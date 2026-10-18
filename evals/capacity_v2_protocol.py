"""Identity and drift checks for the candidate Capacity v2 experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_V2_MANIFEST = PROJECT_ROOT / "evals/capacity_protocol_v2.json"
CAPACITY_V2_PROTOCOL_VERSION = "2.0.0"
CAPACITY_V2_PROTOCOL_STATUS = "candidate"

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
        errors.append("Capacity v2 manifest must remain candidate until frozen")

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
