"""Run a budgeted, privacy-safe smoke test against real service dependencies."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import httpx
from dotenv import load_dotenv
from langfuse import Langfuse

from evals.dataset import dataset_sha256
from evals.live_smoke import (
    LIVE_PROTOCOL_STATUS,
    LIVE_PROTOCOL_VERSION,
    LiveSmokeCase,
    build_live_summary,
    load_live_cases,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ENV_FILE = PROJECT_ROOT / "apps/api/.env"
DEFAULT_DATASET = PROJECT_ROOT / "evals/datasets/live_smoke_v1.jsonl"
DEFAULT_API_BASE_URL = "http://localhost:8000"
DEFAULT_MAXIMUM_COST_USD = 0.30

TEXT_TRACE_NAMES = {
    "image-generation-workflow",
    "postgresql-persist-pending",
    "openai-image-generation",
    "s3-upload-generated-image",
    "postgresql-persist-completed",
}
IMAGE_TRACE_NAMES = {
    "image-generation-workflow",
    "postgresql-persist-pending",
    "s3-presign-reference-download",
    "openai-vision-analysis",
    "s3-download-reference-image",
    "openai-image-edit",
    "s3-upload-generated-image",
    "postgresql-persist-completed",
}
EMPTY_TRACE_VALUES = {None, "", "undefined", "null"}


class SafeLiveSmokeError(RuntimeError):
    """Failure description that is safe to persist without provider payloads."""

    def __init__(self, stage: str, error_type: str, status_code: int | None = None):
        super().__init__(stage)
        self.stage = stage
        self.error_type = error_type
        self.status_code = status_code


def _git_value(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _trace_value_is_empty(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in EMPTY_TRACE_VALUES
    )


def _validated_api_base_url(value: str) -> str:
    url = httpx.URL(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise SafeLiveSmokeError("api_base_url", "UnsafeURL")
    return str(url).rstrip("/")


def _response_json(
    response: httpx.Response,
    *,
    stage: str,
    expected_status: int,
) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise SafeLiveSmokeError(stage, "UnexpectedHTTPStatus", response.status_code)
    try:
        payload = response.json()
    except ValueError as error:
        raise SafeLiveSmokeError(
            stage, type(error).__name__, response.status_code
        ) from None
    if not isinstance(payload, dict):
        raise SafeLiveSmokeError(stage, "UnexpectedResponseShape", response.status_code)
    return payload


def _preflight_reference_object(object_key: str) -> dict[str, Any]:
    if not object_key.startswith("uploads/") or ".." in object_key.split("/"):
        raise SafeLiveSmokeError("reference_object", "InvalidObjectKey")
    bucket = os.getenv("S3_BUCKET", "").strip()
    region = os.getenv("AWS_DEFAULT_REGION", "").strip()
    if not bucket or not region:
        raise SafeLiveSmokeError("reference_object", "MissingS3Configuration")
    try:
        response = boto3.client("s3", region_name=region).head_object(
            Bucket=bucket,
            Key=object_key,
        )
    except Exception as error:  # noqa: BLE001 - sanitize provider errors
        raise SafeLiveSmokeError("reference_object", type(error).__name__) from None
    content_type = str(response.get("ContentType") or "")
    size_bytes = int(response.get("ContentLength") or 0)
    if not content_type.startswith("image/") or size_bytes < 1:
        raise SafeLiveSmokeError("reference_object", "InvalidReferenceObject")
    return {
        "exists": True,
        "content_type": content_type,
        "size_bytes": size_bytes,
    }


class TraceReader:
    """Read only bounded operational evidence from Langfuse."""

    def __init__(self, *, environment: str, wait_seconds: int) -> None:
        self.environment = environment
        self.wait_seconds = wait_seconds
        self.client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            base_url=os.getenv("LANGFUSE_BASE_URL"),
            tracing_enabled=False,
        )

    def close(self) -> None:
        self.client.shutdown()

    def preflight(self) -> None:
        try:
            authenticated = self.client.auth_check()
        except Exception as error:  # noqa: BLE001 - sanitize remote errors
            raise SafeLiveSmokeError("langfuse_auth", type(error).__name__) from None
        if not authenticated:
            raise SafeLiveSmokeError("langfuse_auth", "AuthenticationRejected")

    def _read_trace(self, trace_id: str) -> list[Any]:
        response = self.client.api.observations.get_many(
            trace_id=trace_id,
            limit=100,
            fields="basic,time,io,metadata,model,usage,metrics,trace_context",
        )
        return list(response.data)

    def collect(
        self,
        *,
        generation_id: str,
        generation_type: str,
        started_at: datetime,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.wait_seconds
        required_names = (
            TEXT_TRACE_NAMES
            if generation_type == "text_to_image"
            else IMAGE_TRACE_NAMES
        )
        last_result = {
            "trace_found": False,
            "trace_complete": False,
            "privacy_safe": False,
            "cost_measured": False,
            "total_cost_usd": None,
            "trace_id": None,
            "observation_count": 0,
            "model_names": [],
        }
        while time.monotonic() <= deadline:
            try:
                roots = self.client.api.observations.get_many(
                    name="image-generation-workflow",
                    is_root_observation=True,
                    environment=self.environment,
                    from_start_time=started_at - timedelta(seconds=30),
                    limit=100,
                    fields=("basic,time,io,metadata,model,usage,metrics,trace_context"),
                ).data
                root = next(
                    (
                        observation
                        for observation in roots
                        if (observation.metadata or {}).get("generation_id")
                        == generation_id
                    ),
                    None,
                )
                if root is not None and root.trace_id:
                    observations = self._read_trace(root.trace_id)
                    names = {
                        observation.name
                        for observation in observations
                        if observation.name
                    }
                    generations = [
                        observation
                        for observation in observations
                        if observation.type.upper() == "GENERATION"
                    ]
                    costs = [observation.total_cost for observation in generations]
                    privacy_safe = all(
                        _trace_value_is_empty(observation.input)
                        and _trace_value_is_empty(observation.output)
                        for observation in observations
                    )
                    last_result = {
                        "trace_found": True,
                        "trace_complete": required_names <= names
                        and all(
                            observation.end_time is not None
                            for observation in observations
                        ),
                        "privacy_safe": privacy_safe,
                        "cost_measured": bool(generations)
                        and all(cost is not None for cost in costs),
                        "total_cost_usd": (
                            round(
                                sum(float(cost) for cost in costs if cost is not None),
                                12,
                            )
                            if generations and all(cost is not None for cost in costs)
                            else None
                        ),
                        "trace_id": root.trace_id,
                        "observation_count": len(observations),
                        "model_names": sorted(
                            {
                                observation.model
                                for observation in generations
                                if observation.model
                            }
                        ),
                    }
                    if (
                        last_result["trace_complete"]
                        and last_result["privacy_safe"]
                        and last_result["cost_measured"]
                    ):
                        return last_result
            except Exception as error:  # noqa: BLE001 - sanitized retry evidence
                last_result["trace_read_error_type"] = type(error).__name__
            time.sleep(2)
        return last_result


def _preflight(
    *,
    client: httpx.Client,
    trace_reader: TraceReader,
    reference_object_key: str,
) -> dict[str, Any]:
    health = _response_json(
        client.get("/health/database"),
        stage="database_health",
        expected_status=200,
    )
    if health.get("status") != "ok" or health.get("database") != "reachable":
        raise SafeLiveSmokeError("database_health", "UnexpectedHealthResponse", 200)
    reference = _preflight_reference_object(reference_object_key)
    trace_reader.preflight()
    return {
        "api_reachable": True,
        "database_reachable": True,
        "reference_object": reference,
        "langfuse_authenticated": True,
    }


def _verify_s3_output(client: httpx.Client, download_url: str) -> dict[str, Any]:
    try:
        response = client.get(download_url, headers={"Range": "bytes=0-0"})
    except httpx.HTTPError as error:
        raise SafeLiveSmokeError("s3_output", type(error).__name__) from None
    if response.status_code not in {200, 206}:
        raise SafeLiveSmokeError(
            "s3_output", "UnexpectedHTTPStatus", response.status_code
        )
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/") or not response.content:
        raise SafeLiveSmokeError(
            "s3_output", "InvalidImageResponse", response.status_code
        )
    return {
        "retrievable": True,
        "content_type": content_type.split(";", 1)[0],
        "bytes_read": len(response.content),
    }


def _run_case(
    *,
    client: httpx.Client,
    trace_reader: TraceReader,
    case: LiveSmokeCase,
    reference_object_key: str,
    run_id: str,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    request_id = f"{run_id}-{case.case_id}"
    base_result: dict[str, Any] = {
        "case_id": case.case_id,
        "generation_type": case.generation_type,
        "api_completed": False,
        "database_verified": False,
        "s3_verified": False,
        "trace_found": False,
        "trace_complete": False,
        "privacy_safe": False,
        "cost_measured": False,
        "total_cost_usd": None,
        "generation_id": None,
        "trace_id": None,
        "request_id": request_id,
        "observation_count": 0,
        "model_names": [],
        "output_content_type": None,
        "error_stage": None,
        "error_type": None,
        "http_status": None,
        "latency_ms": 0.0,
    }
    try:
        request_payload: dict[str, Any] = {
            "prompt": case.prompt,
            "width": 1024,
            "height": 1024,
        }
        if case.generation_type == "image_to_image":
            request_payload["input_object_key"] = reference_object_key
        created = _response_json(
            client.post(
                "/api/v1/images/generations",
                json=request_payload,
                headers={"X-Request-ID": request_id},
            ),
            stage="create_generation",
            expected_status=201,
        )
        generation_id = str(created.get("id") or "")
        api_completed = (
            bool(generation_id)
            and created.get("status") == "completed"
            and created.get("generation_type") == case.generation_type
            and str(created.get("output_object_key") or "").startswith("generations/")
        )
        if not api_completed:
            raise SafeLiveSmokeError(
                "create_generation", "UnexpectedCompletedState", 201
            )
        base_result["generation_id"] = generation_id
        base_result["api_completed"] = True

        persisted = _response_json(
            client.get(f"/api/v1/images/generations/{generation_id}"),
            stage="database_readback",
            expected_status=200,
        )
        database_verified = (
            str(persisted.get("id")) == generation_id
            and persisted.get("status") == "completed"
            and persisted.get("generation_type") == case.generation_type
            and str(persisted.get("output_object_key") or "").startswith("generations/")
        )
        if not database_verified:
            raise SafeLiveSmokeError("database_readback", "InconsistentState", 200)
        base_result["database_verified"] = True

        download = _response_json(
            client.get(f"/api/v1/images/generations/{generation_id}/download"),
            stage="download_signing",
            expected_status=200,
        )
        download_url = str(download.get("download_url") or "")
        if not download_url.startswith("https://"):
            raise SafeLiveSmokeError("download_signing", "InvalidDownloadURL", 200)
        s3_result = _verify_s3_output(client, download_url)
        base_result["s3_verified"] = s3_result["retrievable"]
        base_result["output_content_type"] = s3_result["content_type"]

        trace_result = trace_reader.collect(
            generation_id=generation_id,
            generation_type=case.generation_type,
            started_at=started_at,
        )
        base_result.update(trace_result)
    except SafeLiveSmokeError as error:
        base_result["error_stage"] = error.stage
        base_result["error_type"] = error.error_type
        base_result["http_status"] = error.status_code
    except httpx.HTTPError as error:
        base_result["error_stage"] = "api_transport"
        base_result["error_type"] = type(error).__name__
    finally:
        base_result["latency_ms"] = round(
            (time.perf_counter() - started) * 1_000,
            3,
        )
    return base_result


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    score = summary["score"]
    gates = summary["acceptance_gates"]
    cost = summary["cost_usd"]
    latency = summary["latency_ms"]
    return "\n".join(
        [
            "# Live Image Workflow Smoke Evaluation",
            "",
            f"- Protocol: `{config['protocol_version']}` ({config['protocol_status']})",
            f"- Dataset SHA-256: `{config['dataset']['sha256']}`",
            f"- Executed/planned cases: {summary['run_count']}/{summary['planned_case_count']}",
            f"- Cloud calls: `{str(summary['cloud_calls']).lower()}`",
            "",
            "## Results",
            "",
            f"- API task success: {score['api_task_success_rate'] or 0:.1%}",
            f"- PostgreSQL consistency: {score['database_consistency_rate'] or 0:.1%}",
            f"- S3 output retrieval: {score['s3_output_retrieval_rate'] or 0:.1%}",
            f"- Langfuse trace completeness: {score['langfuse_trace_completeness_rate'] or 0:.1%}",
            f"- Trace privacy compliance: {score['trace_privacy_compliance_rate'] or 0:.1%}",
            f"- Measured model cost: ${cost['total']:.6f} / ${cost['maximum']:.2f}",
            (
                f"- End-to-end latency P50/P95: "
                f"{latency['p50_nearest_rank'] or 0:.1f} ms / "
                f"{latency['p95_nearest_rank'] or 0:.1f} ms"
            ),
            "",
            "## Acceptance Gates",
            "",
            *(f"- {name}: `{str(value).lower()}`" for name, value in gates.items()),
            "",
            "## Safety and interpretation",
            "",
            "This paid smoke test uses real PostgreSQL, S3, OpenAI, and Langfuse dependencies.",
            "Artifacts omit prompts, object keys, presigned URLs, image bytes, and credentials.",
            "Four samples support integration evidence, not throughput or production-SLA claims.",
            "",
        ]
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument(
        "--reference-object-key",
        default=os.getenv("LIVE_SMOKE_REFERENCE_OBJECT_KEY"),
    )
    parser.add_argument(
        "--maximum-cost-usd",
        type=float,
        default=DEFAULT_MAXIMUM_COST_USD,
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--trace-wait-seconds", type=int, default=30)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--confirm-cloud-spend", action="store_true")
    parser.add_argument("--fail-on-gate", action="store_true")
    return parser.parse_args()


def main() -> int:
    # Docker Compose uses this same file, so the preflight must inspect the
    # credentials and tracing configuration actually supplied to the API.
    load_dotenv(API_ENV_FILE, override=True)
    args = _parse_args()
    if not args.reference_object_key:
        raise SystemExit("--reference-object-key is required and is never stored")
    if args.maximum_cost_usd <= 0:
        raise SystemExit("--maximum-cost-usd must be positive")
    if args.trace_wait_seconds < 1:
        raise SystemExit("--trace-wait-seconds must be at least 1")
    if not args.validate_only and not args.confirm_cloud_spend:
        raise SystemExit("refusing paid calls without --confirm-cloud-spend")
    if os.getenv("LANGFUSE_TRACING_ENABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise SystemExit("LANGFUSE_TRACING_ENABLED must be true for live smoke")

    dataset_path = args.dataset.resolve()
    cases = load_live_cases(dataset_path)
    api_base_url = _validated_api_base_url(args.api_base_url)
    environment = os.getenv("LANGFUSE_ENVIRONMENT", "local-evaluation")
    trace_reader = TraceReader(
        environment=environment,
        wait_seconds=args.trace_wait_seconds,
    )
    timeout = httpx.Timeout(args.timeout_seconds)
    try:
        with httpx.Client(
            base_url=api_base_url,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            preflight = _preflight(
                client=client,
                trace_reader=trace_reader,
                reference_object_key=args.reference_object_key,
            )
            if args.validate_only:
                print(
                    json.dumps(
                        {
                            "valid": True,
                            "paid_model_calls": 0,
                            "case_count": len(cases),
                            "dataset_sha256": dataset_sha256(dataset_path),
                            "preflight": preflight,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                return 0

            run_id = (
                f"live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
            )
            runs: list[dict[str, Any]] = []
            stopped_reason: str | None = None
            for case in cases:
                result = _run_case(
                    client=client,
                    trace_reader=trace_reader,
                    case=case,
                    reference_object_key=args.reference_object_key,
                    run_id=run_id,
                )
                runs.append(result)
                print(
                    f"[{len(runs)}/{len(cases)}] {case.case_id}: "
                    f"api={result['api_completed']} "
                    f"trace={result['trace_complete']} "
                    f"cost={result['total_cost_usd']}"
                )
                if not result["api_completed"]:
                    stopped_reason = "case_failure"
                    break
                if not result["cost_measured"]:
                    stopped_reason = "cost_not_measured"
                    break
                running_cost = sum(float(run["total_cost_usd"] or 0) for run in runs)
                if running_cost >= args.maximum_cost_usd and len(runs) < len(cases):
                    stopped_reason = "cost_cap_reached"
                    break
    except SafeLiveSmokeError as error:
        raise SystemExit(
            f"preflight failed safely: stage={error.stage}, type={error.error_type}"
        ) from None
    except httpx.HTTPError as error:
        raise SystemExit(
            f"preflight transport failed: {type(error).__name__}"
        ) from None
    finally:
        trace_reader.close()

    summary = build_live_summary(
        runs,
        planned_case_count=len(cases),
        maximum_cost_usd=args.maximum_cost_usd,
        stopped_reason=stopped_reason,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_live_smoke_v1"
    )
    config = {
        "protocol_version": LIVE_PROTOCOL_VERSION,
        "protocol_status": LIVE_PROTOCOL_STATUS,
        "run_id": run_id,
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_value("status", "--porcelain")),
        "api_base_url": api_base_url,
        "langfuse_environment": environment,
        "timeout_seconds": args.timeout_seconds,
        "trace_wait_seconds": args.trace_wait_seconds,
        "maximum_cost_usd": args.maximum_cost_usd,
        "reference_object_configured": True,
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
    print(f"Results: {output_dir.relative_to(PROJECT_ROOT)}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.fail_on_gate and not summary["acceptance_gates"]["overall"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
