"""Dataset validation and deterministic scoring for the paid live smoke test."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

LIVE_PROTOCOL_VERSION = "1.0.0-draft"
LIVE_PROTOCOL_STATUS = "candidate"
ALLOWED_GENERATION_TYPES = {"text_to_image", "image_to_image"}


@dataclass(frozen=True)
class LiveSmokeCase:
    """One reviewed real-provider workflow with no embedded credentials or keys."""

    case_id: str
    generation_type: str
    prompt: str


def load_live_cases(path: Path) -> list[LiveSmokeCase]:
    """Load four reviewed cases and reject unsafe or ambiguous fields."""
    cases: list[LiveSmokeCase] = []
    errors: list[str] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if set(payload) != {"id", "generation_type", "prompt"}:
                raise ValueError("only id, generation_type, and prompt are allowed")
            case = LiveSmokeCase(
                case_id=str(payload["id"]),
                generation_type=str(payload["generation_type"]),
                prompt=str(payload["prompt"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"line {line_number}: {type(error).__name__}")
            continue

        prefix = f"line {line_number} ({case.case_id})"
        if not case.case_id.startswith("live-smoke-"):
            errors.append(f"{prefix}: id must start with live-smoke-")
        if case.generation_type not in ALLOWED_GENERATION_TYPES:
            errors.append(f"{prefix}: unsupported generation_type")
        if not 1 <= len(case.prompt) <= 400:
            errors.append(f"{prefix}: prompt length must be between 1 and 400")
        cases.append(case)

    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("case IDs must be unique")
    type_counts = {
        generation_type: sum(case.generation_type == generation_type for case in cases)
        for generation_type in ALLOWED_GENERATION_TYPES
    }
    if len(cases) != 4 or type_counts != {
        "text_to_image": 2,
        "image_to_image": 2,
    }:
        errors.append("live smoke v1 requires two cases of each generation type")
    if errors:
        raise ValueError("; ".join(errors))
    return cases


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _rate(runs: list[dict[str, Any]], field: str) -> float | None:
    if not runs:
        return None
    return sum(bool(run[field]) for run in runs) / len(runs)


def build_live_summary(
    runs: list[dict[str, Any]],
    *,
    planned_case_count: int,
    maximum_cost_usd: float,
    stopped_reason: str | None,
) -> dict[str, Any]:
    """Aggregate privacy-safe evidence and apply the live acceptance gates."""
    latencies = [float(run["latency_ms"]) for run in runs]
    measured_costs = [
        float(run["total_cost_usd"])
        for run in runs
        if run["total_cost_usd"] is not None
    ]
    total_cost = round(sum(measured_costs), 12)
    score = {
        "api_task_success_rate": _rate(runs, "api_completed"),
        "database_consistency_rate": _rate(runs, "database_verified"),
        "s3_output_retrieval_rate": _rate(runs, "s3_verified"),
        "langfuse_trace_completeness_rate": _rate(runs, "trace_complete"),
        "trace_privacy_compliance_rate": _rate(runs, "privacy_safe"),
        "cost_measurement_rate": _rate(runs, "cost_measured"),
    }
    gates = {
        "all_cases_executed": len(runs) == planned_case_count,
        "all_api_requests_complete": score["api_task_success_rate"] == 1.0,
        "database_state_is_consistent": score["database_consistency_rate"] == 1.0,
        "s3_outputs_are_retrievable": score["s3_output_retrieval_rate"] == 1.0,
        "langfuse_traces_are_complete": (
            score["langfuse_trace_completeness_rate"] == 1.0
        ),
        "trace_io_is_private": score["trace_privacy_compliance_rate"] == 1.0,
        "all_costs_are_measured": score["cost_measurement_rate"] == 1.0,
        "within_cost_cap": len(measured_costs) == len(runs)
        and total_cost <= maximum_cost_usd,
        "run_was_not_stopped": stopped_reason is None,
    }
    gates["overall"] = all(gates.values())
    return {
        "planned_case_count": planned_case_count,
        "run_count": len(runs),
        "cloud_calls": True,
        "stopped_reason": stopped_reason,
        "score": score,
        "cost_usd": {
            "sample_count": len(measured_costs),
            "total": total_cost,
            "maximum": maximum_cost_usd,
        },
        "latency_ms": {
            "sample_count": len(latencies),
            "mean": round(mean(latencies), 3) if latencies else None,
            "p50_nearest_rank": _nearest_rank(latencies, 0.50),
            "p95_nearest_rank": _nearest_rank(latencies, 0.95),
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "acceptance_gates": gates,
    }
