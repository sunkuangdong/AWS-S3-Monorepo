"""Validation, scheduling, and scoring for real-dependency capacity tests."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

ALLOWED_STAGE_NAMES = {"ramp", "steady", "spike", "soak"}
ALLOWED_GENERATION_TYPES = {"text_to_image", "image_to_image"}


@dataclass(frozen=True)
class ProductionCapacityCase:
    """One reviewed real-provider request template."""

    case_id: str
    generation_type: str
    prompt: str


@dataclass(frozen=True)
class StageSpec:
    """One bounded open-arrival-rate stage."""

    name: str
    start_rate_jpm: float
    end_rate_jpm: float
    request_count: int

    def rates(self) -> list[float]:
        """Return one dispatch rate for each request in the stage."""
        if self.request_count == 1:
            return [self.end_rate_jpm]
        if self.start_rate_jpm == self.end_rate_jpm:
            return [self.end_rate_jpm] * self.request_count
        step = (self.end_rate_jpm - self.start_rate_jpm) / (self.request_count - 1)
        return [self.start_rate_jpm + step * index for index in range(self.request_count)]


def load_cases(path: Path) -> list[ProductionCapacityCase]:
    """Load the reviewed workload without accepting arbitrary fields."""
    cases: list[ProductionCapacityCase] = []
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
            case = ProductionCapacityCase(
                case_id=str(payload["id"]),
                generation_type=str(payload["generation_type"]),
                prompt=str(payload["prompt"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"line {line_number}: {type(error).__name__}")
            continue

        prefix = f"line {line_number} ({case.case_id})"
        if not case.case_id.startswith("production-capacity-"):
            errors.append(f"{prefix}: invalid case ID")
        if case.generation_type not in ALLOWED_GENERATION_TYPES:
            errors.append(f"{prefix}: unsupported generation type")
        if not 1 <= len(case.prompt) <= 320:
            errors.append(f"{prefix}: prompt length must be between 1 and 320")
        cases.append(case)

    if len(cases) < 2:
        errors.append("at least two reviewed cases are required")
    if {case.generation_type for case in cases} != ALLOWED_GENERATION_TYPES:
        errors.append("both generation types must be represented")
    if len({case.case_id for case in cases}) != len(cases):
        errors.append("case IDs must be unique")
    if errors:
        raise ValueError("; ".join(errors))
    return cases


def parse_stage(value: str) -> StageSpec:
    """Parse NAME:RATE:COUNT or ramp:START-END:COUNT."""
    try:
        name, rate_text, count_text = value.split(":", 2)
        request_count = int(count_text)
        if name == "ramp":
            start_text, end_text = rate_text.split("-", 1)
            start_rate = float(start_text)
            end_rate = float(end_text)
        else:
            start_rate = end_rate = float(rate_text)
    except ValueError as error:
        raise ValueError(
            "stage must be NAME:RATE:COUNT or ramp:START-END:COUNT"
        ) from error

    if name not in ALLOWED_STAGE_NAMES:
        raise ValueError(f"unsupported stage name: {name}")
    if request_count < 1:
        raise ValueError("stage request count must be positive")
    if start_rate <= 0 or end_rate <= 0:
        raise ValueError("stage rates must be positive")
    if name == "ramp" and end_rate < start_rate:
        raise ValueError("ramp end rate must be at least its start rate")
    return StageSpec(name, start_rate, end_rate, request_count)


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 3)


def latency_summary(values: list[float]) -> dict[str, Any]:
    """Build bounded latency statistics without retaining raw payloads."""
    return {
        "sample_count": len(values),
        "mean": round(mean(values), 3) if values else None,
        "p50_nearest_rank": _nearest_rank(values, 0.50),
        "p95_nearest_rank": _nearest_rank(values, 0.95),
        "p99_nearest_rank": _nearest_rank(values, 0.99),
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }


def resource_summary(samples: list[dict[str, float]]) -> dict[str, Any]:
    """Aggregate a deliberately small, numeric metrics contract."""
    if not samples:
        return {"available": False, "sample_count": 0}
    cpu = [sample["cpu_percent"] for sample in samples]
    memory = [sample["memory_percent"] for sample in samples]
    database = [
        sample["database_active_connections"]
        / sample["database_max_connections"]
        * 100
        for sample in samples
    ]
    return {
        "available": True,
        "sample_count": len(samples),
        "cpu_percent": {"mean": round(mean(cpu), 3), "maximum": max(cpu)},
        "memory_percent": {
            "mean": round(mean(memory), 3),
            "maximum": max(memory),
        },
        "database_connection_utilization_percent": {
            "mean": round(mean(database), 3),
            "maximum": round(max(database), 3),
        },
    }


def build_summary(
    runs: list[dict[str, Any]],
    *,
    stages: list[dict[str, Any]],
    planned_count: int,
    maximum_cost_usd: float,
    minimum_success_rate: float,
    database_scan: dict[str, Any],
    orphan_scan: dict[str, Any],
    resources: dict[str, Any],
    maximum_cpu_percent: float,
    maximum_memory_percent: float,
    maximum_database_connection_percent: float,
    stopped_reason: str | None,
) -> dict[str, Any]:
    """Apply production-capacity safety and correctness gates."""
    run_count = len(runs)
    api_success_count = sum(bool(run["api_completed"]) for run in runs)
    database_verified_count = sum(bool(run["database_verified"]) for run in runs)
    s3_verified_count = sum(bool(run["s3_verified"]) for run in runs)
    traced = [run for run in runs if run.get("database_record_found")]
    measured_costs = [
        float(run["total_cost_usd"])
        for run in traced
        if run.get("total_cost_usd") is not None
    ]
    total_cost = round(sum(measured_costs), 12)
    api_latencies = [float(run["api_latency_ms"]) for run in runs]
    success_rate = api_success_count / run_count if run_count else None
    database_rate = database_verified_count / run_count if run_count else None
    s3_rate = s3_verified_count / api_success_count if api_success_count else None
    trace_rate = (
        sum(bool(run.get("trace_complete")) for run in traced) / len(traced)
        if traced
        else None
    )
    privacy_rate = (
        sum(bool(run.get("privacy_safe")) for run in traced) / len(traced)
        if traced
        else None
    )
    cost_rate = len(measured_costs) / len(traced) if traced else None
    model_rate = (
        sum(bool(run.get("model_compliant")) for run in traced) / len(traced)
        if traced
        else None
    )

    resource_gates = {
        "resource_metrics_available": resources.get("available") is True,
        "cpu_within_limit": resources.get("available") is True
        and resources["cpu_percent"]["maximum"] <= maximum_cpu_percent,
        "memory_within_limit": resources.get("available") is True
        and resources["memory_percent"]["maximum"] <= maximum_memory_percent,
        "database_connections_within_limit": resources.get("available") is True
        and resources["database_connection_utilization_percent"]["maximum"]
        <= maximum_database_connection_percent,
    }
    gates = {
        "all_requests_dispatched": run_count == planned_count,
        "minimum_api_success_rate_met": success_rate is not None
        and success_rate >= minimum_success_rate,
        "database_records_are_unique_and_terminal": (
            database_rate == 1.0
            and database_scan.get("missing_count") == 0
            and database_scan.get("duplicate_count") == 0
            and database_scan.get("unexpected_pending_count") == 0
        ),
        "successful_outputs_are_retrievable": s3_rate == 1.0,
        "orphan_scan_complete": orphan_scan.get("available") is True,
        "no_orphan_outputs": orphan_scan.get("available") is True
        and orphan_scan.get("orphan_output_count") == 0,
        "langfuse_traces_are_complete": trace_rate == 1.0,
        "trace_io_is_private": privacy_rate == 1.0,
        "models_match_protocol": model_rate == 1.0,
        "all_recorded_costs_are_measured": cost_rate == 1.0,
        "within_cost_cap": total_cost <= maximum_cost_usd,
        **resource_gates,
        "run_was_not_stopped": stopped_reason is None,
    }
    gates["overall"] = all(gates.values())
    return {
        "planned_request_count": planned_count,
        "run_count": run_count,
        "cloud_calls": True,
        "stopped_reason": stopped_reason,
        "score": {
            "api_task_success_rate": success_rate,
            "database_consistency_rate": database_rate,
            "s3_output_retrieval_rate": s3_rate,
            "langfuse_trace_completeness_rate": trace_rate,
            "trace_privacy_compliance_rate": privacy_rate,
            "model_compliance_rate": model_rate,
            "cost_measurement_rate": cost_rate,
        },
        "api_latency_ms": latency_summary(api_latencies),
        "cost_usd": {
            "sample_count": len(measured_costs),
            "total": total_cost,
            "maximum": maximum_cost_usd,
        },
        "database": database_scan,
        "s3_orphan_scan": orphan_scan,
        "resources": resources,
        "stages": stages,
        "acceptance_gates": gates,
        "claim_boundary": (
            "Results apply only to the recorded deployment, workload, provider "
            "quotas, and test window. They are not a universal production SLO."
        ),
    }
