"""Identity and drift checks for the candidate Capacity v2 experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dataset import dataset_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_V2_MANIFEST = PROJECT_ROOT / "evals/capacity_protocol_v2.json"
CAPACITY_V2_PROTOCOL_VERSION = "2.0.0"
CAPACITY_V2_PROTOCOL_STATUS = "frozen"
CAPACITY_V2_GIT_TAG = "capacity-eval-v2.0.0"
CAPACITY_V2_IMPLEMENTATION_BASELINE_COMMIT = (
    "24b087bf3bb3443ee98daf46328d560cb004efb7"
)
CAPACITY_V2_EVIDENCE = (
    PROJECT_ROOT / "evals/evidence/capacity_v2_summary.json"
)

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


def load_capacity_v2_manifest() -> dict[str, Any]:
    """Load the tracked candidate Capacity v2 manifest."""
    return json.loads(CAPACITY_V2_MANIFEST.read_text(encoding="utf-8"))


def validate_capacity_v2_protocol(
    *,
    concurrencies: list[int],
    requests_per_tier: int,
    warmup_requests_per_tier: int,
    timeout_seconds: float,
    sample_interval_seconds: float,
    preflight_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject candidate identity, workload, safety, gate, or stub drift."""
    manifest = load_capacity_v2_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != CAPACITY_V2_PROTOCOL_VERSION:
        errors.append("Capacity v2 manifest version does not match the runner")
    if manifest.get("status") != CAPACITY_V2_PROTOCOL_STATUS:
        errors.append("Capacity v2 manifest status does not match the runner")

    runner = manifest.get("runner", {})
    expected_runner = {
        "module": "evals.run_capacity_v2",
        "application_module": "evals.capacity_v2_app:app",
        "compose_profile": "capacity-v2",
        "compose_service": "capacity-v2-api",
        "uvicorn_workers": 1,
        "concurrencies": concurrencies,
        "requests_per_tier": requests_per_tier,
        "warmup_requests_per_tier": warmup_requests_per_tier,
        "timeout_seconds": timeout_seconds,
        "sample_interval_seconds": sample_interval_seconds,
        "verification_transport_retries": 1,
    }
    for name, actual in expected_runner.items():
        if runner.get(name) != actual:
            errors.append(
                f"{name} does not match Capacity v2: "
                f"expected {runner.get(name)}, got {actual}"
            )

    workload = manifest.get("workload", {})
    if workload.get("generation_type") != "text_to_image":
        errors.append("Capacity v2 workload must remain text_to_image")
    if (workload.get("width"), workload.get("height")) != (1024, 1024):
        errors.append("Capacity v2 image dimensions must remain 1024 by 1024")

    expected_safety = {
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "expected_cost_usd": 0.0,
        "maximum_concurrency": 256,
        "stop_tier_after_failure": True,
    }
    if manifest.get("safety") != expected_safety:
        errors.append("Capacity v2 safety configuration does not match the runner")
    if concurrencies and max(concurrencies) > expected_safety["maximum_concurrency"]:
        errors.append("Capacity v2 concurrency exceeds the safety ceiling")

    if manifest.get("required_acceptance_gates") != list(
        REQUIRED_ACCEPTANCE_GATES
    ):
        errors.append("Capacity v2 acceptance gates do not match the runner")

    freeze = manifest.get("freeze", {})
    if freeze.get("git_tag") != CAPACITY_V2_GIT_TAG:
        errors.append("Git tag does not match frozen Capacity v2")
    if (
        freeze.get("implementation_baseline_commit")
        != CAPACITY_V2_IMPLEMENTATION_BASELINE_COMMIT
    ):
        errors.append("implementation baseline does not match Capacity v2")
    expected_evidence_path = str(CAPACITY_V2_EVIDENCE.relative_to(PROJECT_ROOT))
    if freeze.get("evidence_path") != expected_evidence_path:
        errors.append("evidence path does not match frozen Capacity v2")
    if not CAPACITY_V2_EVIDENCE.is_file():
        errors.append("frozen aggregate Capacity v2 evidence is missing")
    elif dataset_sha256(CAPACITY_V2_EVIDENCE) != freeze.get("evidence_sha256"):
        errors.append("aggregate Capacity v2 evidence SHA-256 does not match")
    else:
        evidence = json.loads(CAPACITY_V2_EVIDENCE.read_text(encoding="utf-8"))
        result = evidence.get("result", {})
        repeatability = evidence.get("repeatability", {})
        if evidence.get("protocol_version") != CAPACITY_V2_PROTOCOL_VERSION:
            errors.append("aggregate Capacity v2 evidence version does not match")
        if (
            evidence.get("implementation_baseline_commit")
            != CAPACITY_V2_IMPLEMENTATION_BASELINE_COMMIT
        ):
            errors.append("aggregate Capacity v2 evidence baseline does not match")
        if evidence.get("source_worktree_dirty") is not False:
            errors.append("aggregate Capacity v2 evidence must use a clean worktree")
        if result.get("freeze_criteria_met") is not True:
            errors.append("aggregate Capacity v2 freeze criteria were not met")
        if result.get("baseline_concurrency") != 64:
            errors.append("aggregate Capacity v2 baseline does not match")
        if result.get("baseline_success_rate") != 1.0:
            errors.append("aggregate Capacity v2 baseline did not fully pass")
        if result.get("first_saturation_candidate") != 96:
            errors.append("aggregate Capacity v2 breakpoint does not match")
        if result.get("stopped_reason") != "measured_failure_at_concurrency_96":
            errors.append("aggregate Capacity v2 stop reason does not match")
        if result.get("saturation_status") != (
            "candidate_detected_at_concurrency_96"
        ):
            errors.append("aggregate Capacity v2 saturation status does not match")
        if repeatability.get("run_count") != 3 or repeatability.get(
            "all_runs_identified_concurrency_96_as_a_saturation_candidate"
        ) is not True:
            errors.append("aggregate Capacity v2 repeatability evidence is incomplete")

    if preflight_result is not None:
        if preflight_result.get("cloud_calls_enabled") is not False:
            errors.append("Capacity v2 preflight did not prove cloud isolation")
        actual_delays = {
            name: details.get("delay_ms")
            for name, details in preflight_result.get("stubs", {}).items()
            if isinstance(details, dict)
        }
        if actual_delays != manifest.get("stub_delays_ms"):
            errors.append("Capacity v2 stub delays do not match the manifest")
        if preflight_result.get("resource_metrics_available") is not True:
            errors.append("Capacity v2 resource metrics are unavailable")

    if errors:
        raise ValueError("; ".join(errors))
    return manifest
