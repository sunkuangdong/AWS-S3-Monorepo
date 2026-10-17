"""Frozen identity and validation rules for the workflow evaluation protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.dataset import dataset_sha256, load_cases

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "1.0.0"
PROTOCOL_STATUS = "frozen"
FROZEN_MANIFEST = PROJECT_ROOT / "evals/frozen_protocol_v1.json"

REQUIRED_ACCEPTANCE_GATES = (
    "all_cases_match_labels",
    "normal_paths_complete",
    "external_failures_are_contained",
    "invalid_inputs_are_rejected",
    "database_completion_failures_are_compensated",
    "all_terminal_states_are_consistent",
    "no_orphan_outputs",
    "no_unexpected_pending_records",
    "overall",
)


def load_frozen_manifest(path: Path = FROZEN_MANIFEST) -> dict[str, Any]:
    """Load the tracked manifest that defines the immutable v1 inputs."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_frozen_protocol(
    dataset_path: Path,
    *,
    concurrency: int | None = None,
) -> dict[str, Any]:
    """Reject protocol, path, digest, or case-ID drift from frozen v1."""
    manifest = load_frozen_manifest()
    errors: list[str] = []

    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("manifest protocol_version does not match the runner")
    if manifest.get("status") != PROTOCOL_STATUS:
        errors.append("manifest status must be frozen")

    runner = manifest.get("runner", {})
    if runner.get("module") != "evals.run_workflow":
        errors.append("runner module does not match the frozen protocol")
    if runner.get("offline") is not True:
        errors.append("frozen protocol must remain offline")
    if concurrency is not None and concurrency != runner.get("concurrency"):
        errors.append(
            "concurrency does not match the frozen protocol: "
            f"expected {runner.get('concurrency')}, got {concurrency}"
        )

    dataset = manifest.get("dataset", {})
    expected_path = PROJECT_ROOT / str(dataset.get("path", ""))
    resolved_path = dataset_path.resolve()
    if resolved_path != expected_path.resolve():
        errors.append(
            "dataset path is outside the frozen protocol: "
            f"expected {expected_path.relative_to(PROJECT_ROOT)}, got {resolved_path}"
        )

    cases = load_cases(resolved_path)
    actual_sha256 = dataset_sha256(resolved_path)
    actual_case_ids = [case.case_id for case in cases]
    if actual_sha256 != dataset.get("sha256"):
        errors.append("dataset SHA-256 does not match the frozen manifest")
    if len(cases) != dataset.get("case_count"):
        errors.append("dataset case count does not match the frozen manifest")
    if actual_case_ids != dataset.get("case_ids"):
        errors.append(
            "dataset case IDs or their order do not match the frozen manifest"
        )

    if manifest.get("required_acceptance_gates") != list(REQUIRED_ACCEPTANCE_GATES):
        errors.append("acceptance-gate definition does not match the frozen runner")

    if errors:
        raise ValueError("; ".join(errors))
    return manifest
