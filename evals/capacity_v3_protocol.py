"""Identity and drift checks for the frozen Capacity v3 optimization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dataset import dataset_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_V3_MANIFEST = PROJECT_ROOT / "evals/capacity_protocol_v3.json"
CAPACITY_V3_PROTOCOL_VERSION = "3.0.0"
CAPACITY_V3_PROTOCOL_STATUS = "frozen"
CAPACITY_V3_GIT_TAG = "capacity-eval-v3.0.0"
CAPACITY_V3_IMPLEMENTATION_BASELINE_COMMIT = (
    "e02511c91102d7138cc436e8d97c01de90d65b97"
)
CAPACITY_V3_EVIDENCE = (
    PROJECT_ROOT / "evals/evidence/capacity_v3_validation_summary.json"
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


def load_capacity_v3_manifest() -> dict[str, Any]:
    """Load the tracked frozen Capacity v3 manifest."""
    return json.loads(CAPACITY_V3_MANIFEST.read_text(encoding="utf-8"))


def validate_capacity_v3_protocol(
    *,
    mode: str,
    concurrencies: list[int],
    requests_per_tier: int,
    warmup_requests_per_tier: int,
    timeout_seconds: float,
    sample_interval_seconds: float,
    preflight_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject frozen identity, workload, evidence, or safety drift."""
    manifest = load_capacity_v3_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != CAPACITY_V3_PROTOCOL_VERSION:
        errors.append("Capacity v3 manifest version does not match the runner")
    if manifest.get("status") != CAPACITY_V3_PROTOCOL_STATUS:
        errors.append("Capacity v3 manifest status does not match the runner")

    runner = manifest.get("runner", {})
    expected_identity = {
        "module": "evals.run_capacity_v3",
        "application_module": "evals.capacity_v3_app:app",
        "compose_profile": "capacity-v3",
        "compose_service": "capacity-v3-api",
        "uvicorn_workers": 1,
        "timeout_seconds": timeout_seconds,
        "sample_interval_seconds": sample_interval_seconds,
        "verification_transport_retries": 1,
    }
    for name, actual in expected_identity.items():
        if runner.get(name) != actual:
            errors.append(f"{name} does not match Capacity v3")

    mode_config = runner.get("modes", {}).get(mode)
    if not isinstance(mode_config, dict):
        errors.append("Capacity v3 mode is not defined")
    else:
        expected_mode = {
            "concurrencies": concurrencies,
            "requests_per_tier": requests_per_tier,
            "warmup_requests_per_tier": warmup_requests_per_tier,
        }
        if mode_config != expected_mode:
            errors.append(f"{mode} parameters do not match Capacity v3")

    expected_optimization = {
        "single_variable": "sqlalchemy_connection_pool_capacity",
        "v2_database_pool_size": 5,
        "v2_database_max_overflow": 10,
        "v3_database_pool_size": 20,
        "v3_database_max_overflow": 20,
        "database_pool_timeout_seconds": 30,
        "business_logic_changed": False,
        "provider_stub_latency_changed": False,
        "uvicorn_worker_count_changed": False,
    }
    if manifest.get("optimization") != expected_optimization:
        errors.append("Capacity v3 optimization is not a single-variable change")

    safety = manifest.get("safety", {})
    if safety != {
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "expected_cost_usd": 0.0,
        "maximum_concurrency": 256,
        "stop_tier_after_failure": True,
    }:
        errors.append("Capacity v3 safety configuration does not match")
    if concurrencies and max(concurrencies) > 256:
        errors.append("Capacity v3 concurrency exceeds the safety ceiling")
    if manifest.get("required_acceptance_gates") != list(
        REQUIRED_ACCEPTANCE_GATES
    ):
        errors.append("Capacity v3 acceptance gates do not match")

    freeze = manifest.get("freeze", {})
    if freeze.get("git_tag") != CAPACITY_V3_GIT_TAG:
        errors.append("Git tag does not match frozen Capacity v3")
    if (
        freeze.get("implementation_baseline_commit")
        != CAPACITY_V3_IMPLEMENTATION_BASELINE_COMMIT
    ):
        errors.append("implementation baseline does not match Capacity v3")
    expected_evidence_path = str(CAPACITY_V3_EVIDENCE.relative_to(PROJECT_ROOT))
    if freeze.get("evidence_path") != expected_evidence_path:
        errors.append("evidence path does not match frozen Capacity v3")
    if not CAPACITY_V3_EVIDENCE.is_file():
        errors.append("frozen aggregate Capacity v3 evidence is missing")
    elif dataset_sha256(CAPACITY_V3_EVIDENCE) != freeze.get("evidence_sha256"):
        errors.append("aggregate Capacity v3 evidence SHA-256 does not match")
    else:
        evidence = json.loads(CAPACITY_V3_EVIDENCE.read_text(encoding="utf-8"))
        aggregate = evidence.get("aggregate", {})
        conclusion = evidence.get("conclusion", {})
        privacy = evidence.get("privacy", {})
        if evidence.get("protocol_version") != CAPACITY_V3_PROTOCOL_VERSION:
            errors.append("aggregate Capacity v3 evidence version does not match")
        if (
            evidence.get("implementation_commit")
            != CAPACITY_V3_IMPLEMENTATION_BASELINE_COMMIT
        ):
            errors.append("aggregate Capacity v3 evidence baseline does not match")
        if evidence.get("source_worktree_dirty") is not False:
            errors.append("aggregate Capacity v3 evidence must use a clean worktree")
        if evidence.get("freeze_criteria_met") is not True:
            errors.append("aggregate Capacity v3 freeze criteria were not met")
        if aggregate.get("run_count") != 3:
            errors.append("aggregate Capacity v3 run count does not match")
        if aggregate.get(
            "all_runs_identified_concurrency_96_as_first_performance_candidate"
        ) is not True:
            errors.append("aggregate Capacity v3 performance knee is incomplete")
        if aggregate.get("all_concurrency_64_and_96_requests_succeeded") is not True:
            errors.append("aggregate Capacity v3 reliable tiers are incomplete")
        if aggregate.get("request_failures_reproduced_at_concurrency_128") is not True:
            errors.append("aggregate Capacity v3 failure boundary is incomplete")
        if conclusion.get("highest_repeated_fully_reliable_tier") != 96:
            errors.append("aggregate Capacity v3 correctness lower bound differs")
        if conclusion.get("recommended_performance_safe_tier") != 64:
            errors.append("aggregate Capacity v3 performance-safe tier differs")
        if privacy.get("artifact_scan") != "clean" or privacy.get(
            "raw_results_tracked"
        ) is not False:
            errors.append("aggregate Capacity v3 privacy evidence is incomplete")

    if preflight_result is not None:
        if preflight_result.get("cloud_calls_enabled") is not False:
            errors.append("Capacity v3 preflight did not prove cloud isolation")
        if preflight_result.get("resource_metrics_available") is not True:
            errors.append("Capacity v3 resource metrics are unavailable")
        if preflight_result.get("database_pool") != {
            "pool_size": 20,
            "max_overflow": 20,
            "timeout_seconds": 30,
        }:
            errors.append("Capacity v3 database pool configuration does not match")
        actual_delays = {
            name: details.get("delay_ms")
            for name, details in preflight_result.get("stubs", {}).items()
            if isinstance(details, dict)
        }
        if actual_delays != manifest.get("stub_delays_ms"):
            errors.append("Capacity v3 stub delays do not match")

    if errors:
        raise ValueError("; ".join(errors))
    return manifest
