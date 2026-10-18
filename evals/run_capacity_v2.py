"""Run the network-free high-concurrency Capacity v2 breakpoint experiment."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from evals.capacity_v2_protocol import (
    CAPACITY_V2_MANIFEST,
    CAPACITY_V2_PROTOCOL_STATUS,
    CAPACITY_V2_PROTOCOL_VERSION,
    validate_capacity_v2_protocol,
)
from evals.capacity_v2_scoring import build_capacity_v2_summary
from evals.load_scoring import build_load_summary
from evals.run_capacity import (
    _get_json,
    _resource_summary,
    _run_measured_batch,
)
from evals.run_load import (
    PROJECT_ROOT,
    LoadEvaluationError,
    _bounded_stub_snapshot,
    _call_delta,
    _git_value,
    _run_batch,
    _scan_database_records,
    _stub_calls_match,
    _write_json,
    parse_concurrencies,
    validate_local_base_url,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8003"
DEFAULT_CONCURRENCIES = [64, 96, 128, 192, 256]
STATUS_PATH = "/capacity-v2-test/status"
METRICS_PATH = "/capacity-v2-test/metrics"


async def capacity_v2_preflight(client: httpx.AsyncClient) -> dict[str, Any]:
    """Prove service identity, cloud isolation, and metric availability."""
    checks: dict[str, int] = {}
    for path in ("/health", "/health/database"):
        response = await client.get(path)
        checks[path] = response.status_code
        if response.status_code != 200:
            raise LoadEvaluationError(f"Capacity v2 preflight failed at {path}")

    status = await _get_json(client, STATUS_PATH)
    expected = {
        "capacity_v2_test": True,
        "protocol_version": CAPACITY_V2_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_V2_PROTOCOL_STATUS,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
    }
    if any(status.get(name) != value for name, value in expected.items()):
        raise LoadEvaluationError("Capacity v2 safety or identity mismatch")
    stubs = _bounded_stub_snapshot(status)
    if any(
        stub["provider"] != "stub" or stub["network_enabled"] is not False
        for stub in stubs.values()
    ):
        raise LoadEvaluationError("Capacity v2 has an unsafe external client")

    metrics = await _get_json(client, METRICS_PATH)
    container = metrics.get("container")
    postgresql = metrics.get("postgresql")
    metrics_available = (
        isinstance(container, dict)
        and isinstance(postgresql, dict)
        and isinstance(container.get("cpu_usage_usec"), int)
        and isinstance(container.get("memory_current_bytes"), int)
        and isinstance(postgresql.get("active_connections"), int)
        and isinstance(postgresql.get("pool_checked_out"), int)
    )
    if not metrics_available:
        raise LoadEvaluationError("Capacity v2 resource metrics are unavailable")

    return {
        "passed": True,
        "checks": checks,
        "cloud_calls_enabled": False,
        "resource_metrics_available": True,
        "stubs": stubs,
        "initial_metrics": metrics,
    }


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    lines = [
        "# Capacity v2 Breakpoint Report",
        "",
        f"- Run ID: `{config['run_id']}`",
        f"- Git commit: `{config['git_commit']}`",
        f"- Worktree dirty: `{config['git_worktree_dirty']}`",
        "- Cloud calls: `false`",
        "- Cost: `$0.00`",
        f"- Correctness acceptance: `{summary['acceptance_gates']['overall']}`",
        f"- Saturation status: `{summary['saturation_analysis']['status']}`",
        "",
        (
            "| C | RPS | P95 ms | Marginal gain | Marginal efficiency | "
            "Baseline efficiency | CPU % | Memory MiB | PG active | Pool out |"
        ),
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tier in summary["tiers"]:
        resources = tier["resources"] or {}
        api = resources.get("api_container", {})
        postgres = resources.get("postgresql", {})
        lines.append(
            "| "
            f"{tier['concurrency']} | {tier['throughput_rps']} | "
            f"{tier['latency_ms']['p95_nearest_rank']} | "
            f"{tier['marginal_throughput_gain']} | "
            f"{tier['marginal_scaling_efficiency']} | "
            f"{tier['scaling_efficiency']} | "
            f"{api.get('average_cpu_percent')} | "
            f"{api.get('maximum_memory_current_mib')} | "
            f"{postgres.get('maximum_active_connections')} | "
            f"{postgres.get('maximum_pool_checked_out')} |"
        )
    lines.extend(
        [
            "",
            "Saturation signals are heuristics, not acceptance gates. Capacity v2",
            "uses a concurrency-64 baseline and normalizes marginal throughput gain",
            "by the marginal concurrency increase. Results cover one local worker,",
            "real PostgreSQL, and deterministic network-free provider stubs only.",
            "",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path | None]:
    base_url = validate_local_base_url(args.base_url)
    concurrencies = parse_concurrencies(args.concurrencies)
    if args.requests_per_tier < max(concurrencies):
        raise ValueError("Capacity v2 requests per tier must cover maximum concurrency")
    if args.warmup_requests < 0:
        raise ValueError("Capacity v2 warm-up count must be non-negative")
    if args.timeout_seconds <= 0 or args.sample_interval_seconds <= 0:
        raise ValueError("Capacity v2 timeout and sample interval must be positive")

    manifest = validate_capacity_v2_protocol(
        concurrencies=concurrencies,
        requests_per_tier=args.requests_per_tier,
        warmup_requests_per_tier=args.warmup_requests,
        timeout_seconds=args.timeout_seconds,
        sample_interval_seconds=args.sample_interval_seconds,
    )
    baseline_concurrency = int(manifest["metrics"]["baseline_concurrency"])
    if concurrencies[0] != baseline_concurrency:
        raise ValueError("Capacity v2 must start at the locked baseline concurrency")

    limits = httpx.Limits(
        max_connections=max(concurrencies) + 16,
        max_keepalive_connections=max(concurrencies) + 16,
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
        preflight = await capacity_v2_preflight(client)
        manifest = validate_capacity_v2_protocol(
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
                    "manifest": str(
                        CAPACITY_V2_MANIFEST.relative_to(PROJECT_ROOT)
                    ),
                },
                "preflight": preflight,
            }, None

        run_id = (
            f"capacity-v2-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
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
                request_count=args.requests_per_tier,
                sample_interval_seconds=args.sample_interval_seconds,
                metrics_path=METRICS_PATH,
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
    summary = build_capacity_v2_summary(
        load_summary=load_summary,
        resource_tiers=resource_tiers,
        baseline_concurrency=baseline_concurrency,
        saturation_signals=manifest["saturation_signals"],
    )
    config = {
        "protocol_version": CAPACITY_V2_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_V2_PROTOCOL_STATUS,
        "protocol_manifest": str(CAPACITY_V2_MANIFEST.relative_to(PROJECT_ROOT)),
        "run_id": run_id,
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_value("status", "--porcelain")),
        "api_base_url": base_url,
        "concurrencies": concurrencies,
        "baseline_concurrency": baseline_concurrency,
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
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_capacity_v2"
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
    parser.add_argument("--requests-per-tier", type=int, default=1000)
    parser.add_argument("--warmup-requests", type=int, default=64)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--sample-interval-seconds", type=float, default=0.05)
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
        raise SystemExit(f"Capacity v2 failed safely: {detail}") from None
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
