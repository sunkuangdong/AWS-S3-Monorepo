"""Derived scaling and saturation analysis for the capacity experiment."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _round(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def build_capacity_summary(
    *,
    load_summary: dict[str, Any],
    resource_tiers: list[dict[str, Any]],
    saturation_signals: dict[str, float],
) -> dict[str, Any]:
    """Merge correctness, resources, and transparent saturation heuristics."""
    summary = deepcopy(load_summary)
    resources_by_concurrency = {
        int(resource["concurrency"]): resource for resource in resource_tiers
    }
    saturation_candidates: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None

    for tier in summary["tiers"]:
        concurrency = int(tier["concurrency"])
        resource = resources_by_concurrency.get(concurrency)
        tier["resources"] = resource
        tier["marginal_throughput_gain"] = None
        tier["p95_latency_growth"] = None
        tier["saturation_signals"] = []

        if previous is not None:
            previous_rps = float(previous["throughput_rps"] or 0)
            current_rps = float(tier["throughput_rps"] or 0)
            previous_p95 = float(previous["latency_ms"]["p95_nearest_rank"] or 0)
            current_p95 = float(tier["latency_ms"]["p95_nearest_rank"] or 0)
            throughput_gain = (
                current_rps / previous_rps - 1 if previous_rps > 0 else None
            )
            p95_growth = (
                current_p95 / previous_p95 - 1 if previous_p95 > 0 else None
            )
            tier["marginal_throughput_gain"] = _round(throughput_gain)
            tier["p95_latency_growth"] = _round(p95_growth)

            if (
                throughput_gain is not None
                and throughput_gain
                < saturation_signals["maximum_marginal_throughput_gain"]
            ):
                tier["saturation_signals"].append("throughput_gain_below_20_percent")
            if (
                p95_growth is not None
                and p95_growth
                > saturation_signals["minimum_p95_latency_growth"]
            ):
                tier["saturation_signals"].append("p95_growth_above_50_percent")
            if (
                float(tier["scaling_efficiency"] or 0)
                < saturation_signals["maximum_scaling_efficiency"]
            ):
                tier["saturation_signals"].append("scaling_efficiency_below_50_percent")
            if tier["success_rate"] != 1.0:
                tier["saturation_signals"].append("request_failures")
            if tier["saturation_signals"]:
                saturation_candidates.append(
                    {
                        "concurrency": concurrency,
                        "signals": tier["saturation_signals"],
                    }
                )
        previous = tier

    gates = summary["acceptance_gates"]
    gates.pop("overall", None)
    gates["resource_metrics_collected"] = len(resource_tiers) == len(
        summary["tiers"]
    ) and all(
        resource["sample_count"] >= 2
        and resource["api_container"]["average_cpu_percent"] is not None
        and resource["api_container"]["maximum_memory_current_bytes"] is not None
        for resource in resource_tiers
    )
    gates["monitoring_errors_absent"] = all(
        resource["sample_error_count"] == 0 for resource in resource_tiers
    )
    gates["overall"] = all(gates.values())

    summary["experiment_type"] = "exploratory_capacity"
    summary["saturation_analysis"] = {
        "status": (
            "candidate_detected"
            if saturation_candidates
            else "not_observed_through_maximum_tested_concurrency"
        ),
        "first_candidate": (
            saturation_candidates[0] if saturation_candidates else None
        ),
        "all_candidates": saturation_candidates,
        "heuristics": saturation_signals,
        "interpretation_required": True,
    }
    return summary
