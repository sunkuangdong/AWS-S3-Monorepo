"""Identity and drift validation for the deterministic load protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dataset import dataset_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOAD_MANIFEST = PROJECT_ROOT / "evals/load_protocol_v1.json"
LOAD_PROTOCOL_VERSION = "1.0.0"
LOAD_PROTOCOL_STATUS = "frozen"
LOAD_GIT_TAG = "load-eval-v1.0.0"
LOAD_IMPLEMENTATION_BASELINE_COMMIT = (
    "0d917ef6cfb1304b37fff37df153e918ad8134f5"
)
LOAD_EVIDENCE = PROJECT_ROOT / "evals/evidence/load_v1_summary.json"

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
    "overall",
)


def load_load_manifest(path: Path = LOAD_MANIFEST) -> dict[str, Any]:
    """Load the tracked candidate manifest for load protocol v1."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_load_protocol(
    *,
    concurrencies: list[int],
    requests_per_tier: int,
    warmup_requests_per_tier: int,
    timeout_seconds: float,
    preflight_result: dict[str, Any] | None = None,
    allow_parameter_deviation: bool = False,
) -> dict[str, Any]:
    """Reject manifest, runner, safety, gate, parameter, or stub drift."""
    manifest = load_load_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != LOAD_PROTOCOL_VERSION:
        errors.append("manifest protocol_version does not match the runner")
    if manifest.get("status") != LOAD_PROTOCOL_STATUS:
        errors.append("manifest status does not match the runner")

    runner = manifest.get("runner", {})
    expected_runner_identity = {
        "module": "evals.run_load",
        "application_module": "evals.load_app:app",
        "compose_profile": "evaluation",
        "compose_service": "load-api",
        "uvicorn_workers": 1,
    }
    for name, expected in expected_runner_identity.items():
        if runner.get(name) != expected:
            errors.append(f"runner {name} does not match load protocol v1")

    safety = manifest.get("safety", {})
    expected_safety = {
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "expected_cost_usd": 0.0,
    }
    for name, expected in expected_safety.items():
        if safety.get(name) != expected:
            errors.append(f"safety field {name} does not match load protocol v1")

    workload = manifest.get("workload", {})
    if workload.get("generation_type") != "text_to_image":
        errors.append("workload generation type must remain text_to_image")
    if (workload.get("width"), workload.get("height")) != (1024, 1024):
        errors.append("workload image dimensions do not match load protocol v1")

    if manifest.get("required_acceptance_gates") != list(
        REQUIRED_ACCEPTANCE_GATES
    ):
        errors.append("acceptance gates do not match the load runner")

    freeze = manifest.get("freeze", {})
    if freeze.get("git_tag") != LOAD_GIT_TAG:
        errors.append("Git tag does not match frozen load protocol v1")
    if (
        freeze.get("implementation_baseline_commit")
        != LOAD_IMPLEMENTATION_BASELINE_COMMIT
    ):
        errors.append("implementation baseline does not match frozen load protocol v1")
    expected_evidence_path = str(LOAD_EVIDENCE.relative_to(PROJECT_ROOT))
    if freeze.get("evidence_path") != expected_evidence_path:
        errors.append("evidence path does not match frozen load protocol v1")
    if not LOAD_EVIDENCE.is_file():
        errors.append("frozen aggregate load evidence is missing")
    elif dataset_sha256(LOAD_EVIDENCE) != freeze.get("evidence_sha256"):
        errors.append("aggregate load evidence SHA-256 does not match the manifest")
    else:
        evidence = json.loads(LOAD_EVIDENCE.read_text(encoding="utf-8"))
        if evidence.get("protocol_version") != LOAD_PROTOCOL_VERSION:
            errors.append("aggregate evidence protocol version does not match")
        if (
            evidence.get("implementation_baseline_commit")
            != LOAD_IMPLEMENTATION_BASELINE_COMMIT
        ):
            errors.append("aggregate evidence baseline commit does not match")
        if evidence.get("source_worktree_dirty") is not False:
            errors.append("aggregate evidence must originate from a clean worktree")
        if evidence.get("result", {}).get("overall_passed") is not True:
            errors.append("aggregate evidence did not pass all acceptance gates")

    if not allow_parameter_deviation:
        expected_parameters = {
            "concurrencies": concurrencies,
            "requests_per_tier": requests_per_tier,
            "warmup_requests_per_tier": warmup_requests_per_tier,
            "timeout_seconds": timeout_seconds,
        }
        for name, actual in expected_parameters.items():
            if runner.get(name) != actual:
                errors.append(
                    f"{name} does not match load protocol v1: "
                    f"expected {runner.get(name)}, got {actual}"
                )

    if preflight_result is not None:
        if preflight_result.get("cloud_calls_enabled") is not False:
            errors.append("preflight did not prove that cloud calls are disabled")
        actual_delays = {
            name: details.get("delay_ms")
            for name, details in preflight_result.get("stubs", {}).items()
            if isinstance(details, dict)
        }
        expected_delays = manifest.get("stub_delays_ms", {})
        if actual_delays != expected_delays:
            errors.append(
                "stub delays do not match load protocol v1: "
                f"expected {expected_delays}, got {actual_delays}"
            )

    if errors:
        raise ValueError("; ".join(errors))
    return manifest
