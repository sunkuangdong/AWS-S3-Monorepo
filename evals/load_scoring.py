"""Deterministic aggregation and acceptance gates for load evaluation."""

from __future__ import annotations

import math
from collections import Counter
from statistics import mean
from typing import Any


def nearest_rank(values: list[float], percentile: float) -> float | None:
    """Return a nearest-rank percentile without interpolation."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _round(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _tier_summary(
    runs: list[dict[str, Any]],
    *,
    concurrency: int,
    elapsed_seconds: float,
    max_in_flight: int,
    baseline_throughput: float | None,
) -> dict[str, Any]:
    latencies = [float(run["latency_ms"]) for run in runs]
    success_count = sum(bool(run["api_completed"]) for run in runs)
    verified_count = sum(bool(run["database_verified"]) for run in runs)
    throughput = len(runs) / elapsed_seconds if elapsed_seconds > 0 else 0.0
    speedup = (
        throughput / baseline_throughput
        if baseline_throughput is not None and baseline_throughput > 0
        else 1.0
    )
    efficiency = speedup / concurrency if concurrency > 0 else 0.0
    return {
        "concurrency": concurrency,
        "request_count": len(runs),
        "completed_count": success_count,
        "success_rate": success_count / len(runs) if runs else None,
        "database_verified_count": verified_count,
        "database_consistency_rate": verified_count / len(runs) if runs else None,
        "status_counts": dict(
            sorted(Counter(str(run["status_code"]) for run in runs).items())
        ),
        "error_type_counts": dict(
            sorted(
                Counter(
                    str(run["error_type"])
                    for run in runs
                    if run["error_type"] is not None
                ).items()
            )
        ),
        "elapsed_seconds": _round(elapsed_seconds),
        "throughput_rps": _round(throughput),
        "speedup_vs_concurrency_1": _round(speedup),
        "scaling_efficiency": _round(efficiency),
        "max_in_flight": max_in_flight,
        "latency_ms": {
            "sample_count": len(latencies),
            "mean": _round(mean(latencies)) if latencies else None,
            "p50_nearest_rank": _round(nearest_rank(latencies, 0.50)),
            "p95_nearest_rank": _round(nearest_rank(latencies, 0.95)),
            "min": _round(min(latencies)) if latencies else None,
            "max": _round(max(latencies)) if latencies else None,
        },
    }


def build_load_summary(
    *,
    runs: list[dict[str, Any]],
    tier_timings: list[dict[str, Any]],
    concurrencies: list[int],
    requests_per_tier: int,
    warmup_requests_per_tier: int,
    database_records: list[dict[str, Any]],
    preflight_passed: bool,
    cloud_calls_enabled: bool,
    stub_calls_match_workload: bool,
    stopped_reason: str | None,
) -> dict[str, Any]:
    """Aggregate correctness and performance without imposing an arbitrary RPS gate."""
    measured_runs = [run for run in runs if run["phase"] == "measured"]
    warmup_runs = [run for run in runs if run["phase"] == "warmup"]
    timings_by_concurrency = {
        int(timing["concurrency"]): timing for timing in tier_timings
    }

    tier_inputs: list[tuple[int, list[dict[str, Any]], dict[str, Any]]] = []
    for concurrency in concurrencies:
        tier_runs = [
            run for run in measured_runs if run["concurrency"] == concurrency
        ]
        timing = timings_by_concurrency.get(
            concurrency,
            {
                "elapsed_seconds": 0.0,
                "max_in_flight": 0,
            },
        )
        tier_inputs.append((concurrency, tier_runs, timing))

    baseline_throughput: float | None = None
    if tier_inputs:
        _, baseline_runs, baseline_timing = tier_inputs[0]
        elapsed = float(baseline_timing["elapsed_seconds"])
        if baseline_runs and elapsed > 0:
            baseline_throughput = len(baseline_runs) / elapsed

    tiers = [
        _tier_summary(
            tier_runs,
            concurrency=concurrency,
            elapsed_seconds=float(timing["elapsed_seconds"]),
            max_in_flight=int(timing["max_in_flight"]),
            baseline_throughput=baseline_throughput,
        )
        for concurrency, tier_runs, timing in tier_inputs
    ]

    planned_measured_count = len(concurrencies) * requests_per_tier
    planned_warmup_count = len(concurrencies) * warmup_requests_per_tier
    expected_database_record_count = planned_measured_count + planned_warmup_count
    all_runs = warmup_runs + measured_runs
    status_counts = Counter(str(record["status"]) for record in database_records)
    server_error_count = sum(
        run["status_code"] is not None and int(run["status_code"]) >= 500
        for run in all_runs
    )

    gates = {
        "preflight_passed": preflight_passed,
        "all_warmups_complete": len(warmup_runs) == planned_warmup_count
        and all(run["api_completed"] for run in warmup_runs),
        "all_requests_executed": len(measured_runs) == planned_measured_count,
        "all_api_requests_complete": len(measured_runs) == planned_measured_count
        and all(run["api_completed"] for run in measured_runs),
        "no_server_errors": server_error_count == 0,
        "database_state_consistent": bool(all_runs)
        and all(run["database_verified"] for run in all_runs)
        and len(database_records) == expected_database_record_count
        and all(
            record["status"] == "completed" and record["output_present"]
            for record in database_records
        ),
        "all_load_records_found": len(database_records)
        == expected_database_record_count,
        "all_load_records_completed": bool(database_records)
        and all(
            record["status"] == "completed" and record["output_present"]
            for record in database_records
        ),
        "no_unexpected_pending_records": status_counts.get("pending", 0) == 0,
        "stub_calls_match_workload": stub_calls_match_workload,
        "no_cloud_calls": not cloud_calls_enabled,
        "run_was_not_stopped": stopped_reason is None,
    }
    gates["overall"] = all(gates.values())

    return {
        "planned_measured_count": planned_measured_count,
        "measured_count": len(measured_runs),
        "planned_warmup_count": planned_warmup_count,
        "warmup_count": len(warmup_runs),
        "stopped_reason": stopped_reason,
        "cloud_calls": cloud_calls_enabled,
        "cost_usd": 0.0 if not cloud_calls_enabled else None,
        "tiers": tiers,
        "database": {
            "expected_record_count": expected_database_record_count,
            "record_count": len(database_records),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "errors": {
            "server_error_count": server_error_count,
            "transport_error_count": sum(
                run["status_code"] is None for run in all_runs
            ),
        },
        "acceptance_gates": gates,
    }
