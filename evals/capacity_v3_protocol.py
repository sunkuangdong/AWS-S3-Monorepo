"""Identity and drift checks for the candidate Capacity v3 optimization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_V3_MANIFEST = PROJECT_ROOT / "evals/capacity_protocol_v3.json"
CAPACITY_V3_PROTOCOL_VERSION = "3.0.0"
CAPACITY_V3_PROTOCOL_STATUS = "candidate"

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
    """Reject identity, workload, optimization, or safety drift."""
    manifest = load_capacity_v3_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != CAPACITY_V3_PROTOCOL_VERSION:
        errors.append("Capacity v3 manifest version does not match the runner")
    if manifest.get("status") != CAPACITY_V3_PROTOCOL_STATUS:
        errors.append("Capacity v3 must remain candidate until full validation")

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
