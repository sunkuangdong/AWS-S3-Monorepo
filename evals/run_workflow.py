"""Run the image workflow against deterministic in-memory dependencies."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.exceptions import (
    ImageGenerationError,
    InvalidObjectKeyError,
    StorageError,
    VisionModelError,
)
from app.models.image_generation import ImageGeneration
from app.schemas.image_generation import (
    CreateImageGenerationRequest,
)
from app.services.image_service import ImageService

from evals.dataset import WorkflowCase, dataset_sha256, load_cases
from evals.scoring import build_summary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals/datasets/workflow_smoke_v1.jsonl"
PROTOCOL_VERSION = "1.0.0-draft"

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"


def _sleep(delay_ms: int) -> None:
    time.sleep(delay_ms / 1_000)


async def _async_sleep(delay_ms: int) -> None:
    await asyncio.sleep(delay_ms / 1_000)


@dataclass(frozen=True)
class PersistedGeneration:
    id: UUID
    user_prompt: str
    image_analysis: str | None
    final_prompt: str
    generation_type: str
    input_object_key: str | None
    output_object_key: str | None
    width: int
    height: int
    status: str
    created_at: datetime

    @classmethod
    def capture(cls, generation: ImageGeneration) -> PersistedGeneration:
        return cls(
            id=generation.id,
            user_prompt=generation.user_prompt,
            image_analysis=generation.image_analysis,
            final_prompt=generation.final_prompt,
            generation_type=generation.generation_type,
            input_object_key=generation.input_object_key,
            output_object_key=generation.output_object_key,
            width=generation.width,
            height=generation.height,
            status=generation.status,
            created_at=generation.created_at,
        )

    def restore(self) -> ImageGeneration:
        return ImageGeneration(
            id=self.id,
            user_prompt=self.user_prompt,
            image_analysis=self.image_analysis,
            final_prompt=self.final_prompt,
            generation_type=self.generation_type,
            input_object_key=self.input_object_key,
            output_object_key=self.output_object_key,
            width=self.width,
            height=self.height,
            status=self.status,
            created_at=self.created_at,
        )


class FakeRepository:
    """Model commit boundaries without touching PostgreSQL."""

    def __init__(self, case: WorkflowCase) -> None:
        self.case = case
        self.current: ImageGeneration | None = None
        self.persisted: PersistedGeneration | None = None
        self.calls: Counter[str] = Counter()

    async def create(self, generation: ImageGeneration) -> ImageGeneration:
        self.calls["create"] += 1
        generation.id = uuid5(NAMESPACE_URL, self.case.case_id)
        generation.created_at = datetime(2026, 10, 17, tzinfo=UTC)
        self.current = generation
        return generation

    async def mark_completed(
        self,
        generation: ImageGeneration,
        *,
        image_analysis: str | None,
        final_prompt: str,
        output_object_key: str,
    ) -> ImageGeneration:
        self.calls["mark_completed"] += 1
        generation.image_analysis = image_analysis
        generation.final_prompt = final_prompt
        generation.output_object_key = output_object_key
        generation.status = "completed"
        self.current = generation
        return generation

    async def mark_failed(
        self,
        generation: ImageGeneration,
    ) -> ImageGeneration:
        self.calls["mark_failed"] += 1
        generation.status = "failed"
        self.current = generation
        return generation

    async def commit(self) -> None:
        self.calls["commit"] += 1
        if self.current is None:
            raise RuntimeError("commit_without_current_generation")
        if (
            self.case.failure_point == "database_complete"
            and self.current.status == "completed"
        ):
            raise RuntimeError("injected_database_completion_failure")
        self.persisted = PersistedGeneration.capture(self.current)

    async def rollback(self) -> None:
        self.calls["rollback"] += 1
        self.current = self.persisted.restore() if self.persisted is not None else None

    async def get_by_id(self, generation_id: UUID) -> ImageGeneration | None:
        self.calls["get_by_id"] += 1
        if self.persisted is None or self.persisted.id != generation_id:
            return None
        self.current = self.persisted.restore()
        return self.current


class FakeStorage:
    """Model S3 calls and track generated objects for orphan detection."""

    def __init__(self, case: WorkflowCase) -> None:
        self.case = case
        self.settings = SimpleNamespace(presigned_url_expires=600)
        self.uploaded_output_keys: set[str] = set()
        self.calls: Counter[str] = Counter()

    def create_presigned_download_url(self, object_key: str) -> str:
        self.calls["create_presigned_download_url"] += 1
        _sleep(self.case.mock_delay_ms)
        if self.case.failure_point == "reference_presign" and object_key.startswith(
            "uploads/"
        ):
            raise StorageError("injected reference presign failure")
        if self.case.failure_point == "response_presign" and object_key.startswith(
            "generations/"
        ):
            raise StorageError("injected response presign failure")
        return f"https://offline.invalid/{object_key}"

    def download_image(self, *, object_key: str) -> SimpleNamespace:
        self.calls["download_image"] += 1
        _sleep(self.case.mock_delay_ms)
        if self.case.failure_point == "reference_download":
            raise StorageError("injected reference download failure")
        return SimpleNamespace(
            data=b"deterministic-reference-image",
            file_name=Path(object_key).name,
            content_type="image/png",
        )

    def upload_generated_image(self, *, image_bytes: bytes) -> str:
        self.calls["upload_generated_image"] += 1
        _sleep(self.case.mock_delay_ms)
        if self.case.failure_point == "output_upload":
            raise StorageError("injected output upload failure")
        if not image_bytes:
            raise ValueError("empty generated image")
        object_key = f"generations/{self.case.case_id}.png"
        self.uploaded_output_keys.add(object_key)
        return object_key

    def delete_generated_image(self, *, object_key: str) -> None:
        self.calls["delete_generated_image"] += 1
        _sleep(self.case.mock_delay_ms)
        self.uploaded_output_keys.discard(object_key)


class FakeVision:
    def __init__(self, case: WorkflowCase) -> None:
        self.case = case
        self.calls: Counter[str] = Counter()

    async def analyze_image(self, image_url: str, prompt: str) -> str:
        self.calls["analyze_image"] += 1
        await _async_sleep(self.case.mock_delay_ms)
        if self.case.failure_point == "vision":
            raise VisionModelError("injected vision failure")
        if not image_url or not prompt:
            raise AssertionError("vision inputs must be non-empty")
        return "A deterministic reference subject on a neutral background."


class FakeImageGeneration:
    def __init__(self, case: WorkflowCase) -> None:
        self.case = case
        self.calls: Counter[str] = Counter()

    async def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        self.calls["generate_image"] += 1
        await _async_sleep(self.case.mock_delay_ms)
        if self.case.failure_point == "image_generate":
            raise ImageGenerationError("injected image generation failure")
        return f"generated:{prompt}:{width}x{height}".encode()

    async def edit_image(
        self,
        *,
        image_bytes: bytes,
        file_name: str,
        content_type: str,
        prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        self.calls["edit_image"] += 1
        await _async_sleep(self.case.mock_delay_ms)
        if self.case.failure_point == "image_edit":
            raise ImageGenerationError("injected image edit failure")
        if not image_bytes or not file_name or content_type != "image/png":
            raise AssertionError("invalid deterministic edit input")
        return f"edited:{prompt}:{width}x{height}".encode()


class InFlightTracker:
    def __init__(self) -> None:
        self.current = 0
        self.maximum = 0

    def enter(self) -> None:
        self.current += 1
        self.maximum = max(self.maximum, self.current)

    def exit(self) -> None:
        self.current -= 1


def _state_consistent(
    persisted: PersistedGeneration | None,
    uploaded_output_keys: set[str],
) -> tuple[bool, bool, int]:
    output_key = persisted.output_object_key if persisted else None
    output_present = bool(output_key and output_key in uploaded_output_keys)
    referenced = {output_key} if output_key else set()
    orphan_count = len(uploaded_output_keys - referenced)

    if persisted is None:
        consistent = not uploaded_output_keys
    elif persisted.status == "completed":
        consistent = output_present and orphan_count == 0
    elif persisted.status == "failed":
        consistent = output_key is None and orphan_count == 0
    else:
        consistent = False
    return consistent, output_present, orphan_count


async def run_case(case: WorkflowCase) -> dict[str, Any]:
    repository = FakeRepository(case)
    storage = FakeStorage(case)
    vision = FakeVision(case)
    image_generation = FakeImageGeneration(case)
    service = ImageService(storage, vision, image_generation, repository)
    request = CreateImageGenerationRequest(
        prompt=case.prompt,
        input_object_key=case.input_object_key,
    )

    started = time.perf_counter()
    outcome = "completed"
    error_type: str | None = None
    try:
        await service.create_generation(request)
    except InvalidObjectKeyError as error:
        outcome = "rejected"
        error_type = type(error).__name__
    except (ImageGenerationError, StorageError, VisionModelError) as error:
        outcome = "handled_failure"
        error_type = type(error).__name__
    except Exception as error:  # noqa: BLE001 - evaluator classifies runtime faults
        outcome = "infrastructure_failure"
        error_type = type(error).__name__
    latency_ms = round((time.perf_counter() - started) * 1_000, 3)

    persisted = repository.persisted
    state_consistent, output_present, orphan_count = _state_consistent(
        persisted,
        storage.uploaded_output_keys,
    )
    db_status = persisted.status if persisted else None
    matches_expected = (
        outcome == case.expected_outcome
        and db_status == case.expected_db_status
        and output_present == case.expected_output_present
        and orphan_count == case.expected_orphan_outputs
    )

    return {
        "case_id": case.case_id,
        "category": case.category,
        "generation_type": case.generation_type,
        "failure_point": case.failure_point,
        "expected": {
            "outcome": case.expected_outcome,
            "db_status": case.expected_db_status,
            "output_present": case.expected_output_present,
            "orphan_output_count": case.expected_orphan_outputs,
        },
        "outcome": outcome,
        "error_type": error_type,
        "db_status": db_status,
        "output_present": output_present,
        "orphan_output_count": orphan_count,
        "state_consistent": state_consistent,
        "matches_expected": matches_expected,
        "latency_ms": latency_ms,
        "calls": {
            "repository": dict(sorted(repository.calls.items())),
            "storage": dict(sorted(storage.calls.items())),
            "vision": dict(sorted(vision.calls.items())),
            "image_generation": dict(sorted(image_generation.calls.items())),
        },
    }


async def run_cases(
    cases: list[WorkflowCase],
    *,
    concurrency: int,
) -> tuple[list[dict[str, Any]], int]:
    semaphore = asyncio.Semaphore(concurrency)
    tracker = InFlightTracker()

    async def guarded(case: WorkflowCase) -> dict[str, Any]:
        async with semaphore:
            tracker.enter()
            try:
                return await run_case(case)
            finally:
                tracker.exit()

    runs = await asyncio.gather(*(guarded(case) for case in cases))
    return list(runs), tracker.maximum


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    score = summary["score"]
    gates = summary["acceptance_gates"]
    latency = summary["latency_ms"]
    return "\n".join(
        [
            "# Offline Image Workflow Evaluation",
            "",
            f"- Protocol: `{config['protocol_version']}`",
            f"- Dataset: `{config['dataset']['path']}`",
            f"- Dataset SHA-256: `{config['dataset']['sha256']}`",
            f"- Cases: {summary['run_count']}",
            f"- Cloud calls: `{str(summary['cloud_calls']).lower()}`",
            "",
            "## Results",
            "",
            f"- Normal-path task success: {score['normal_path_task_success_rate']:.1%}",
            f"- External-failure containment: {score['external_failure_containment_rate']:.1%}",
            f"- State consistency: {score['state_consistency_rate']:.1%}",
            f"- Dataset expectation match: {score['scenario_expectation_rate']:.1%}",
            f"- Orphan generated objects: {score['orphan_output_count']}",
            f"- Unexpected pending records: {score['unexpected_pending_count']}",
            (
                f"- Latency P50/P95: {latency['p50_nearest_rank']:.3f} ms / "
                f"{latency['p95_nearest_rank']:.3f} ms"
            ),
            "",
            "## Acceptance Gates",
            "",
            *(f"- {name}: `{str(value).lower()}`" for name, value in gates.items()),
            "",
            "## Interpretation",
            "",
            summary["interpretation"],
            "",
            (
                "The database-completion failure case verifies compensation: "
                "the uploaded output is removed and the committed task is marked "
                "failed before the original infrastructure error is propagated."
            ),
            "",
        ]
    )


def execute(
    *,
    dataset_path: Path,
    output_dir: Path,
    concurrency: int,
) -> dict[str, Any]:
    cases = load_cases(dataset_path)
    runs, max_in_flight = asyncio.run(run_cases(cases, concurrency=concurrency))
    summary = build_summary(
        runs,
        requested_concurrency=concurrency,
        max_in_flight=max_in_flight,
    )
    status = _git_value("status", "--porcelain")
    config = {
        "protocol_version": PROTOCOL_VERSION,
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(status),
        "offline": True,
        "langfuse_tracing_enabled": False,
        "concurrency": concurrency,
        "dataset": {
            "path": str(dataset_path.relative_to(PROJECT_ROOT)),
            "sha256": dataset_sha256(dataset_path),
            "case_count": len(cases),
            "case_ids": [case.case_id for case in cases],
        },
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "raw_runs.jsonl").write_text(
        "".join(json.dumps(run, ensure_ascii=False) + "\n" for run in runs),
        encoding="utf-8",
    )
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "config.json", config)
    (output_dir / "report.md").write_text(
        _render_report(summary, config),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--fail-on-gate", action="store_true")
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    dataset_path = args.dataset.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_{dataset_path.stem}"
    )
    summary = execute(
        dataset_path=dataset_path,
        output_dir=output_dir,
        concurrency=args.concurrency,
    )
    print(f"Results: {output_dir.relative_to(PROJECT_ROOT)}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.fail_on_gate and not summary["acceptance_gates"]["overall"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
