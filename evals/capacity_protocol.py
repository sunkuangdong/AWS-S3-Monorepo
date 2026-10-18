"""Identity and drift checks for the exploratory capacity experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPACITY_MANIFEST = PROJECT_ROOT / "evals/capacity_protocol_v1.json"
CAPACITY_PROTOCOL_VERSION = "1.0.0"
CAPACITY_PROTOCOL_STATUS = "exploratory"


def load_capacity_manifest() -> dict[str, Any]:
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
    """Reject experiment parameter, safety, identity, or stub-delay drift."""
    manifest = load_capacity_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != CAPACITY_PROTOCOL_VERSION:
        errors.append("capacity manifest version does not match the runner")
    if manifest.get("status") != CAPACITY_PROTOCOL_STATUS:
        errors.append("capacity manifest must remain exploratory")

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
