"""Run the network-free capacity experiment with bounded resource sampling."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

import httpx

from evals.capacity_protocol import (
    CAPACITY_MANIFEST,
    CAPACITY_PROTOCOL_STATUS,
    CAPACITY_PROTOCOL_VERSION,
    validate_capacity_protocol,
)
from evals.capacity_scoring import build_capacity_summary
from evals.load_scoring import build_load_summary
from evals.run_load import (
    PROJECT_ROOT,
    InFlightTracker,
    LoadEvaluationError,
    _bounded_stub_snapshot,
    _call_delta,
    _git_value,
    _post_generation,
    _run_batch,
    _scan_database_records,
    _stub_calls_match,
    _verify_generation,
    _write_json,
    parse_concurrencies,
    validate_local_base_url,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8002"
DEFAULT_CONCURRENCIES = [1, 4, 8, 16, 32, 64]


def _require_dict(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LoadEvaluationError(f"capacity {name} has an invalid shape")
    return payload


async def _get_json(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    response = await client.get(path)
    if response.status_code != 200:
        raise LoadEvaluationError(f"capacity check failed at {path}")
    try:
        return _require_dict(response.json(), path)
    except ValueError as error:
        raise LoadEvaluationError(f"capacity check at {path} is not JSON") from error


async def capacity_preflight(client: httpx.AsyncClient) -> dict[str, Any]:
    checks: dict[str, int] = {}
    for path in ("/health", "/health/database"):
        response = await client.get(path)
        checks[path] = response.status_code
        if response.status_code != 200:
            raise LoadEvaluationError(f"capacity preflight failed at {path}")

    status = await _get_json(client, "/capacity-test/status")
    expected = {
        "capacity_test": True,
        "protocol_version": CAPACITY_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_PROTOCOL_STATUS,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
    }
    if any(status.get(name) != value for name, value in expected.items()):
        raise LoadEvaluationError("capacity safety or protocol identity mismatch")
    stubs = _bounded_stub_snapshot(status)
    if any(
        stub["provider"] != "stub" or stub["network_enabled"] is not False
        for stub in stubs.values()
    ):
        raise LoadEvaluationError("capacity service has an unsafe external client")

    metrics = await _get_json(client, "/capacity-test/metrics")
    container = _require_dict(metrics.get("container"), "container metrics")
    postgresql = _require_dict(metrics.get("postgresql"), "PostgreSQL metrics")
    metrics_available = (
        isinstance(container.get("cpu_usage_usec"), int)
        and isinstance(container.get("memory_current_bytes"), int)
        and isinstance(postgresql.get("active_connections"), int)
        and isinstance(postgresql.get("pool_checked_out"), int)
    )
    if not metrics_available:
        raise LoadEvaluationError("capacity resource metrics are unavailable")

    return {
        "passed": True,
        "checks": checks,
        "cloud_calls_enabled": False,
        "resource_metrics_available": True,
        "stubs": stubs,
        "initial_metrics": metrics,
    }


async def _sample_metrics(
    client: httpx.AsyncClient,
    *,
    stop: asyncio.Event,
    interval_seconds: float,
    samples: list[dict[str, Any]],
    errors: list[str],
) -> None:
    while True:
        sampled_at = time.perf_counter()
        try:
            payload = await _get_json(client, "/capacity-test/metrics")
            samples.append(
                {
                    "sampled_at_monotonic": sampled_at,
                    "container": payload["container"],
                    "postgresql": payload["postgresql"],
                }
            )
        except (LoadEvaluationError, httpx.HTTPError, KeyError) as error:
            errors.append(type(error).__name__)
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def _run_measured_batch(
    client: httpx.AsyncClient,
    metrics_client: httpx.AsyncClient,
    *,
    run_id: str,
    concurrency: int,
    request_count: int,
    sample_interval_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[str]]:
    semaphore = asyncio.Semaphore(concurrency)
    tracker = InFlightTracker()
    stop = asyncio.Event()
    samples: list[dict[str, Any]] = []
    sample_errors: list[str] = []
    sampler = asyncio.create_task(
        _sample_metrics(
            metrics_client,
            stop=stop,
            interval_seconds=sample_interval_seconds,
            samples=samples,
            errors=sample_errors,
        )
    )
    await asyncio.sleep(0)
    started = time.perf_counter()
    runs = await asyncio.gather(
        *[
            _post_generation(
                client,
                semaphore=semaphore,
                tracker=tracker,
                run_id=run_id,
                phase="measured",
                concurrency=concurrency,
                request_number=index,
            )
            for index in range(1, request_count + 1)
        ]
    )
    elapsed_seconds = time.perf_counter() - started
    stop.set()
    await sampler

    verification_semaphore = asyncio.Semaphore(concurrency)
    verified = await asyncio.gather(
        *[
            _verify_generation(client, run, semaphore=verification_semaphore)
            for run in runs
        ]
    )
    return list(verified), {
        "concurrency": concurrency,
        "elapsed_seconds": elapsed_seconds,
        "max_in_flight": tracker.maximum,
    }, samples, sample_errors


def _maximum(samples: list[dict[str, Any]], section: str, field: str) -> int | None:
    values = [
        sample[section].get(field)
        for sample in samples
        if isinstance(sample.get(section, {}).get(field), int)
    ]
    return max(values) if values else None


def _resource_summary(
    *,
    concurrency: int,
    samples: list[dict[str, Any]],
    sample_errors: list[str],
) -> dict[str, Any]:
    cpu_samples = [
        (sample["sampled_at_monotonic"], sample["container"].get("cpu_usage_usec"))
        for sample in samples
        if isinstance(sample["container"].get("cpu_usage_usec"), int)
    ]
    average_cpu_percent: float | None = None
    if len(cpu_samples) >= 2:
        elapsed = cpu_samples[-1][0] - cpu_samples[0][0]
        cpu_delta = cpu_samples[-1][1] - cpu_samples[0][1]
        if elapsed > 0:
            average_cpu_percent = round(cpu_delta / 1_000_000 / elapsed * 100, 3)

    memory_values = [
        sample["container"].get("memory_current_bytes")
        for sample in samples
        if isinstance(sample["container"].get("memory_current_bytes"), int)
    ]
    return {
        "concurrency": concurrency,
        "sample_count": len(samples),
        "sample_error_count": len(sample_errors),
        "sample_error_types": sorted(set(sample_errors)),
        "api_container": {
            "average_cpu_percent": average_cpu_percent,
            "maximum_memory_current_bytes": max(memory_values) if memory_values else None,
            "maximum_memory_current_mib": (
                round(max(memory_values) / 1024 / 1024, 3)
                if memory_values
                else None
            ),
            "cgroup_memory_peak_bytes": _maximum(
                samples, "container", "memory_peak_bytes"
            ),
            "cpu_throttled_usec_maximum": _maximum(
                samples, "container", "cpu_throttled_usec"
            ),
        },
        "postgresql": {
            "maximum_total_connections": _maximum(
                samples, "postgresql", "total_connections"
            ),
            "maximum_active_connections": _maximum(
                samples, "postgresql", "active_connections"
            ),
            "maximum_idle_connections": _maximum(
                samples, "postgresql", "idle_connections"
            ),
            "maximum_pool_checked_out": _maximum(
                samples, "postgresql", "pool_checked_out"
            ),
            "maximum_pool_overflow": _maximum(
                samples, "postgresql", "pool_overflow"
            ),
            "mean_active_connections": (
                round(
                    mean(
                        sample["postgresql"]["active_connections"]
                        for sample in samples
                    ),
                    3,
                )
                if samples
                else None
            ),
        },
    }


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    lines = [
        "# Exploratory Capacity Report",
        "",
        f"- Run ID: `{config['run_id']}`",
        f"- Git commit: `{config['git_commit']}`",
        f"- Worktree dirty: `{config['git_worktree_dirty']}`",
        "- Cloud calls: `false`",
        "- Cost: `$0.00`",
        f"- Correctness acceptance: `{summary['acceptance_gates']['overall']}`",
        f"- Saturation status: `{summary['saturation_analysis']['status']}`",
        "",
        "| C | RPS | P95 ms | Gain | Efficiency | CPU % | Memory MiB | PG active | Pool out |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tier in summary["tiers"]:
        resources = tier["resources"] or {}
        api = resources.get("api_container", {})
        postgres = resources.get("postgresql", {})
        lines.append(
            "| "
            f"{tier['concurrency']} | {tier['throughput_rps']} | "
            f"{tier['latency_ms']['p95_nearest_rank']} | "
            f"{tier['marginal_throughput_gain']} | {tier['scaling_efficiency']} | "
            f"{api.get('average_cpu_percent')} | "
            f"{api.get('maximum_memory_current_mib')} | "
            f"{postgres.get('maximum_active_connections')} | "
            f"{postgres.get('maximum_pool_checked_out')} |"
        )
    lines.extend(
        [
            "",
            "Saturation signals are heuristics, not acceptance gates. Resource sampling",
            "adds bounded observer overhead and the deterministic provider delay means",
            "these results must not be presented as real OpenAI or S3 capacity.",
            "",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path | None]:
    base_url = validate_local_base_url(args.base_url)
    concurrencies = parse_concurrencies(args.concurrencies)
    if concurrencies[0] != 1:
        raise ValueError("capacity experiment must start at concurrency 1")
    if args.requests_per_tier < 1 or args.warmup_requests < 0:
        raise ValueError("capacity request counts are invalid")
    if args.timeout_seconds <= 0 or args.sample_interval_seconds <= 0:
        raise ValueError("capacity timeout and sample interval must be positive")

    manifest = validate_capacity_protocol(
        concurrencies=concurrencies,
        requests_per_tier=args.requests_per_tier,
        warmup_requests_per_tier=args.warmup_requests,
        timeout_seconds=args.timeout_seconds,
        sample_interval_seconds=args.sample_interval_seconds,
    )
    limits = httpx.Limits(
        max_connections=max(concurrencies) + 8,
        max_keepalive_connections=max(concurrencies) + 8,
    )
    async with (
        httpx.AsyncClient(
            base_url=base_url,
            timeout=args.timeout_seconds,
            limits=limits,
        ) as client,
        httpx.AsyncClient(
            base_url=base_url,
            timeout=args.timeout_seconds,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        ) as metrics_client,
    ):
        preflight = await capacity_preflight(client)
        manifest = validate_capacity_protocol(
            concurrencies=concurrencies,
            requests_per_tier=args.requests_per_tier,
            warmup_requests_per_tier=args.warmup_requests,
            timeout_seconds=args.timeout_seconds,
            sample_interval_seconds=args.sample_interval_seconds,
            preflight_result=preflight,
        )
        if args.validate_only:
            return {
                "valid": True,
                "paid_model_calls": 0,
                "protocol": {
                    "version": manifest["protocol_version"],
                    "status": manifest["status"],
                    "manifest": str(CAPACITY_MANIFEST.relative_to(PROJECT_ROOT)),
                },
                "preflight": preflight,
            }, None

        run_id = (
            f"capacity-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid4().hex[:8]}"
        )
        all_runs: list[dict[str, Any]] = []
        tier_timings: list[dict[str, Any]] = []
        resource_tiers: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        before_stubs = preflight["stubs"]

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

            measured, timing, samples, sample_errors = await _run_measured_batch(
                client,
                metrics_client,
                run_id=run_id,
                concurrency=concurrency,
                request_count=args.requests_per_tier,
                sample_interval_seconds=args.sample_interval_seconds,
            )
            all_runs.extend(measured)
            tier_timings.append(timing)
            resource_tiers.append(
                _resource_summary(
                    concurrency=concurrency,
                    samples=samples,
                    sample_errors=sample_errors,
                )
            )
            print(
                f"concurrency={concurrency} "
                f"completed={sum(run['api_completed'] for run in measured)}/{len(measured)} "
                f"elapsed={timing['elapsed_seconds']:.3f}s samples={len(samples)}"
            )
            if not all(
                run["api_completed"] and run["database_verified"] for run in measured
            ):
                stopped_reason = f"measured_failure_at_concurrency_{concurrency}"
                break

        final_status = await _get_json(client, "/capacity-test/status")
        after_stubs = _bounded_stub_snapshot(final_status)
        stub_delta = _call_delta(before_stubs, after_stubs)
        stub_calls_match = _stub_calls_match(
            stub_delta,
            expected_request_count=len(all_runs),
        )
        database_records = await _scan_database_records(client, run_id=run_id)

    load_summary = build_load_summary(
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
    summary = build_capacity_summary(
        load_summary=load_summary,
        resource_tiers=resource_tiers,
        saturation_signals=manifest["saturation_signals"],
    )
    config = {
        "protocol_version": CAPACITY_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_PROTOCOL_STATUS,
        "protocol_manifest": str(CAPACITY_MANIFEST.relative_to(PROJECT_ROOT)),
        "run_id": run_id,
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_value("status", "--porcelain")),
        "api_base_url": base_url,
        "concurrencies": concurrencies,
        "requests_per_tier": args.requests_per_tier,
        "warmup_requests_per_tier": args.warmup_requests,
        "timeout_seconds": args.timeout_seconds,
        "sample_interval_seconds": args.sample_interval_seconds,
        "cloud_calls": False,
        "langfuse_tracing": False,
        "real_postgresql": True,
        "stub_call_delta": stub_delta,
        "stub_delays_ms": manifest["stub_delays_ms"],
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_capacity_v1"
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
    parser.add_argument("--requests-per-tier", type=int, default=200)
    parser.add_argument("--warmup-requests", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--sample-interval-seconds", type=float, default=0.1)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--fail-on-gate", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result, output_dir = asyncio.run(run(args))
    except (LoadEvaluationError, ValueError, httpx.HTTPError) as error:
        detail = str(error) or type(error).__name__
        raise SystemExit(f"capacity experiment failed safely: {detail}") from None
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
