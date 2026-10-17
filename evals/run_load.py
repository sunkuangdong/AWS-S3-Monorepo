"""Run a local, network-isolated load benchmark against real PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from evals.load_protocol import (
    LOAD_MANIFEST,
    LOAD_PROTOCOL_STATUS,
    LOAD_PROTOCOL_VERSION,
    validate_load_protocol,
)
from evals.load_scoring import build_load_summary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_CONCURRENCIES = [1, 4, 8, 16]


class LoadEvaluationError(RuntimeError):
    """A bounded error safe to print and persist without response bodies."""


class InFlightTracker:
    def __init__(self) -> None:
        self.current = 0
        self.maximum = 0

    def enter(self) -> None:
        self.current += 1
        self.maximum = max(self.maximum, self.current)

    def exit(self) -> None:
        self.current -= 1


def validate_local_base_url(value: str) -> str:
    """Allow only an unauthenticated loopback HTTP endpoint."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("load evaluation base URL must be a plain loopback HTTP URL")
    if parsed.port is None:
        raise ValueError("load evaluation base URL must include an explicit port")
    return value.rstrip("/")


def parse_concurrencies(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise ValueError("concurrencies must be comma-separated integers") from error
    if not values or any(item < 1 for item in values):
        raise ValueError("concurrencies must contain positive integers")
    if len(values) != len(set(values)):
        raise ValueError("concurrencies must not contain duplicates")
    if values != sorted(values):
        raise ValueError("concurrencies must be in ascending order")
    return values


def _git_value(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _bounded_stub_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    stubs = payload.get("stubs")
    if not isinstance(stubs, dict):
        raise LoadEvaluationError("load-test status is missing stub metadata")
    result: dict[str, Any] = {}
    for name in ("storage", "vision", "image_generation"):
        stub = stubs.get(name)
        if not isinstance(stub, dict):
            raise LoadEvaluationError(f"load-test status is missing {name} stub")
        calls = stub.get("calls", {})
        if not isinstance(calls, dict) or not all(
            isinstance(key, str) and isinstance(value, int)
            for key, value in calls.items()
        ):
            raise LoadEvaluationError(f"invalid {name} stub call counts")
        result[name] = {
            "provider": stub.get("provider"),
            "network_enabled": stub.get("network_enabled"),
            "delay_ms": stub.get("delay_ms"),
            "calls": calls,
        }
    return result


async def preflight(client: httpx.AsyncClient) -> dict[str, Any]:
    """Verify liveness, real PostgreSQL, and network-free dependency overrides."""
    checks: dict[str, Any] = {}
    for path in ("/health", "/health/database"):
        response = await client.get(path)
        checks[path] = response.status_code
        if response.status_code != 200:
            raise LoadEvaluationError(f"preflight failed at {path}: HTTP status")

    response = await client.get("/load-test/status")
    if response.status_code != 200:
        raise LoadEvaluationError("preflight failed at /load-test/status")
    try:
        status = response.json()
    except ValueError as error:
        raise LoadEvaluationError("load-test status is not JSON") from error
    if not isinstance(status, dict):
        raise LoadEvaluationError("load-test status has an invalid shape")
    if (
        status.get("protocol_version") != LOAD_PROTOCOL_VERSION
        or status.get("protocol_status") != LOAD_PROTOCOL_STATUS
    ):
        raise LoadEvaluationError(
            "load-test service protocol identity does not match the runner"
        )

    required_flags = {
        "load_test": True,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
    }
    if any(status.get(name) is not expected for name, expected in required_flags.items()):
        raise LoadEvaluationError("load-test safety flags do not match the protocol")

    stubs = _bounded_stub_snapshot(status)
    if any(
        stub["provider"] != "stub" or stub["network_enabled"] is not False
        for stub in stubs.values()
    ):
        raise LoadEvaluationError("one or more external-service stubs are unsafe")
    return {
        "passed": True,
        "protocol_version": status["protocol_version"],
        "protocol_status": status["protocol_status"],
        "checks": checks,
        "cloud_calls_enabled": False,
        "stubs": stubs,
    }


async def _post_generation(
    client: httpx.AsyncClient,
    *,
    semaphore: asyncio.Semaphore,
    tracker: InFlightTracker,
    run_id: str,
    phase: str,
    concurrency: int,
    request_number: int,
) -> dict[str, Any]:
    request_id = f"{run_id}-{phase}-c{concurrency}-{request_number:04d}"
    prompt = f"load-eval:{run_id}:c{concurrency}:{phase}:{request_number:04d}"
    async with semaphore:
        tracker.enter()
        started = time.perf_counter()
        try:
            response = await client.post(
                "/api/v1/images/generations",
                headers={"X-Request-ID": request_id},
                json={
                    "prompt": prompt,
                    "width": 1024,
                    "height": 1024,
                },
            )
            latency_ms = round((time.perf_counter() - started) * 1_000, 3)
            try:
                payload = response.json()
            except ValueError:
                payload = None
            valid_payload = isinstance(payload, dict)
            generation_id = payload.get("id") if valid_payload else None
            api_completed = bool(
                response.status_code == 201
                and generation_id
                and payload.get("status") == "completed"
                and payload.get("output_object_key")
                and payload.get("output_url")
            )
            return {
                "phase": phase,
                "concurrency": concurrency,
                "request_number": request_number,
                "request_id": request_id,
                "status_code": response.status_code,
                "api_completed": api_completed,
                "generation_id": str(generation_id) if generation_id else None,
                "generation_status": payload.get("status") if valid_payload else None,
                "output_present": bool(
                    valid_payload and payload.get("output_object_key")
                ),
                "latency_ms": latency_ms,
                "database_verified": False,
                "error_type": None if api_completed else "UnexpectedAPIResponse",
            }
        except httpx.HTTPError as error:
            return {
                "phase": phase,
                "concurrency": concurrency,
                "request_number": request_number,
                "request_id": request_id,
                "status_code": None,
                "api_completed": False,
                "generation_id": None,
                "generation_status": None,
                "output_present": False,
                "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
                "database_verified": False,
                "error_type": type(error).__name__,
            }
        finally:
            tracker.exit()


async def _verify_generation(
    client: httpx.AsyncClient,
    run: dict[str, Any],
    *,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    generation_id = run["generation_id"]
    if not generation_id:
        return run
    async with semaphore:
        try:
            response = await client.get(f"/api/v1/images/generations/{generation_id}")
            payload = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as error:
            return {
                **run,
                "database_verified": False,
                "verification_error_type": type(error).__name__,
            }
    verified = bool(
        isinstance(payload, dict)
        and payload.get("id") == generation_id
        and payload.get("status") == "completed"
        and payload.get("output_object_key")
        and payload.get("output_url")
    )
    return {
        **run,
        "database_verified": verified,
        "verification_error_type": None if verified else "DatabaseStateMismatch",
    }


async def _run_batch(
    client: httpx.AsyncClient,
    *,
    run_id: str,
    phase: str,
    concurrency: int,
    request_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    tracker = InFlightTracker()
    started = time.perf_counter()
    runs = await asyncio.gather(
        *[
            _post_generation(
                client,
                semaphore=semaphore,
                tracker=tracker,
                run_id=run_id,
                phase=phase,
                concurrency=concurrency,
                request_number=index,
            )
            for index in range(1, request_count + 1)
        ]
    )
    elapsed_seconds = time.perf_counter() - started
    verification_semaphore = asyncio.Semaphore(concurrency)
    verified_runs = await asyncio.gather(
        *[
            _verify_generation(
                client,
                run,
                semaphore=verification_semaphore,
            )
            for run in runs
        ]
    )
    return list(verified_runs), {
        "concurrency": concurrency,
        "elapsed_seconds": elapsed_seconds,
        "max_in_flight": tracker.maximum,
    }


def _call_delta(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for stub_name in ("storage", "vision", "image_generation"):
        before_calls = Counter(before[stub_name]["calls"])
        after_calls = Counter(after[stub_name]["calls"])
        result[stub_name] = dict(sorted((after_calls - before_calls).items()))
    return result


def _stub_calls_match(
    delta: dict[str, dict[str, int]],
    *,
    expected_request_count: int,
) -> bool:
    return (
        delta["image_generation"] == {"generate_image": expected_request_count}
        and delta["vision"] == {}
        and delta["storage"].get("upload_generated_image")
        == expected_request_count
        and delta["storage"].get("create_presigned_download_url")
        == expected_request_count * 2
        and set(delta["storage"])
        <= {"upload_generated_image", "create_presigned_download_url"}
    )


async def _scan_database_records(
    client: httpx.AsyncClient,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    """Read real API-backed records but retain no prompts, URLs, or object keys."""
    prefix = f"load-eval:{run_id}:"
    offset = 0
    records: list[dict[str, Any]] = []
    while True:
        response = await client.get(
            "/api/v1/images/generations",
            params={"limit": 100, "offset": offset},
        )
        if response.status_code != 200:
            raise LoadEvaluationError("database record scan returned a non-200 status")
        try:
            payload = response.json()
        except ValueError as error:
            raise LoadEvaluationError("database record scan returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise LoadEvaluationError("database record scan returned an invalid shape")
        items = payload["items"]
        for item in items:
            if isinstance(item, dict) and str(item.get("user_prompt", "")).startswith(
                prefix
            ):
                records.append(
                    {
                        "id": item.get("id"),
                        "status": item.get("status"),
                        "generation_type": item.get("generation_type"),
                        "output_present": bool(item.get("output_object_key")),
                    }
                )
        offset += len(items)
        total = payload.get("total")
        if not items or not isinstance(total, int) or offset >= total:
            break
        if offset >= 10_000:
            raise LoadEvaluationError("database record scan exceeded its safety limit")
    return records


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    def display(value: Any) -> str:
        return "n/a" if value is None else str(value)

    lines = [
        "# Load Evaluation Report",
        "",
        f"- Run ID: `{config['run_id']}`",
        f"- Protocol: `{config['protocol_version']}` ({config['protocol_status']})",
        f"- Protocol compliant: `{config['protocol_compliant']}`",
        f"- Git commit: `{config['git_commit']}`",
        "- Cloud calls: `false`",
        "- Model/S3 cost: `$0.00`",
        f"- Overall acceptance: `{summary['acceptance_gates']['overall']}`",
        "",
        "## Performance by concurrency",
        "",
        "| Concurrency | Requests | Success | RPS | P50 ms | P95 ms | Max in flight |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tier in summary["tiers"]:
        lines.append(
            "| "
            f"{tier['concurrency']} | {tier['request_count']} | "
            f"{display(tier['success_rate'])} | {display(tier['throughput_rps'])} | "
            f"{display(tier['latency_ms']['p50_nearest_rank'])} | "
            f"{display(tier['latency_ms']['p95_nearest_rank'])} | "
            f"{tier['max_in_flight']} |"
        )
    lines.extend(
        [
            "",
            "## Correctness",
            "",
            f"- Database records: `{summary['database']['record_count']}`",
            f"- Database states: `{json.dumps(summary['database']['status_counts'])}`",
            f"- Server errors: `{summary['errors']['server_error_count']}`",
            f"- Transport errors: `{summary['errors']['transport_error_count']}`",
            "",
            "## Acceptance gates",
            "",
        ]
    )
    lines.extend(
        f"- {name}: `{value}`"
        for name, value in summary["acceptance_gates"].items()
    )
    lines.extend(
        [
            "",
            "Latency measures the generation POST request only. Database verification",
            "runs after each measured batch and is excluded from throughput timing.",
            "Stub latency is deterministic and must not be presented as cloud-provider latency.",
            "",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path | None]:
    base_url = validate_local_base_url(args.base_url)
    concurrencies = parse_concurrencies(args.concurrencies)
    if concurrencies[0] != 1:
        raise ValueError("the first concurrency tier must be 1 for baseline scaling")
    if args.requests_per_tier < 1:
        raise ValueError("requests_per_tier must be positive")
    if args.warmup_requests < 0:
        raise ValueError("warmup_requests must be non-negative")
    if args.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    manifest = validate_load_protocol(
        concurrencies=concurrencies,
        requests_per_tier=args.requests_per_tier,
        warmup_requests_per_tier=args.warmup_requests,
        timeout_seconds=args.timeout_seconds,
        allow_parameter_deviation=args.allow_protocol_deviation,
    )

    limits = httpx.Limits(
        max_connections=max(concurrencies) + 4,
        max_keepalive_connections=max(concurrencies) + 4,
    )
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=args.timeout_seconds,
        limits=limits,
    ) as client:
        preflight_result = await preflight(client)
        manifest = validate_load_protocol(
            concurrencies=concurrencies,
            requests_per_tier=args.requests_per_tier,
            warmup_requests_per_tier=args.warmup_requests,
            timeout_seconds=args.timeout_seconds,
            preflight_result=preflight_result,
            allow_parameter_deviation=args.allow_protocol_deviation,
        )
        if args.validate_only:
            return {
                "valid": True,
                "paid_model_calls": 0,
                "protocol": {
                    "version": manifest["protocol_version"],
                    "status": manifest["status"],
                    "compliant": not args.allow_protocol_deviation,
                    "manifest": str(LOAD_MANIFEST.relative_to(PROJECT_ROOT)),
                },
                "preflight": preflight_result,
            }, None

        run_id = f"load-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        all_runs: list[dict[str, Any]] = []
        tier_timings: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        before_stubs = preflight_result["stubs"]

        for concurrency in concurrencies:
            warmups, _ = await _run_batch(
                client,
                run_id=run_id,
                phase="warmup",
                concurrency=concurrency,
                request_count=args.warmup_requests,
            )
            all_runs.extend(warmups)
            if not all(run["api_completed"] and run["database_verified"] for run in warmups):
                stopped_reason = f"warmup_failure_at_concurrency_{concurrency}"
                break

            measured, timing = await _run_batch(
                client,
                run_id=run_id,
                phase="measured",
                concurrency=concurrency,
                request_count=args.requests_per_tier,
            )
            all_runs.extend(measured)
            tier_timings.append(timing)
            completed = sum(run["api_completed"] for run in measured)
            print(
                f"concurrency={concurrency} completed={completed}/{len(measured)} "
                f"elapsed={timing['elapsed_seconds']:.3f}s"
            )
            if completed != len(measured) or not all(
                run["database_verified"] for run in measured
            ):
                stopped_reason = f"measured_failure_at_concurrency_{concurrency}"
                break

        status_response = await client.get("/load-test/status")
        if status_response.status_code != 200:
            raise LoadEvaluationError("final load-test status check failed")
        try:
            status_payload = status_response.json()
        except ValueError as error:
            raise LoadEvaluationError("final load-test status is not JSON") from error
        if not isinstance(status_payload, dict):
            raise LoadEvaluationError("final load-test status has an invalid shape")
        after_stubs = _bounded_stub_snapshot(status_payload)
        stub_delta = _call_delta(before_stubs, after_stubs)
        expected_request_count = len(all_runs)
        stub_calls_match = _stub_calls_match(
            stub_delta,
            expected_request_count=expected_request_count,
        )
        database_records = await _scan_database_records(client, run_id=run_id)

    summary = build_load_summary(
        runs=all_runs,
        tier_timings=tier_timings,
        concurrencies=concurrencies,
        requests_per_tier=args.requests_per_tier,
        warmup_requests_per_tier=args.warmup_requests,
        database_records=database_records,
        preflight_passed=True,
        cloud_calls_enabled=False,
        stub_calls_match_workload=stub_calls_match,
        stopped_reason=stopped_reason,
    )
    config = {
        "protocol_version": LOAD_PROTOCOL_VERSION,
        "protocol_status": LOAD_PROTOCOL_STATUS,
        "protocol_manifest": str(LOAD_MANIFEST.relative_to(PROJECT_ROOT)),
        "protocol_compliant": not args.allow_protocol_deviation,
        "run_id": run_id,
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_value("status", "--porcelain")),
        "api_base_url": base_url,
        "concurrencies": concurrencies,
        "requests_per_tier": args.requests_per_tier,
        "warmup_requests_per_tier": args.warmup_requests,
        "timeout_seconds": args.timeout_seconds,
        "cloud_calls": False,
        "langfuse_tracing": False,
        "real_postgresql": True,
        "stub_call_delta": stub_delta,
        "stub_delays_ms": {
            name: details["delay_ms"] for name, details in after_stubs.items()
        },
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_load_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "raw_runs.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in all_runs),
        encoding="utf-8",
    )
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "config.json", config)
    (output_dir / "report.md").write_text(
        _render_report(summary, config),
        encoding="utf-8",
    )
    return summary, output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--concurrencies",
        default=",".join(str(value) for value in DEFAULT_CONCURRENCIES),
    )
    parser.add_argument("--requests-per-tier", type=int, default=40)
    parser.add_argument("--warmup-requests", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--fail-on-gate", action="store_true")
    parser.add_argument(
        "--allow-protocol-deviation",
        action="store_true",
        help=(
            "allow exploratory parameter changes and mark the result as "
            "non-compliant with load protocol v1"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result, output_dir = asyncio.run(run(args))
    except (LoadEvaluationError, ValueError, httpx.HTTPError) as error:
        raise SystemExit(f"load evaluation failed safely: {error}") from None
    if output_dir is None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"Results: {output_dir.relative_to(PROJECT_ROOT)}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.fail_on_gate and not result["acceptance_gates"]["overall"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
