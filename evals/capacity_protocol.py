"""Identity and drift checks for the frozen capacity experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dataset import dataset_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_MANIFEST = PROJECT_ROOT / "evals/capacity_protocol_v1.json"
CAPACITY_PROTOCOL_VERSION = "1.0.0"
CAPACITY_PROTOCOL_STATUS = "frozen"
CAPACITY_GIT_TAG = "capacity-eval-v1.0.0"
CAPACITY_IMPLEMENTATION_BASELINE_COMMIT = (
    "28edd96acf4848e349f3d4d5d1eccc15218ff7c7"
)
CAPACITY_EVIDENCE = PROJECT_ROOT / "evals/evidence/capacity_v1_summary.json"

REQUIRED_ACCEPTANCE_GATES = (
    "preflight_passed",
    "all_warmups_complete",
    "all_requests_executed",
    "all_api_requests_complete",
    "no_server_errors",
    "database_state_consistent",
    "all_load_records_found",
    "all_load_records_completed",
    "no_unexpected_pending_records",
    "stub_calls_match_workload",
    "no_cloud_calls",
    "run_was_not_stopped",
    "resource_metrics_collected",
    "monitoring_errors_absent",
    "overall",
)


def load_capacity_manifest() -> dict[str, Any]:
    """Load the tracked frozen capacity protocol manifest."""
    return json.loads(CAPACITY_MANIFEST.read_text(encoding="utf-8"))


def validate_capacity_protocol(
    *,
    concurrencies: list[int],
    requests_per_tier: int,
    warmup_requests_per_tier: int,
    timeout_seconds: float,
    sample_interval_seconds: float,
    preflight_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject frozen identity, evidence, parameter, safety, or stub drift."""
    manifest = load_capacity_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != CAPACITY_PROTOCOL_VERSION:
        errors.append("capacity manifest version does not match the runner")
    if manifest.get("status") != CAPACITY_PROTOCOL_STATUS:
        errors.append("capacity manifest status does not match the runner")

    runner = manifest.get("runner", {})
    expected_runner = {
        "module": "evals.run_capacity",
        "application_module": "evals.capacity_app:app",
        "compose_profile": "capacity",
        "compose_service": "capacity-api",
        "uvicorn_workers": 1,
        "concurrencies": concurrencies,
        "requests_per_tier": requests_per_tier,
        "warmup_requests_per_tier": warmup_requests_per_tier,
        "timeout_seconds": timeout_seconds,
        "sample_interval_seconds": sample_interval_seconds,
    }
    for name, actual in expected_runner.items():
        if runner.get(name) != actual:
            errors.append(
                f"{name} does not match capacity protocol v1: "
                f"expected {runner.get(name)}, got {actual}"
            )

    if manifest.get("workload", {}).get("generation_type") != "text_to_image":
        errors.append("capacity workload must remain text_to_image")
    if manifest.get("safety") != {
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "expected_cost_usd": 0.0,
    }:
        errors.append("capacity safety configuration does not match the runner")

    if manifest.get("required_acceptance_gates") != list(
        REQUIRED_ACCEPTANCE_GATES
    ):
        errors.append("capacity acceptance gates do not match the runner")

    freeze = manifest.get("freeze", {})
    if freeze.get("git_tag") != CAPACITY_GIT_TAG:
        errors.append("Git tag does not match frozen capacity protocol v1")
    if (
        freeze.get("implementation_baseline_commit")
        != CAPACITY_IMPLEMENTATION_BASELINE_COMMIT
    ):
        errors.append("implementation baseline does not match capacity protocol v1")
    expected_evidence_path = str(CAPACITY_EVIDENCE.relative_to(PROJECT_ROOT))
    if freeze.get("evidence_path") != expected_evidence_path:
        errors.append("evidence path does not match frozen capacity protocol v1")
    if not CAPACITY_EVIDENCE.is_file():
        errors.append("frozen aggregate capacity evidence is missing")
    elif dataset_sha256(CAPACITY_EVIDENCE) != freeze.get("evidence_sha256"):
        errors.append("aggregate capacity evidence SHA-256 does not match manifest")
    else:
        evidence = json.loads(CAPACITY_EVIDENCE.read_text(encoding="utf-8"))
        if evidence.get("protocol_version") != CAPACITY_PROTOCOL_VERSION:
            errors.append("aggregate capacity evidence protocol version does not match")
        if (
            evidence.get("implementation_baseline_commit")
            != CAPACITY_IMPLEMENTATION_BASELINE_COMMIT
        ):
            errors.append("aggregate capacity evidence baseline commit does not match")
        if evidence.get("source_worktree_dirty") is not False:
            errors.append("aggregate capacity evidence must come from a clean worktree")
        result = evidence.get("result", {})
        if result.get("overall_passed") is not True:
            errors.append("aggregate capacity evidence did not pass all gates")
        if result.get("maximum_tested_concurrency") != 64:
            errors.append("aggregate capacity evidence tested range does not match")
        if result.get("saturation_status") != (
            "not_observed_through_maximum_tested_concurrency"
        ):
            errors.append("aggregate capacity saturation status does not match")

    if preflight_result is not None:
        if preflight_result.get("cloud_calls_enabled") is not False:
            errors.append("capacity preflight did not prove cloud isolation")
        actual_delays = {
            name: details.get("delay_ms")
            for name, details in preflight_result.get("stubs", {}).items()
            if isinstance(details, dict)
        }
        if actual_delays != manifest.get("stub_delays_ms"):
            errors.append("capacity stub delays do not match the manifest")
        if preflight_result.get("resource_metrics_available") is not True:
            errors.append("capacity resource metrics are unavailable")

    if errors:
        raise ValueError("; ".join(errors))
    return manifest
