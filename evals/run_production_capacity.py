"""Run a bounded real-dependency production-capacity evaluation.

This runner intentionally does not reuse the local Capacity v1-v3 runners. It
uses an open arrival rate, real PostgreSQL/S3/OpenAI/Langfuse dependencies, a
pessimistic spend reservation, and explicit human confirmations.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
import httpx
from dotenv import load_dotenv

from evals.dataset import dataset_sha256
from evals.live_smoke import EXPECTED_MODELS
from evals.production_capacity import (
    ProductionCapacityCase,
    StageSpec,
    build_summary,
    latency_summary,
    load_cases,
    parse_stage,
    resource_summary,
)
from evals.run_live_smoke import (
    API_ENV_FILE,
    SafeLiveSmokeError,
    TraceReader,
    _preflight_reference_object,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals/datasets/production_capacity_v1.jsonl"
PROTOCOL_PATH = PROJECT_ROOT / "evals/production_capacity_protocol_v1.json"
DEFAULT_STAGES = (
    "ramp:0.5-1:4",
    "steady:1:6",
    "spike:2:4",
    "soak:1:10",
)
GENERATION_PREFIX = "generations/"


class ProductionCapacityError(RuntimeError):
    """A sanitized capacity-test failure safe to persist."""

    def __init__(self, stage: str, error_type: str, status_code: int | None = None):
        super().__init__(stage)
        self.stage = stage
        self.error_type = error_type
        self.status_code = status_code


def _load_default_environment(env_file: Path = API_ENV_FILE) -> None:
    """Load local defaults without replacing an explicitly selected target."""
    load_dotenv(env_file, override=False)


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


def _safe_ref(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _validated_url(value: str, *, expected_host: str, name: str) -> str:
    url = httpx.URL(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(f"{name} must be a plain HTTP(S) URL without credentials")
    if url.host != expected_host:
        raise ValueError(f"{name} host does not match --expected-api-host")
    if url.scheme != "https" and url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"{name} must use HTTPS for a non-loopback target")
    return str(url).rstrip("/")


def _validated_metrics_url(value: str | None) -> str | None:
    if value is None:
        return None
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("metrics URL must not contain credentials, query, or fragment")
    if parts.scheme != "https" and parts.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("metrics URL must use HTTPS for a non-loopback target")
    return value.rstrip("/")


def _authorization_headers(environment_name: str) -> dict[str, str]:
    value = os.getenv(environment_name, "").strip()
    return {"Authorization": value} if value else {}


def _response_dict(
    response: httpx.Response,
    *,
    stage: str,
    expected_status: int,
) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise ProductionCapacityError(
            stage,
            "UnexpectedHTTPStatus",
            response.status_code,
        )
    try:
        payload = response.json()
    except ValueError:
        raise ProductionCapacityError(
            stage,
            "InvalidJSON",
            response.status_code,
        ) from None
    if not isinstance(payload, dict):
        raise ProductionCapacityError(
            stage,
            "UnexpectedResponseShape",
            response.status_code,
        )
    return payload


def _tracking_token(run_id: str, sequence: int) -> str:
    return f"PCAP-{run_id}-{sequence:04d}"


def _request_prompt(case: ProductionCapacityCase, token: str) -> str:
    prompt = f"{case.prompt} Do not render this evaluation token: {token}."
    if len(prompt) > 400:
        raise ValueError("tracked prompt exceeds the API's 400-character limit")
    return prompt


def _sanitize_run(run: dict[str, Any]) -> dict[str, Any]:
    """Remove correlation IDs, object keys, URLs, and prompts from artifacts."""
    return {
        key: value
        for key, value in run.items()
        if not key.startswith("_")
    }


def _metrics_payload(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        raise ProductionCapacityError("resource_metrics", "UnexpectedResponseShape")
    required = (
        "cpu_percent",
        "memory_percent",
        "database_active_connections",
        "database_max_connections",
    )
    result: dict[str, float] = {}
    for name in required:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProductionCapacityError("resource_metrics", f"Invalid_{name}")
        result[name] = float(value)
    if not 0 <= result["cpu_percent"] <= 100:
        raise ProductionCapacityError("resource_metrics", "Invalid_cpu_percent")
    if not 0 <= result["memory_percent"] <= 100:
        raise ProductionCapacityError("resource_metrics", "Invalid_memory_percent")
    if result["database_active_connections"] < 0:
        raise ProductionCapacityError(
            "resource_metrics", "Invalid_database_active_connections"
        )
    if result["database_max_connections"] <= 0:
        raise ProductionCapacityError(
            "resource_metrics", "Invalid_database_max_connections"
        )
    return result


class MetricsSampler:
    """Poll a user-supplied, bounded numeric metrics endpoint."""

    def __init__(
        self,
        *,
        url: str | None,
        interval_seconds: float,
        headers: dict[str, str],
        maximum_cpu_percent: float,
        maximum_memory_percent: float,
        maximum_database_connection_percent: float,
    ) -> None:
        self.url = url
        self.interval_seconds = interval_seconds
        self.headers = headers
        self.samples: list[dict[str, float]] = []
        self.error_type: str | None = None
        self.breach_reason: str | None = None
        self.maximum_cpu_percent = maximum_cpu_percent
        self.maximum_memory_percent = maximum_memory_percent
        self.maximum_database_connection_percent = (
            maximum_database_connection_percent
        )
        self._stop = asyncio.Event()

    async def sample_once(self) -> dict[str, float] | None:
        if self.url is None:
            return None
        try:
            async with httpx.AsyncClient(timeout=10, headers=self.headers) as client:
                response = await client.get(self.url)
            if response.status_code != 200:
                raise ProductionCapacityError(
                    "resource_metrics",
                    "UnexpectedHTTPStatus",
                    response.status_code,
                )
            sample = _metrics_payload(response.json())
            self.samples.append(sample)
            database_percent = (
                sample["database_active_connections"]
                / sample["database_max_connections"]
                * 100
            )
            if sample["cpu_percent"] > self.maximum_cpu_percent:
                self.breach_reason = "cpu_limit_exceeded"
            elif sample["memory_percent"] > self.maximum_memory_percent:
                self.breach_reason = "memory_limit_exceeded"
            elif database_percent > self.maximum_database_connection_percent:
                self.breach_reason = "database_connection_limit_exceeded"
            return sample
        except ProductionCapacityError as error:
            self.error_type = error.error_type
            return None
        except (httpx.HTTPError, ValueError) as error:
            self.error_type = type(error).__name__
            return None

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.sample_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.interval_seconds,
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()


def _enforce_resource_metrics_preflight(
    sample: dict[str, float] | None,
    *,
    required: bool,
    error_type: str | None,
) -> None:
    if sample is None and required:
        raise ProductionCapacityError(
            "resource_metrics",
            error_type or "Unavailable",
        )


class InFlightTracker:
    def __init__(self) -> None:
        self.current = 0
        self.maximum = 0
        self._lock = asyncio.Lock()

    async def enter(self) -> int:
        async with self._lock:
            self.current += 1
            self.maximum = max(self.maximum, self.current)
            return self.current

    async def leave(self) -> None:
        async with self._lock:
            self.current -= 1


async def _execute_request(
    *,
    api_client: httpx.AsyncClient,
    download_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    tracker: InFlightTracker,
    case: ProductionCapacityCase,
    run_id: str,
    sequence: int,
    stage_name: str,
    scheduled_at: float,
    reference_object_key: str,
) -> dict[str, Any]:
    token = _tracking_token(run_id, sequence)
    result: dict[str, Any] = {
        "sequence": sequence,
        "stage": stage_name,
        "generation_type": case.generation_type,
        "api_completed": False,
        "database_verified": False,
        "database_record_found": False,
        "s3_verified": False,
        "trace_found": False,
        "trace_complete": False,
        "privacy_safe": False,
        "cost_measured": False,
        "total_cost_usd": None,
        "model_names": [],
        "http_status": None,
        "error_stage": None,
        "error_type": None,
        "dispatch_lag_ms": 0.0,
        "api_latency_ms": 0.0,
        "verification_latency_ms": 0.0,
        "_tracking_token": token,
        "_generation_id": None,
        "_output_object_key": None,
    }
    async with semaphore:
        result["dispatch_lag_ms"] = round(
            max(0.0, time.monotonic() - scheduled_at) * 1000,
            3,
        )
        result["in_flight_at_start"] = await tracker.enter()
        api_started = time.perf_counter()
        try:
            payload: dict[str, Any] = {
                "prompt": _request_prompt(case, token),
                "width": 1024,
                "height": 1024,
            }
            if case.generation_type == "image_to_image":
                payload["input_object_key"] = reference_object_key
            response = await api_client.post(
                "/api/v1/images/generations",
                json=payload,
                headers={"X-Request-ID": f"{run_id}-{sequence:04d}"},
            )
            result["http_status"] = response.status_code
            result["api_latency_ms"] = round(
                (time.perf_counter() - api_started) * 1000,
                3,
            )
            created = _response_dict(
                response,
                stage="create_generation",
                expected_status=201,
            )
            generation_id = str(created.get("id") or "")
            output_key = str(created.get("output_object_key") or "")
            if not (
                generation_id
                and created.get("status") == "completed"
                and created.get("generation_type") == case.generation_type
                and output_key.startswith(GENERATION_PREFIX)
            ):
                raise ProductionCapacityError(
                    "create_generation",
                    "UnexpectedCompletedState",
                    201,
                )
            result["api_completed"] = True
            result["_generation_id"] = generation_id
            result["_output_object_key"] = output_key

            verification_started = time.perf_counter()
            persisted = _response_dict(
                await api_client.get(f"/api/v1/images/generations/{generation_id}"),
                stage="database_readback",
                expected_status=200,
            )
            if not (
                str(persisted.get("id")) == generation_id
                and persisted.get("status") == "completed"
                and persisted.get("generation_type") == case.generation_type
                and persisted.get("output_object_key") == output_key
            ):
                raise ProductionCapacityError(
                    "database_readback", "InconsistentState", 200
                )
            result["database_verified"] = True
            result["database_record_found"] = True

            download = _response_dict(
                await api_client.get(
                    f"/api/v1/images/generations/{generation_id}/download"
                ),
                stage="download_signing",
                expected_status=200,
            )
            download_url = str(download.get("download_url") or "")
            if not download_url.startswith("https://"):
                raise ProductionCapacityError(
                    "download_signing", "InvalidDownloadURL", 200
                )
            s3_response = await download_client.get(
                download_url,
                headers={"Range": "bytes=0-0"},
            )
            if s3_response.status_code not in {200, 206}:
                raise ProductionCapacityError(
                    "s3_output",
                    "UnexpectedHTTPStatus",
                    s3_response.status_code,
                )
            if not s3_response.headers.get("content-type", "").startswith("image/"):
                raise ProductionCapacityError(
                    "s3_output", "InvalidContentType", s3_response.status_code
                )
            if not s3_response.content:
                raise ProductionCapacityError(
                    "s3_output", "EmptyObject", s3_response.status_code
                )
            result["s3_verified"] = True
            result["verification_latency_ms"] = round(
                (time.perf_counter() - verification_started) * 1000,
                3,
            )
        except ProductionCapacityError as error:
            result["error_stage"] = error.stage
            result["error_type"] = error.error_type
            result["http_status"] = error.status_code or result["http_status"]
            if result["api_latency_ms"] == 0.0:
                result["api_latency_ms"] = round(
                    (time.perf_counter() - api_started) * 1000,
                    3,
                )
        except httpx.HTTPError as error:
            result["error_stage"] = "transport"
            result["error_type"] = type(error).__name__
            result["api_latency_ms"] = round(
                (time.perf_counter() - api_started) * 1000,
                3,
            )
        finally:
            await tracker.leave()
    return result


async def _run_stage(
    *,
    spec: StageSpec,
    api_client: httpx.AsyncClient,
    download_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    tracker: InFlightTracker,
    cases: list[ProductionCapacityCase],
    run_id: str,
    first_sequence: int,
    reference_object_key: str,
    deadline: float,
    metrics_sampler: MetricsSampler,
    maximum_stage_error_rate: float,
) -> tuple[list[dict[str, Any]], str | None]:
    stage_started = time.monotonic()
    due = stage_started
    tasks: list[asyncio.Task[dict[str, Any]]] = []
    stopped_reason: str | None = None
    for offset, rate in enumerate(spec.rates()):
        if time.monotonic() >= deadline:
            stopped_reason = "duration_cap_reached"
            break
        if metrics_sampler.breach_reason:
            stopped_reason = metrics_sampler.breach_reason
            break
        completed = [task.result() for task in tasks if task.done()]
        if completed:
            error_rate = (
                sum(not run["api_completed"] for run in completed)
                / len(completed)
            )
            if error_rate > maximum_stage_error_rate:
                stopped_reason = "stage_error_rate_exceeded"
                break
        sleep_seconds = max(0.0, due - time.monotonic())
        remaining_seconds = deadline - time.monotonic()
        if sleep_seconds > remaining_seconds:
            await asyncio.sleep(max(0.0, remaining_seconds))
            stopped_reason = "duration_cap_reached"
            break
        await asyncio.sleep(sleep_seconds)
        if metrics_sampler.breach_reason:
            stopped_reason = metrics_sampler.breach_reason
            break
        sequence = first_sequence + offset
        case = cases[(sequence - 1) % len(cases)]
        tasks.append(
            asyncio.create_task(
                _execute_request(
                    api_client=api_client,
                    download_client=download_client,
                    semaphore=semaphore,
                    tracker=tracker,
                    case=case,
                    run_id=run_id,
                    sequence=sequence,
                    stage_name=spec.name,
                    scheduled_at=due,
                    reference_object_key=reference_object_key,
                )
            )
        )
        due += 60.0 / rate
    results = await asyncio.gather(*tasks) if tasks else []
    return results, stopped_reason


def _parse_created_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


async def _scan_recent_records(
    client: httpx.AsyncClient,
    *,
    run_id: str,
    started_at: datetime,
    dispatched_count: int,
) -> dict[str, Any]:
    matching: dict[int, list[dict[str, Any]]] = {
        sequence: [] for sequence in range(1, dispatched_count + 1)
    }
    recent_output_keys: set[str] = set()
    offset = 0
    reached_older_record = False
    while offset < 10_000 and not reached_older_record:
        payload = _response_dict(
            await client.get(
                "/api/v1/images/generations",
                params={"limit": 100, "offset": offset},
            ),
            stage="database_scan",
            expected_status=200,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ProductionCapacityError("database_scan", "UnexpectedResponseShape")
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            created_at = _parse_created_at(item.get("created_at"))
            if created_at is not None and created_at < started_at - timedelta(seconds=5):
                reached_older_record = True
                continue
            output_key = item.get("output_object_key")
            if isinstance(output_key, str) and output_key.startswith(GENERATION_PREFIX):
                recent_output_keys.add(output_key)
            prompt = item.get("user_prompt")
            if not isinstance(prompt, str):
                continue
            for sequence in range(1, dispatched_count + 1):
                if _tracking_token(run_id, sequence) in prompt:
                    matching[sequence].append(item)
                    break
        offset += len(items)
        if len(items) < 100:
            break

    missing = [sequence for sequence, records in matching.items() if not records]
    duplicates = sum(max(0, len(records) - 1) for records in matching.values())
    status_counts = Counter(
        str(record.get("status"))
        for records in matching.values()
        for record in records
    )
    return {
        "matching": matching,
        "recent_output_keys": recent_output_keys,
        "summary": {
            "expected_record_count": dispatched_count,
            "record_count": sum(len(records) for records in matching.values()),
            "missing_count": len(missing),
            "duplicate_count": duplicates,
            "unexpected_pending_count": status_counts.get("pending", 0),
            "status_counts": dict(sorted(status_counts.items())),
            "scan_page_limit_reached": offset >= 10_000,
        },
    }


def _list_s3_objects(
    *,
    started_at: datetime,
    finished_at: datetime,
) -> set[str]:
    bucket = os.getenv("S3_BUCKET", "").strip()
    region = os.getenv("AWS_DEFAULT_REGION", "").strip()
    client = boto3.client("s3", region_name=region)
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=GENERATION_PREFIX):
        for item in page.get("Contents", []):
            modified = item.get("LastModified")
            key = item.get("Key")
            if (
                isinstance(modified, datetime)
                and isinstance(key, str)
                and started_at - timedelta(seconds=5)
                <= modified.astimezone(UTC)
                <= finished_at + timedelta(seconds=5)
            ):
                keys.add(key)
    return keys


def _trace_for_record(
    *,
    environment: str,
    wait_seconds: int,
    generation_id: str,
    generation_type: str,
    started_at: datetime,
) -> dict[str, Any]:
    reader = TraceReader(environment=environment, wait_seconds=wait_seconds)
    try:
        return reader.collect(
            generation_id=generation_id,
            generation_type=generation_type,
            started_at=started_at,
        )
    finally:
        reader.close()


async def _attach_database_and_trace_results(
    runs: list[dict[str, Any]],
    *,
    scan: dict[str, Any],
    environment: str,
    wait_seconds: int,
    started_at: datetime,
) -> None:
    for run in runs:
        records = scan["matching"].get(run["sequence"], [])
        run["database_record_found"] = len(records) == 1
        if len(records) != 1:
            continue
        record = records[0]
        generation_id = str(record.get("id") or "")
        generation_type = str(record.get("generation_type") or "")
        run["_generation_id"] = generation_id or run.get("_generation_id")
        output_key = record.get("output_object_key")
        if isinstance(output_key, str):
            run["_output_object_key"] = output_key
        run["database_verified"] = (
            record.get("status") in {"completed", "failed"}
            and generation_type == run["generation_type"]
        )
        if not generation_id or (
            run.get("trace_complete")
            and run.get("privacy_safe")
            and run.get("cost_measured")
        ):
            continue
        trace = await asyncio.to_thread(
            _trace_for_record,
            environment=environment,
            wait_seconds=wait_seconds,
            generation_id=generation_id,
            generation_type=generation_type,
            started_at=started_at,
        )
        run.update(
            {
                "trace_found": trace.get("trace_found", False),
                "trace_complete": trace.get("trace_complete", False),
                "privacy_safe": trace.get("privacy_safe", False),
                "cost_measured": trace.get("cost_measured", False),
                "total_cost_usd": trace.get("total_cost_usd"),
                "model_names": trace.get("model_names", []),
                "model_compliant": set(trace.get("model_names", []))
                == EXPECTED_MODELS.get(generation_type, set()),
                "trace_ref": _safe_ref(trace.get("trace_id")),
            }
        )


async def _preflight(
    *,
    api_client: httpx.AsyncClient,
    trace_reader: TraceReader,
    reference_object_key: str,
    s3_list_required: bool,
    resource_metrics_required: bool,
    metrics_sampler: MetricsSampler,
) -> dict[str, Any]:
    health = _response_dict(
        await api_client.get("/health/database"),
        stage="database_health",
        expected_status=200,
    )
    if health.get("status") != "ok" or health.get("database") != "reachable":
        raise ProductionCapacityError(
            "database_health", "UnexpectedHealthResponse", 200
        )
    history = await api_client.get(
        "/api/v1/images/generations",
        params={"limit": 1, "offset": 0},
    )
    _response_dict(history, stage="database_scan", expected_status=200)
    try:
        reference = await asyncio.to_thread(
            _preflight_reference_object,
            reference_object_key,
        )
        await asyncio.to_thread(trace_reader.preflight)
    except SafeLiveSmokeError as error:
        raise ProductionCapacityError(error.stage, error.error_type) from None

    s3_list_available = True
    try:
        bucket = os.getenv("S3_BUCKET", "").strip()
        region = os.getenv("AWS_DEFAULT_REGION", "").strip()
        await asyncio.to_thread(
            boto3.client("s3", region_name=region).list_objects_v2,
            Bucket=bucket,
            Prefix=GENERATION_PREFIX,
            MaxKeys=1,
        )
    except Exception as error:  # noqa: BLE001 - provider details must be sanitized
        s3_list_available = False
        if s3_list_required:
            raise ProductionCapacityError(
                "s3_orphan_scan", type(error).__name__
            ) from None

    metric = await metrics_sampler.sample_once()
    _enforce_resource_metrics_preflight(
        metric,
        required=resource_metrics_required,
        error_type=metrics_sampler.error_type,
    )
    return {
        "api_reachable": True,
        "database_reachable": True,
        "history_scan_available": True,
        "reference_object": reference,
        "langfuse_authenticated": True,
        "s3_list_available": s3_list_available,
        "resource_metrics_available": metric is not None,
        "resource_metrics_error_type": metrics_sampler.error_type,
    }


def _stage_summary(
    spec: StageSpec,
    runs: list[dict[str, Any]],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    successes = sum(bool(run["api_completed"]) for run in runs)
    latencies = [float(run["api_latency_ms"]) for run in runs]
    dispatch_lags = [float(run["dispatch_lag_ms"]) for run in runs]
    return {
        "name": spec.name,
        "target_start_rate_jobs_per_minute": spec.start_rate_jpm,
        "target_end_rate_jobs_per_minute": spec.end_rate_jpm,
        "planned_request_count": spec.request_count,
        "run_count": len(runs),
        "completed_count": successes,
        "success_rate": successes / len(runs) if runs else None,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "completion_throughput_jobs_per_minute": (
            round(successes / elapsed_seconds * 60, 3)
            if elapsed_seconds > 0
            else None
        ),
        "maximum_in_flight": max(
            (int(run.get("in_flight_at_start", 0)) for run in runs),
            default=0,
        ),
        "api_latency_ms": latency_summary(latencies),
        "dispatch_lag_ms": latency_summary(dispatch_lags),
        "status_counts": dict(
            sorted(Counter(str(run.get("http_status")) for run in runs).items())
        ),
        "error_type_counts": dict(
            sorted(
                Counter(
                    str(run["error_type"])
                    for run in runs
                    if run.get("error_type")
                ).items()
            )
        ),
    }


def _render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    lines = [
        "# Production Capacity Evaluation",
        "",
        f"- Protocol: `{config['protocol_version']}` ({config['protocol_status']})",
        f"- Target label: `{config['target_environment_label']}`",
        f"- Target host: `{config['target_host']}`",
        f"- Executed/planned: {summary['run_count']}/{summary['planned_request_count']}",
        (
            f"- Measured cost / cap: ${summary['cost_usd']['total']:.6f} / "
            f"${summary['cost_usd']['maximum']:.2f}"
        ),
        f"- Overall gate: `{str(summary['acceptance_gates']['overall']).lower()}`",
        "",
        "## Stages",
        "",
        "| Stage | Target jobs/min | Success | P95 ms | Max in flight |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for stage in summary["stages"]:
        target = (
            f"{stage['target_start_rate_jobs_per_minute']}-"
            f"{stage['target_end_rate_jobs_per_minute']}"
        )
        lines.append(
            f"| {stage['name']} | {target} | {stage['success_rate'] or 0:.1%} | "
            f"{stage['api_latency_ms']['p95_nearest_rank']} | "
            f"{stage['maximum_in_flight']} |"
        )
    lines.extend(
        [
            "",
            "## Acceptance gates",
            "",
            *(
                f"- {name}: `{str(value).lower()}`"
                for name, value in summary["acceptance_gates"].items()
            ),
            "",
            "## Interpretation boundary",
            "",
            summary["claim_boundary"],
            (
                "The runner stores no prompts, object keys, signed URLs, credentials, "
                "generation IDs, or raw trace IDs in its artifacts."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--expected-api-host", required=True)
    parser.add_argument("--target-environment-label", required=True)
    parser.add_argument(
        "--reference-object-key",
        default=os.getenv("LIVE_SMOKE_REFERENCE_OBJECT_KEY"),
    )
    parser.add_argument(
        "--stage",
        action="append",
        dest="stages",
        help="NAME:RATE:COUNT or ramp:START-END:COUNT; may be repeated",
    )
    parser.add_argument("--maximum-in-flight", type=int, default=4)
    parser.add_argument("--maximum-request-count", type=int, default=30)
    parser.add_argument("--maximum-duration-seconds", type=float, default=3600)
    parser.add_argument("--maximum-cost-usd", type=float, default=3.0)
    parser.add_argument(
        "--maximum-reserved-cost-per-request-usd",
        type=float,
        default=0.10,
    )
    parser.add_argument("--minimum-success-rate", type=float, default=0.99)
    parser.add_argument("--maximum-stage-error-rate", type=float, default=0.01)
    parser.add_argument("--request-timeout-seconds", type=float, default=180)
    parser.add_argument("--trace-wait-seconds", type=int, default=30)
    parser.add_argument("--stage-pause-seconds", type=float, default=10)
    parser.add_argument("--metrics-url")
    parser.add_argument("--metrics-sample-interval-seconds", type=float, default=5)
    parser.add_argument("--maximum-cpu-percent", type=float, default=80)
    parser.add_argument("--maximum-memory-percent", type=float, default=80)
    parser.add_argument(
        "--maximum-database-connection-percent",
        type=float,
        default=80,
    )
    parser.add_argument("--allow-missing-resource-metrics", action="store_true")
    parser.add_argument("--allow-missing-orphan-scan", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--confirm-cloud-spend", action="store_true")
    parser.add_argument("--confirm-production-capacity-test", action="store_true")
    parser.add_argument("--confirm-isolated-test-data", action="store_true")
    parser.add_argument("--fail-on-gate", action="store_true")
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> tuple[list[StageSpec], dict[str, Any]]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    limits = protocol["hard_safety_limits"]
    stage_values = args.stages or list(DEFAULT_STAGES)
    stages = [parse_stage(value) for value in stage_values]
    planned_count = sum(stage.request_count for stage in stages)
    if not args.reference_object_key:
        raise ValueError("--reference-object-key is required and never stored")
    if not 0 < args.minimum_success_rate <= 1:
        raise ValueError("minimum success rate must be in (0, 1]")
    if not 0 <= args.maximum_stage_error_rate < 1:
        raise ValueError("maximum stage error rate must be in [0, 1)")
    positive = {
        "maximum request count": args.maximum_request_count,
        "maximum in flight": args.maximum_in_flight,
        "maximum duration": args.maximum_duration_seconds,
        "maximum cost": args.maximum_cost_usd,
        "reserved request cost": args.maximum_reserved_cost_per_request_usd,
        "request timeout": args.request_timeout_seconds,
        "trace wait": args.trace_wait_seconds,
        "metrics interval": args.metrics_sample_interval_seconds,
    }
    if any(value <= 0 for value in positive.values()):
        raise ValueError("all limits and timeouts must be positive")
    if planned_count > args.maximum_request_count:
        raise ValueError("stage plan exceeds --maximum-request-count")
    if planned_count * args.maximum_reserved_cost_per_request_usd > args.maximum_cost_usd:
        raise ValueError("pessimistic request-cost reservation exceeds total cost cap")
    if args.maximum_request_count > limits["maximum_request_count"]:
        raise ValueError("maximum request count exceeds the protocol hard limit")
    if args.maximum_in_flight > limits["maximum_in_flight"]:
        raise ValueError("maximum in-flight count exceeds the protocol hard limit")
    if args.maximum_duration_seconds > limits["maximum_duration_seconds"]:
        raise ValueError("maximum duration exceeds the protocol hard limit")
    if args.maximum_cost_usd > limits["maximum_cost_usd"]:
        raise ValueError("maximum cost exceeds the protocol hard limit")
    if (
        args.maximum_reserved_cost_per_request_usd
        > limits["maximum_reserved_cost_per_request_usd"]
    ):
        raise ValueError("per-request reservation exceeds the protocol hard limit")
    for name in (
        "maximum_cpu_percent",
        "maximum_memory_percent",
        "maximum_database_connection_percent",
    ):
        if not 0 < getattr(args, name) <= 100:
            raise ValueError(f"{name} must be in (0, 100]")
    return stages, protocol


async def _async_main(args: argparse.Namespace) -> int:
    stages, protocol = _validate_args(args)
    dataset_path = args.dataset.resolve()
    cases = load_cases(dataset_path)
    dataset_protocol = protocol["dataset"]
    expected_dataset_path = PROJECT_ROOT / dataset_protocol["path"]
    if dataset_path != expected_dataset_path.resolve():
        raise ValueError("dataset path is outside production capacity v1")
    if dataset_sha256(dataset_path) != dataset_protocol["sha256"]:
        raise ValueError("dataset SHA-256 does not match the reviewed protocol")
    if len(cases) != dataset_protocol["case_count"]:
        raise ValueError("dataset case count does not match the reviewed protocol")
    if [case.case_id for case in cases] != dataset_protocol["case_ids"]:
        raise ValueError("dataset case IDs or order do not match the protocol")
    api_base_url = _validated_url(
        args.api_base_url,
        expected_host=args.expected_api_host,
        name="API base URL",
    )
    metrics_url = _validated_metrics_url(args.metrics_url)
    if metrics_url is None and not args.allow_missing_resource_metrics:
        raise SystemExit(
            "--metrics-url is required unless --allow-missing-resource-metrics is set"
        )
    if not args.validate_only:
        missing = [
            name
            for name, confirmed in {
                "--confirm-cloud-spend": args.confirm_cloud_spend,
                "--confirm-production-capacity-test": (
                    args.confirm_production_capacity_test
                ),
                "--confirm-isolated-test-data": args.confirm_isolated_test_data,
            }.items()
            if not confirmed
        ]
        if missing:
            raise SystemExit("refusing paid capacity test without " + ", ".join(missing))
    if os.getenv("LANGFUSE_TRACING_ENABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise SystemExit("LANGFUSE_TRACING_ENABLED must be true")

    api_headers = _authorization_headers("PRODUCTION_CAPACITY_AUTHORIZATION")
    metrics_headers = _authorization_headers(
        "PRODUCTION_CAPACITY_METRICS_AUTHORIZATION"
    )
    metrics_sampler = MetricsSampler(
        url=metrics_url,
        interval_seconds=args.metrics_sample_interval_seconds,
        headers=metrics_headers,
        maximum_cpu_percent=args.maximum_cpu_percent,
        maximum_memory_percent=args.maximum_memory_percent,
        maximum_database_connection_percent=(
            args.maximum_database_connection_percent
        ),
    )
    environment = os.getenv("LANGFUSE_ENVIRONMENT", "production-capacity")
    trace_reader = TraceReader(environment=environment, wait_seconds=args.trace_wait_seconds)
    timeout = httpx.Timeout(args.request_timeout_seconds)
    async with (
        httpx.AsyncClient(
            base_url=api_base_url,
            timeout=timeout,
            follow_redirects=True,
            headers=api_headers,
        ) as api_client,
        httpx.AsyncClient(timeout=30, follow_redirects=True) as download_client,
    ):
        try:
            preflight = await _preflight(
                api_client=api_client,
                trace_reader=trace_reader,
                reference_object_key=args.reference_object_key,
                s3_list_required=not args.allow_missing_orphan_scan,
                resource_metrics_required=(
                    not args.allow_missing_resource_metrics
                ),
                metrics_sampler=metrics_sampler,
            )
        finally:
            trace_reader.close()

        validation = {
            "valid": True,
            "paid_model_calls": 0,
            "protocol_version": protocol["protocol_version"],
            "protocol_status": protocol["status"],
            "dataset_sha256": dataset_sha256(dataset_path),
            "planned_request_count": sum(stage.request_count for stage in stages),
            "reserved_cost_usd": round(
                sum(stage.request_count for stage in stages)
                * args.maximum_reserved_cost_per_request_usd,
                6,
            ),
            "preflight": preflight,
            "warnings": [
                warning
                for warning, active in {
                    "resource metrics are unavailable; production claim will fail": (
                        not preflight["resource_metrics_available"]
                    ),
                    "S3 orphan scan is unavailable; production claim will fail": (
                        not preflight["s3_list_available"]
                    ),
                    "protocol remains draft until repeated evidence is reviewed": True,
                }.items()
                if active
            ],
        }
        if args.validate_only:
            print(json.dumps(validation, indent=2, ensure_ascii=False))
            return 0

        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        monotonic_started = time.monotonic()
        deadline = monotonic_started + args.maximum_duration_seconds
        semaphore = asyncio.Semaphore(args.maximum_in_flight)
        tracker = InFlightTracker()
        metrics_task = asyncio.create_task(metrics_sampler.run())
        runs: list[dict[str, Any]] = []
        stage_summaries: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        sequence = 1
        try:
            for stage_index, spec in enumerate(stages):
                if time.monotonic() >= deadline:
                    stopped_reason = "duration_cap_reached"
                    break
                stage_started = time.monotonic()
                stage_runs, stage_stop_reason = await _run_stage(
                    spec=spec,
                    api_client=api_client,
                    download_client=download_client,
                    semaphore=semaphore,
                    tracker=tracker,
                    cases=cases,
                    run_id=run_id,
                    first_sequence=sequence,
                    reference_object_key=args.reference_object_key,
                    deadline=deadline,
                    metrics_sampler=metrics_sampler,
                    maximum_stage_error_rate=args.maximum_stage_error_rate,
                )
                sequence += len(stage_runs)
                runs.extend(stage_runs)
                stage_summaries.append(
                    _stage_summary(
                        spec,
                        stage_runs,
                        elapsed_seconds=time.monotonic() - stage_started,
                    )
                )
                stage_scan = await _scan_recent_records(
                    api_client,
                    run_id=run_id,
                    started_at=started_at,
                    dispatched_count=len(runs),
                )
                await _attach_database_and_trace_results(
                    runs,
                    scan=stage_scan,
                    environment=environment,
                    wait_seconds=args.trace_wait_seconds,
                    started_at=started_at,
                )
                running_cost = sum(
                    float(run.get("total_cost_usd") or 0) for run in runs
                )
                if running_cost > args.maximum_cost_usd:
                    stopped_reason = "measured_cost_cap_exceeded"
                    break
                if any(
                    float(run.get("total_cost_usd") or 0)
                    > args.maximum_reserved_cost_per_request_usd
                    for run in runs
                ):
                    stopped_reason = "per_request_cost_reservation_exceeded"
                    break
                recorded_runs = [
                    run for run in runs if run.get("database_record_found")
                ]
                if recorded_runs and any(
                    not run.get("cost_measured") for run in recorded_runs
                ):
                    stopped_reason = "cost_not_measured"
                    break
                if stage_stop_reason:
                    stopped_reason = stage_stop_reason
                    break
                error_rate = (
                    sum(not run["api_completed"] for run in stage_runs)
                    / len(stage_runs)
                    if stage_runs
                    else 1.0
                )
                if error_rate > args.maximum_stage_error_rate:
                    stopped_reason = "stage_error_rate_exceeded"
                    break
                if stage_index < len(stages) - 1:
                    await asyncio.sleep(args.stage_pause_seconds)
        finally:
            metrics_sampler.stop()
            await metrics_task

        finished_at = datetime.now(UTC)
        scan = await _scan_recent_records(
            api_client,
            run_id=run_id,
            started_at=started_at,
            dispatched_count=len(runs),
        )
        await _attach_database_and_trace_results(
            runs,
            scan=scan,
            environment=environment,
            wait_seconds=args.trace_wait_seconds,
            started_at=started_at,
        )

    measured_cost = sum(float(run.get("total_cost_usd") or 0) for run in runs)
    if measured_cost > args.maximum_cost_usd and stopped_reason is None:
        stopped_reason = "measured_cost_cap_exceeded"
    if any(
        float(run.get("total_cost_usd") or 0)
        > args.maximum_reserved_cost_per_request_usd
        for run in runs
    ) and stopped_reason is None:
        stopped_reason = "per_request_cost_reservation_exceeded"

    if preflight["s3_list_available"]:
        s3_keys = await asyncio.to_thread(
            _list_s3_objects,
            started_at=started_at,
            finished_at=finished_at,
        )
        orphan_keys = s3_keys - scan["recent_output_keys"]
        orphan_scan = {
            "available": True,
            "window_object_count": len(s3_keys),
            "database_output_count": len(scan["recent_output_keys"]),
            "orphan_output_count": len(orphan_keys),
        }
    else:
        orphan_scan = {
            "available": False,
            "window_object_count": None,
            "database_output_count": None,
            "orphan_output_count": None,
        }

    resources = resource_summary(metrics_sampler.samples)
    if metrics_sampler.error_type:
        resources["last_error_type"] = metrics_sampler.error_type
    summary = build_summary(
        runs,
        stages=stage_summaries,
        planned_count=sum(stage.request_count for stage in stages),
        maximum_cost_usd=args.maximum_cost_usd,
        minimum_success_rate=args.minimum_success_rate,
        database_scan=scan["summary"],
        orphan_scan=orphan_scan,
        resources=resources,
        maximum_cpu_percent=args.maximum_cpu_percent,
        maximum_memory_percent=args.maximum_memory_percent,
        maximum_database_connection_percent=(
            args.maximum_database_connection_percent
        ),
        stopped_reason=stopped_reason,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else PROJECT_ROOT / "evals/results" / f"{timestamp}_production_capacity_v1"
    )
    target_host = httpx.URL(api_base_url).host
    config = {
        "protocol_version": protocol["protocol_version"],
        "protocol_status": protocol["status"],
        "run_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_value("status", "--porcelain")),
        "target_environment_label": args.target_environment_label,
        "target_host": target_host,
        "api_transport": httpx.URL(api_base_url).scheme,
        "authentication_configured": bool(api_headers),
        "metrics_authentication_configured": bool(metrics_headers),
        "langfuse_environment": environment,
        "dataset": {
            "path": str(dataset_path.relative_to(PROJECT_ROOT)),
            "sha256": dataset_sha256(dataset_path),
            "case_count": len(cases),
            "generation_types": sorted(
                {case.generation_type for case in cases}
            ),
        },
        "stages": [
            {
                "name": stage.name,
                "start_rate_jobs_per_minute": stage.start_rate_jpm,
                "end_rate_jobs_per_minute": stage.end_rate_jpm,
                "request_count": stage.request_count,
            }
            for stage in stages
        ],
        "safety": {
            "maximum_in_flight": args.maximum_in_flight,
            "maximum_request_count": args.maximum_request_count,
            "maximum_duration_seconds": args.maximum_duration_seconds,
            "maximum_cost_usd": args.maximum_cost_usd,
            "maximum_reserved_cost_per_request_usd": (
                args.maximum_reserved_cost_per_request_usd
            ),
            "maximum_stage_error_rate": args.maximum_stage_error_rate,
            "explicit_cloud_spend_confirmation": True,
            "explicit_target_confirmation": True,
            "explicit_isolation_confirmation": True,
        },
        "privacy": {
            "prompts_persisted": False,
            "object_keys_persisted": False,
            "signed_urls_persisted": False,
            "credentials_persisted": False,
            "generation_ids_persisted": False,
            "raw_trace_ids_persisted": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "raw_runs.jsonl").write_text(
        "".join(
            json.dumps(_sanitize_run(run), ensure_ascii=False) + "\n"
            for run in runs
        ),
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


def main() -> int:
    _load_default_environment()
    args = _parse_args()
    try:
        return asyncio.run(_async_main(args))
    except (ProductionCapacityError, ValueError) as error:
        if isinstance(error, ProductionCapacityError):
            message = f"stage={error.stage}, type={error.error_type}"
        else:
            message = str(error)
        raise SystemExit(f"production capacity evaluation failed safely: {message}") from None


if __name__ == "__main__":
    raise SystemExit(main())
