"""Scaling and saturation analysis for the high-concurrency v2 experiment."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _round(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def build_capacity_v2_summary(
    *,
    load_summary: dict[str, Any],
    resource_tiers: list[dict[str, Any]],
    baseline_concurrency: int,
    saturation_signals: dict[str, float],
) -> dict[str, Any]:
    """Rebase scaling at 64 and apply concurrency-normalized knee signals."""
    summary = deepcopy(load_summary)
    resources_by_concurrency = {
        int(resource["concurrency"]): resource for resource in resource_tiers
    }
    baseline = next(
        (
            tier
            for tier in summary["tiers"]
            if int(tier["concurrency"]) == baseline_concurrency
        ),
        None,
    )
    baseline_rps = float(baseline["throughput_rps"] or 0) if baseline else 0.0
    if baseline is None or baseline_rps <= 0:
        raise ValueError("Capacity v2 baseline tier is missing or invalid")

    candidates: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for tier in summary["tiers"]:
        concurrency = int(tier["concurrency"])
        executed = int(tier.get("request_count") or 0) > 0
        tier["executed"] = executed
        tier["resources"] = resources_by_concurrency.get(concurrency)
        tier["marginal_throughput_gain"] = None
        tier["marginal_concurrency_gain"] = None
        tier["marginal_scaling_efficiency"] = None
        tier["p95_latency_growth"] = None
        tier["saturation_signals"] = []
        if not executed:
            tier.pop("speedup_vs_concurrency_1", None)
            tier["speedup_vs_baseline"] = None
            tier["scaling_efficiency"] = None
            continue

        current_rps = float(tier["throughput_rps"] or 0)
        concurrency_multiplier = concurrency / baseline_concurrency
        speedup = current_rps / baseline_rps
        efficiency = speedup / concurrency_multiplier

        tier.pop("speedup_vs_concurrency_1", None)
        tier["speedup_vs_baseline"] = _round(speedup)
        tier["scaling_efficiency"] = _round(efficiency)

        if previous is not None:
            previous_concurrency = int(previous["concurrency"])
            previous_rps = float(previous["throughput_rps"] or 0)
            previous_p95 = float(
                previous["latency_ms"]["p95_nearest_rank"] or 0
            )
            current_p95 = float(tier["latency_ms"]["p95_nearest_rank"] or 0)
            concurrency_gain = concurrency / previous_concurrency - 1
            throughput_gain = (
                current_rps / previous_rps - 1 if previous_rps > 0 else None
            )
            marginal_efficiency = (
                throughput_gain / concurrency_gain
                if throughput_gain is not None and concurrency_gain > 0
                else None
            )
            p95_growth = (
                current_p95 / previous_p95 - 1 if previous_p95 > 0 else None
            )

            tier["marginal_throughput_gain"] = _round(throughput_gain)
            tier["marginal_concurrency_gain"] = _round(concurrency_gain)
            tier["marginal_scaling_efficiency"] = _round(marginal_efficiency)
            tier["p95_latency_growth"] = _round(p95_growth)

            if (
                marginal_efficiency is not None
                and marginal_efficiency
                < saturation_signals["maximum_marginal_scaling_efficiency"]
            ):
                tier["saturation_signals"].append(
                    "marginal_scaling_efficiency_below_50_percent"
                )
            if (
                p95_growth is not None
                and p95_growth
                > saturation_signals["minimum_p95_latency_growth"]
            ):
                tier["saturation_signals"].append(
                    "p95_growth_above_50_percent"
                )
            if (
                efficiency
                < saturation_signals["maximum_scaling_efficiency"]
            ):
                tier["saturation_signals"].append(
                    "scaling_efficiency_below_50_percent"
                )
            if tier["success_rate"] != 1.0:
                tier["saturation_signals"].append("request_failures")
            if tier["saturation_signals"]:
                candidates.append(
                    {
                        "concurrency": concurrency,
                        "signals": list(tier["saturation_signals"]),
                    }
                )
        previous = tier

    gates = summary["acceptance_gates"]
    gates.pop("overall", None)
    executed_tiers = [tier for tier in summary["tiers"] if tier["executed"]]
    gates["resource_metrics_collected"] = len(resource_tiers) == len(
        executed_tiers
    ) and all(
        resource["sample_count"] >= 3
        and resource["api_container"]["average_cpu_percent"] is not None
        and resource["api_container"]["maximum_memory_current_bytes"] is not None
        for resource in resource_tiers
    )
    gates["monitoring_errors_absent"] = all(
        resource["sample_error_count"] == 0 for resource in resource_tiers
    )
    gates["overall"] = all(gates.values())

    summary["experiment_type"] = "capacity_breakpoint_v2"
    summary["baseline_concurrency"] = baseline_concurrency
    summary["saturation_analysis"] = {
        "status": "candidate_detected" if candidates else "not_observed",
        "first_candidate": candidates[0] if candidates else None,
        "all_candidates": candidates,
        "heuristics": saturation_signals,
        "interpretation_required": True,
    }
    return summary
