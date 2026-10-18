"""Run the network-free Capacity v3 connection-pool experiment."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from evals.capacity_v2_scoring import build_capacity_v2_summary
from evals.capacity_v3_protocol import (
    CAPACITY_V3_MANIFEST,
    CAPACITY_V3_PROTOCOL_STATUS,
    CAPACITY_V3_PROTOCOL_VERSION,
    load_capacity_v3_manifest,
    validate_capacity_v3_protocol,
)
from evals.load_scoring import build_load_summary
from evals.run_capacity import _get_json, _resource_summary, _run_measured_batch
from evals.run_capacity_v2 import (
    _capacity_v2_stub_calls_match,
    _retry_verification_transport_failures,
)
from evals.run_load import (
    PROJECT_ROOT,
    LoadEvaluationError,
    _bounded_stub_snapshot,
    _call_delta,
    _git_value,
    _run_batch,
    _write_json,
    validate_local_base_url,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8004"
STATUS_PATH = "/capacity-v3-test/status"
METRICS_PATH = "/capacity-v3-test/metrics"
RECORDS_PATH = "/capacity-v3-test/records"
V2_EVIDENCE = PROJECT_ROOT / "evals/evidence/capacity_v2_summary.json"


def _mode_parameters(mode: str) -> dict[str, Any]:
    manifest = load_capacity_v3_manifest()
    mode_config = manifest["runner"]["modes"].get(mode)
    if not isinstance(mode_config, dict):
        raise TypeError(f"unknown Capacity v3 mode: {mode}")
    return {
        "concurrencies": [int(value) for value in mode_config["concurrencies"]],
        "requests_per_tier": int(mode_config["requests_per_tier"]),
        "warmup_requests_per_tier": int(
            mode_config["warmup_requests_per_tier"]
        ),
        "timeout_seconds": float(manifest["runner"]["timeout_seconds"]),
        "sample_interval_seconds": float(
            manifest["runner"]["sample_interval_seconds"]
        ),
    }


async def capacity_v3_preflight(client: httpx.AsyncClient) -> dict[str, Any]:
    checks: dict[str, int] = {}
    for path in ("/health", "/health/database"):
        response = await client.get(path)
        checks[path] = response.status_code
        if response.status_code != 200:
            raise LoadEvaluationError(f"Capacity v3 preflight failed at {path}")

    status = await _get_json(client, STATUS_PATH)
    expected = {
        "capacity_v3_test": True,
        "protocol_version": CAPACITY_V3_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_V3_PROTOCOL_STATUS,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
    }
    if any(status.get(name) != value for name, value in expected.items()):
        raise LoadEvaluationError("Capacity v3 safety or identity mismatch")
    database_pool = status.get("database_pool")
    if database_pool != {
        "pool_size": 20,
        "max_overflow": 20,
        "timeout_seconds": 30,
    }:
        raise LoadEvaluationError("Capacity v3 database pool mismatch")
    stubs = _bounded_stub_snapshot(status)
    if any(
        stub["provider"] != "stub" or stub["network_enabled"] is not False
        for stub in stubs.values()
    ):
        raise LoadEvaluationError("Capacity v3 has an unsafe external client")

    metrics = await _get_json(client, METRICS_PATH)
    container = metrics.get("container")
    postgresql = metrics.get("postgresql")
    metrics_available = (
        isinstance(container, dict)
        and isinstance(postgresql, dict)
        and isinstance(container.get("cpu_usage_usec"), int)
        and isinstance(container.get("memory_current_bytes"), int)
        and isinstance(postgresql.get("active_connections"), int)
        and postgresql.get("pool_size") == 20
    )
    if not metrics_available:
        raise LoadEvaluationError("Capacity v3 resource metrics are unavailable")

    return {
        "passed": True,
        "checks": checks,
        "cloud_calls_enabled": False,
        "resource_metrics_available": True,
        "database_pool": database_pool,
        "stubs": stubs,
        "initial_metrics": metrics,
    }


async def _scan_capacity_v3_records(
    client: httpx.AsyncClient,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    response = await client.get(RECORDS_PATH, params={"run_id": run_id})
    if response.status_code != 200:
        raise LoadEvaluationError("Capacity v3 record scan returned non-200 status")
    try:
        payload = response.json()
    except ValueError as error:
        raise LoadEvaluationError(
            "Capacity v3 record scan returned invalid JSON"
        ) from error
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise LoadEvaluationError("Capacity v3 record scan returned invalid shape")
    return records


def _comparison_to_v2(summary: dict[str, Any]) -> dict[str, Any]:
    evidence = json.loads(V2_EVIDENCE.read_text(encoding="utf-8"))
    v2_tiers = {int(tier["concurrency"]): tier for tier in evidence["tiers"]}
    comparisons: list[dict[str, Any]] = []
    for tier in summary["tiers"]:
        concurrency = int(tier["concurrency"])
        if not tier["executed"] or concurrency not in v2_tiers:
            continue
        reference = v2_tiers[concurrency]
        reference_rps = float(reference["throughput_rps"])
        reference_p95 = float(reference["latency_ms"]["p95_nearest_rank"])
        comparisons.append(
            {
                "concurrency": concurrency,
                "v2_throughput_rps": reference_rps,
                "v3_throughput_rps": tier["throughput_rps"],
                "throughput_change_ratio": round(
                    float(tier["throughput_rps"]) / reference_rps - 1,
                    3,
                ),
                "v2_p95_latency_ms": reference_p95,
                "v3_p95_latency_ms": tier["latency_ms"]["p95_nearest_rank"],
                "p95_change_ratio": round(
                    float(tier["latency_ms"]["p95_nearest_rank"])
                    / reference_p95
                    - 1,
                    3,
                ),
                "v2_success_rate": reference["success_rate"],
                "v3_success_rate": tier["success_rate"],
            }
        )
    return {
        "reference": "evals/evidence/capacity_v2_summary.json",
        "caveat": (
            "Run-to-run variance remains; a full repeated v3 run is required "
            "before claiming a durable improvement."
        ),
        "tiers": comparisons,
    }


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    lines = [
        "# Capacity v3 Connection-Pool Experiment",
        "",
        f"- Mode: `{config['mode']}`",
        f"- Run ID: `{config['run_id']}`",
        f"- Git commit: `{config['git_commit']}`",
        f"- Worktree dirty: `{config['git_worktree_dirty']}`",
        "- Single change: SQLAlchemy pool `5+10` to `20+20`",
        "- Cloud calls / cost: `false` / `$0.00`",
        f"- Overall acceptance: `{summary['acceptance_gates']['overall']}`",
        "",
        "| C | Success | RPS | P95 ms | CPU % | Pool out | Overflow |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tier in summary["tiers"]:
        if not tier["executed"]:
            continue
        resources = tier["resources"]
        lines.append(
            "| "
            f"{tier['concurrency']} | {tier['success_rate']} | "
            f"{tier['throughput_rps']} | "
            f"{tier['latency_ms']['p95_nearest_rank']} | "
            f"{resources['api_container']['average_cpu_percent']} | "
            f"{resources['postgresql']['maximum_pool_checked_out']} | "
            f"{resources['postgresql']['maximum_pool_overflow']} |"
        )
    lines.extend(
        [
            "",
            "This candidate changes only connection-pool capacity. The pilot is",
            "directional; durable improvement requires the full repeated v3 phase.",
            "",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path | None]:
    base_url = validate_local_base_url(args.base_url)
    parameters = _mode_parameters(args.mode)
    concurrencies = parameters["concurrencies"]
    limits = httpx.Limits(
        max_connections=max(concurrencies) + 16,
        max_keepalive_connections=max(concurrencies) + 16,
    )
    async with (
        httpx.AsyncClient(
            base_url=base_url,
            timeout=parameters["timeout_seconds"],
            limits=limits,
        ) as client,
        httpx.AsyncClient(
            base_url=base_url,
            timeout=parameters["timeout_seconds"],
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        ) as metrics_client,
    ):
        preflight = await capacity_v3_preflight(client)
        manifest = validate_capacity_v3_protocol(
            mode=args.mode,
            preflight_result=preflight,
            **parameters,
        )
        if args.validate_only:
            return {
                "valid": True,
                "paid_model_calls": 0,
                "mode": args.mode,
                "protocol": {
                    "version": manifest["protocol_version"],
                    "status": manifest["status"],
                    "manifest": str(CAPACITY_V3_MANIFEST.relative_to(PROJECT_ROOT)),
                },
                "preflight": preflight,
            }, None

        run_id = (
            f"capacity-v3-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid4().hex[:8]}"
        )
        all_runs: list[dict[str, Any]] = []
        tier_timings: list[dict[str, Any]] = []
        resource_tiers: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        verification_retries = {"attempted": 0, "recovered": 0}
        before_stubs = preflight["stubs"]

        for concurrency in concurrencies:
            warmups, _ = await _run_batch(
                client,
                run_id=run_id,
                phase="warmup",
                concurrency=concurrency,
                request_count=parameters["warmup_requests_per_tier"],
            )
            warmups, retry_result = await _retry_verification_transport_failures(
                client,
                warmups,
            )
            for name in verification_retries:
                verification_retries[name] += retry_result[name]
            all_runs.extend(warmups)
            if not all(
                run["api_completed"] and run["database_verified"]
                for run in warmups
            ):
                stopped_reason = f"warmup_failure_at_concurrency_{concurrency}"
                break

            measured, timing, samples, sample_errors = await _run_measured_batch(
                client,
                metrics_client,
                run_id=run_id,
                concurrency=concurrency,
                request_count=parameters["requests_per_tier"],
                sample_interval_seconds=parameters["sample_interval_seconds"],
                metrics_path=METRICS_PATH,
            )
            measured, retry_result = await _retry_verification_transport_failures(
                client,
                measured,
            )
            for name in verification_retries:
                verification_retries[name] += retry_result[name]
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
                f"completed={sum(run['api_completed'] for run in measured)}/"
                f"{len(measured)} elapsed={timing['elapsed_seconds']:.3f}s "
                f"samples={len(samples)}"
            )
            if not all(
                run["api_completed"] and run["database_verified"]
                for run in measured
            ):
                stopped_reason = f"measured_failure_at_concurrency_{concurrency}"
                break

        final_status = await _get_json(client, STATUS_PATH)
        after_stubs = _bounded_stub_snapshot(final_status)
        stub_delta = _call_delta(before_stubs, after_stubs)
        stub_calls_match = _capacity_v2_stub_calls_match(
            stub_delta,
            expected_request_count=len(all_runs),
            verification_retry_attempts=verification_retries["attempted"],
        )
        database_records = await _scan_capacity_v3_records(client, run_id=run_id)

    load_summary = build_load_summary(
        runs=all_runs,
        tier_timings=tier_timings,
        concurrencies=concurrencies,
        requests_per_tier=parameters["requests_per_tier"],
        warmup_requests_per_tier=parameters["warmup_requests_per_tier"],
        database_records=database_records,
        preflight_passed=True,
        cloud_calls_enabled=False,
        stub_calls_match_workload=stub_calls_match,
        stopped_reason=stopped_reason,
    )
    summary = build_capacity_v2_summary(
        load_summary=load_summary,
        resource_tiers=resource_tiers,
        baseline_concurrency=64,
        saturation_signals=manifest["saturation_signals"],
    )
    summary["experiment_type"] = "capacity_optimization_v3"
    summary["experiment_mode"] = args.mode
    summary["comparison_to_capacity_v2_primary"] = _comparison_to_v2(summary)

    config = {
        "protocol_version": CAPACITY_V3_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_V3_PROTOCOL_STATUS,
        "protocol_manifest": str(CAPACITY_V3_MANIFEST.relative_to(PROJECT_ROOT)),
        "mode": args.mode,
        "run_id": run_id,
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_value("status", "--porcelain")),
        "api_base_url": base_url,
        **parameters,
        "database_pool": preflight["database_pool"],
        "single_variable_optimization": "sqlalchemy_connection_pool_capacity",
        "cloud_calls": False,
        "langfuse_tracing": False,
        "real_postgresql": True,
        "stub_call_delta": stub_delta,
        "verification_transport_retries": verification_retries,
        "stub_delays_ms": manifest["stub_delays_ms"],
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = "capacity_v3_pilot" if args.mode == "pilot" else "capacity_v3"
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_{suffix}"
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
    parser.add_argument("--mode", choices=("pilot", "full"), default="pilot")
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
        raise SystemExit(f"Capacity v3 failed safely: {detail}") from None
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
