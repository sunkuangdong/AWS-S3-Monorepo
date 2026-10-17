"""Deterministic scoring for image-workflow evaluation runs."""

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


def _rate(items: list[dict[str, Any]], predicate: str) -> float | None:
    if not items:
        return None
    return sum(bool(item[predicate]) for item in items) / len(items)


def build_summary(
    runs: list[dict[str, Any]],
    *,
    requested_concurrency: int,
    max_in_flight: int,
) -> dict[str, Any]:
    """Aggregate run records while keeping unlike failure classes separate."""
    normal = [run for run in runs if run["category"] == "normal_path"]
    external_failures = [run for run in runs if run["category"] == "external_failure"]
    validation = [run for run in runs if run["category"] == "validation"]
    database_failures = [run for run in runs if run["category"] == "database_failure"]
    post_commit_failures = [
        run for run in runs if run["category"] == "post_commit_failure"
    ]

    latencies = [float(run["latency_ms"]) for run in runs]
    orphan_output_count = sum(int(run["orphan_output_count"]) for run in runs)
    unexpected_pending_count = sum(run["db_status"] == "pending" for run in runs)

    scenario_expectation_rate = _rate(runs, "matches_expected")
    state_consistency_rate = _rate(runs, "state_consistent")
    normal_path_success_rate = (
        sum(
            run["outcome"] == "completed"
            and run["db_status"] == "completed"
            and run["output_present"]
            and run["state_consistent"]
            for run in normal
        )
        / len(normal)
        if normal
        else None
    )
    external_failure_containment_rate = (
        sum(
            run["outcome"] == "handled_failure"
            and run["db_status"] == "failed"
            and not run["output_present"]
            and run["orphan_output_count"] == 0
            and run["state_consistent"]
            for run in external_failures
        )
        / len(external_failures)
        if external_failures
        else None
    )
    validation_rejection_rate = (
        sum(
            run["outcome"] == "rejected"
            and run["db_status"] is None
            and run["state_consistent"]
            for run in validation
        )
        / len(validation)
        if validation
        else None
    )
    database_failure_recovery_rate = (
        sum(
            run["outcome"] == "infrastructure_failure"
            and run["db_status"] == "failed"
            and not run["output_present"]
            and run["orphan_output_count"] == 0
            and run["state_consistent"]
            for run in database_failures
        )
        / len(database_failures)
        if database_failures
        else None
    )

    gates = {
        "all_cases_match_labels": scenario_expectation_rate == 1.0,
        "normal_paths_complete": normal_path_success_rate == 1.0,
        "external_failures_are_contained": (external_failure_containment_rate == 1.0),
        "invalid_inputs_are_rejected": validation_rejection_rate == 1.0,
        "database_completion_failures_are_compensated": (
            database_failure_recovery_rate == 1.0
        ),
        "all_terminal_states_are_consistent": state_consistency_rate == 1.0,
        "no_orphan_outputs": orphan_output_count == 0,
        "no_unexpected_pending_records": unexpected_pending_count == 0,
    }
    gates["overall"] = all(gates.values())

    return {
        "run_count": len(runs),
        "evaluated_count": len(runs),
        "cloud_calls": False,
        "outcome_counts": dict(sorted(Counter(run["outcome"] for run in runs).items())),
        "database_status_counts": dict(
            sorted(Counter(run["db_status"] or "none" for run in runs).items())
        ),
        "error_type_counts": dict(
            sorted(Counter(run["error_type"] or "none" for run in runs).items())
        ),
        "score": {
            "scenario_expectation_rate": scenario_expectation_rate,
            "normal_path_task_success_rate": normal_path_success_rate,
            "external_failure_containment_rate": (external_failure_containment_rate),
            "validation_rejection_rate": validation_rejection_rate,
            "database_failure_recovery_rate": database_failure_recovery_rate,
            "state_consistency_rate": state_consistency_rate,
            "orphan_output_count": orphan_output_count,
            "unexpected_pending_count": unexpected_pending_count,
            "post_commit_response_failure_count": sum(
                run["outcome"] == "handled_failure" for run in post_commit_failures
            ),
            "database_failure_case_count": len(database_failures),
        },
        "latency_ms": {
            "sample_count": len(latencies),
            "mean": round(mean(latencies), 3) if latencies else None,
            "p50_nearest_rank": nearest_rank(latencies, 0.50),
            "p95_nearest_rank": nearest_rank(latencies, 0.95),
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "concurrency": {
            "requested": requested_concurrency,
            "max_in_flight": max_in_flight,
        },
        "acceptance_gates": gates,
        "interpretation": (
            "Normal-path success is calculated only from normal-path cases; "
            "deliberately injected failures are scored by containment and state "
            "consistency instead of being mixed into task success."
        ),
    }
