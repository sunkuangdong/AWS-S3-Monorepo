"""Dataset validation and deterministic scoring for the paid live smoke test."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from evals.dataset import dataset_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN_LIVE_MANIFEST = PROJECT_ROOT / "evals/frozen_live_protocol_v1.json"
LIVE_PROTOCOL_VERSION = "1.0.0"
LIVE_PROTOCOL_STATUS = "frozen"
ALLOWED_GENERATION_TYPES = {"text_to_image", "image_to_image"}
EXPECTED_MODELS = {
    "text_to_image": {"gpt-image-2.5-sunburst"},
    "image_to_image": {"gpt-4.1-mini", "gpt-image-2.5-sunburst"},
}
REQUIRED_ACCEPTANCE_GATES = (
    "all_cases_executed",
    "all_api_requests_complete",
    "database_state_is_consistent",
    "s3_outputs_are_retrievable",
    "langfuse_traces_are_complete",
    "trace_io_is_private",
    "models_match_protocol",
    "all_costs_are_measured",
    "within_cost_cap",
    "run_was_not_stopped",
    "overall",
)


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


def load_frozen_live_manifest() -> dict[str, Any]:
    """Load the tracked identity of live smoke v1."""
    return json.loads(FROZEN_LIVE_MANIFEST.read_text(encoding="utf-8"))


def validate_frozen_live_protocol(
    dataset_path: Path,
    *,
    maximum_cost_usd: float,
    timeout_seconds: float,
    trace_wait_seconds: int,
) -> dict[str, Any]:
    """Reject dataset, model, budget, timing, evidence, or gate drift."""
    manifest = load_frozen_live_manifest()
    errors: list[str] = []
    if manifest.get("protocol_version") != LIVE_PROTOCOL_VERSION:
        errors.append("manifest protocol version does not match the runner")
    if manifest.get("status") != LIVE_PROTOCOL_STATUS:
        errors.append("manifest status must be frozen")

    dataset = manifest.get("dataset", {})
    expected_path = PROJECT_ROOT / str(dataset.get("path", ""))
    resolved_path = dataset_path.resolve()
    cases = load_live_cases(resolved_path)
    if resolved_path != expected_path.resolve():
        errors.append("dataset path is outside frozen live smoke v1")
    if dataset_sha256(resolved_path) != dataset.get("sha256"):
        errors.append("dataset SHA-256 does not match the frozen manifest")
    if len(cases) != dataset.get("case_count"):
        errors.append("dataset case count does not match the frozen manifest")
    if [case.case_id for case in cases] != dataset.get("case_ids"):
        errors.append("dataset case IDs or order do not match the frozen manifest")

    runner = manifest.get("runner", {})
    if runner.get("module") != "evals.run_live_smoke":
        errors.append("runner module does not match the frozen protocol")
    if runner.get("sequential") is not True or runner.get("concurrency") != 1:
        errors.append("live smoke v1 must remain sequential")
    if (runner.get("width"), runner.get("height")) != (1024, 1024):
        errors.append("image dimensions do not match the frozen protocol")
    if maximum_cost_usd != runner.get("maximum_cost_usd"):
        errors.append("maximum cost does not match the frozen protocol")
    if timeout_seconds != runner.get("timeout_seconds"):
        errors.append("request timeout does not match the frozen protocol")
    if trace_wait_seconds != runner.get("trace_wait_seconds"):
        errors.append("trace wait does not match the frozen protocol")
    expected_models = {
        name: set(models)
        for name, models in manifest.get("expected_models", {}).items()
    }
    if expected_models != EXPECTED_MODELS:
        errors.append("expected models do not match the frozen runner")
    if manifest.get("required_acceptance_gates") != list(REQUIRED_ACCEPTANCE_GATES):
        errors.append("acceptance gates do not match the frozen runner")

    evidence = manifest.get("evidence", {})
    evidence_path = PROJECT_ROOT / str(evidence.get("path", ""))
    if not evidence_path.is_file():
        errors.append("frozen aggregate evidence is missing")
    elif dataset_sha256(evidence_path) != evidence.get("sha256"):
        errors.append("aggregate evidence SHA-256 does not match the manifest")
    if errors:
        raise ValueError("; ".join(errors))
    return manifest


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
        "model_compliance_rate": (
            sum(
                set(run.get("model_names", []))
                == EXPECTED_MODELS.get(run["generation_type"], set())
                for run in runs
            )
            / len(runs)
            if runs
            else None
        ),
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
        "models_match_protocol": score["model_compliance_rate"] == 1.0,
        "all_costs_are_measured": score["cost_measurement_rate"] == 1.0,
        "within_cost_cap": len(measured_costs) == len(runs)
        and total_cost <= maximum_cost_usd,
        "run_was_not_stopped": stopped_reason is None,
    }
    gates["overall"] = all(gates.values())
    if tuple(gates) != REQUIRED_ACCEPTANCE_GATES:
        raise ValueError("acceptance gates drifted from frozen live protocol")
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
