"""Dataset loading and validation for workflow evaluations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_GENERATION_TYPES = {
    "text_to_image",
    "image_to_image",
}
ALLOWED_CATEGORIES = {
    "normal_path",
    "external_failure",
    "database_failure",
    "post_commit_failure",
    "validation",
}
ALLOWED_FAILURE_POINTS = {
    None,
    "reference_presign",
    "vision",
    "reference_download",
    "image_generate",
    "image_edit",
    "output_upload",
    "database_complete",
    "response_presign",
    "invalid_object_key",
}
ALLOWED_OUTCOMES = {
    "completed",
    "handled_failure",
    "infrastructure_failure",
    "rejected",
}
ALLOWED_DB_STATUSES = {
    None,
    "pending",
    "completed",
    "failed",
}


@dataclass(frozen=True)
class WorkflowCase:
    """One deterministic workflow scenario and its expected terminal state."""

    case_id: str
    category: str
    generation_type: str
    prompt: str
    input_object_key: str | None
    failure_point: str | None
    expected_outcome: str
    expected_db_status: str | None
    expected_output_present: bool
    expected_orphan_outputs: int
    mock_delay_ms: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowCase:
        return cls(
            case_id=str(payload["id"]),
            category=str(payload["category"]),
            generation_type=str(payload["generation_type"]),
            prompt=str(payload["prompt"]),
            input_object_key=payload.get("input_object_key"),
            failure_point=payload.get("failure_point"),
            expected_outcome=str(payload["expected_outcome"]),
            expected_db_status=payload.get("expected_db_status"),
            expected_output_present=bool(payload["expected_output_present"]),
            expected_orphan_outputs=int(payload["expected_orphan_outputs"]),
            mock_delay_ms=int(payload.get("mock_delay_ms", 5)),
        )


def dataset_sha256(path: Path) -> str:
    """Return the digest of the exact bytes used by a run."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> list[WorkflowCase]:
    """Load JSONL cases and reject malformed or ambiguous labels."""
    cases: list[WorkflowCase] = []
    errors: list[str] = []

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            case = WorkflowCase.from_dict(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"line {line_number}: {type(error).__name__}")
            continue
        errors.extend(_validate_case(case, line_number))
        cases.append(case)

    duplicate_ids = sorted(
        case_id
        for case_id in {case.case_id for case in cases}
        if sum(case.case_id == case_id for case in cases) > 1
    )
    if duplicate_ids:
        errors.append(f"duplicate ids: {', '.join(duplicate_ids)}")
    if not cases:
        errors.append("dataset contains no cases")
    if errors:
        raise ValueError("; ".join(errors))
    return cases


def _validate_case(case: WorkflowCase, line_number: int) -> list[str]:
    prefix = f"line {line_number} ({case.case_id})"
    errors: list[str] = []
    if not case.case_id.startswith("workflow-"):
        errors.append(f"{prefix}: id must start with workflow-")
    if case.category not in ALLOWED_CATEGORIES:
        errors.append(f"{prefix}: unsupported category {case.category}")
    if case.generation_type not in ALLOWED_GENERATION_TYPES:
        errors.append(f"{prefix}: unsupported generation_type {case.generation_type}")
    if case.failure_point not in ALLOWED_FAILURE_POINTS:
        errors.append(f"{prefix}: unsupported failure_point {case.failure_point}")
    if case.expected_outcome not in ALLOWED_OUTCOMES:
        errors.append(f"{prefix}: unsupported expected_outcome {case.expected_outcome}")
    if case.expected_db_status not in ALLOWED_DB_STATUSES:
        errors.append(
            f"{prefix}: unsupported expected_db_status {case.expected_db_status}"
        )
    if not 1 <= len(case.prompt) <= 400:
        errors.append(f"{prefix}: prompt length must be between 1 and 400")
    if not 0 <= case.mock_delay_ms <= 1_000:
        errors.append(f"{prefix}: mock_delay_ms must be between 0 and 1000")
    if case.expected_orphan_outputs < 0:
        errors.append(f"{prefix}: expected_orphan_outputs cannot be negative")

    needs_input = case.generation_type == "image_to_image"
    has_input = case.input_object_key is not None
    if needs_input != has_input:
        errors.append(f"{prefix}: input_object_key must match generation_type")
    if case.failure_point == "invalid_object_key" and (
        case.input_object_key is None or case.input_object_key.startswith("uploads/")
    ):
        errors.append(f"{prefix}: invalid_object_key case must use a rejected prefix")
    return errors
