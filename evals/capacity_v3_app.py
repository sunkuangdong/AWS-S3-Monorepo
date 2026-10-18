"""Network-free FastAPI application for the Capacity v3 pool experiment."""

from __future__ import annotations

import os
import re

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.api.router import api_router
from app.db.session import engine, settings
from app.dependencies import (
    get_openai_image_generation_client,
    get_openai_vision_client,
    get_s3_storage_client,
)
from app.main import (
    database_health_check,
    health_check,
    lifespan,
    request_observability,
)
from app.models.image_generation import ImageGeneration
from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from evals.capacity_metrics import collect_capacity_metrics
from evals.capacity_v3_protocol import (
    CAPACITY_V3_PROTOCOL_STATUS,
    CAPACITY_V3_PROTOCOL_VERSION,
)
from evals.load_stubs import (
    DeterministicImageGenerationStub,
    DeterministicStorageStub,
    DeterministicVisionStub,
)


def _non_negative_delay(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value < 0:
        raise RuntimeError(f"{name} must be non-negative")
    return value


storage_stub = DeterministicStorageStub(
    delay_ms=_non_negative_delay("CAPACITY_V3_STUB_STORAGE_DELAY_MS", 0),
)
vision_stub = DeterministicVisionStub(
    delay_ms=_non_negative_delay("CAPACITY_V3_STUB_VISION_DELAY_MS", 50),
)
image_generation_stub = DeterministicImageGenerationStub(
    delay_ms=_non_negative_delay("CAPACITY_V3_STUB_IMAGE_DELAY_MS", 250),
)

CAPACITY_V3_RUN_ID_PATTERN = re.compile(
    r"^capacity-v3-\d{8}T\d{6}Z-[0-9a-f]{8}$"
)

app = FastAPI(
    title="AI Image API - Capacity v3 Pool Experiment",
    version=f"{CAPACITY_V3_PROTOCOL_VERSION}-{CAPACITY_V3_PROTOCOL_STATUS}",
    lifespan=lifespan,
)
app.middleware("http")(request_observability)
app.include_router(api_router)
app.add_api_route("/health", health_check, methods=["GET"], response_model=dict[str, str])
app.add_api_route(
    "/health/database",
    database_health_check,
    methods=["GET"],
    response_model=dict[str, str],
)

app.dependency_overrides[get_s3_storage_client] = lambda: storage_stub
app.dependency_overrides[get_openai_vision_client] = lambda: vision_stub
app.dependency_overrides[get_openai_image_generation_client] = (
    lambda: image_generation_stub
)


@app.get("/capacity-v3-test/status", include_in_schema=False)
def capacity_v3_test_status() -> dict[str, object]:
    return {
        "capacity_v3_test": True,
        "protocol_version": CAPACITY_V3_PROTOCOL_VERSION,
        "protocol_status": CAPACITY_V3_PROTOCOL_STATUS,
        "cloud_calls_enabled": False,
        "langfuse_tracing_enabled": False,
        "real_postgresql_enabled": True,
        "database_pool": {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "timeout_seconds": settings.database_pool_timeout_seconds,
        },
        "stubs": {
            "storage": storage_stub.snapshot(),
            "vision": vision_stub.snapshot(),
            "image_generation": image_generation_stub.snapshot(),
        },
    }


@app.get("/capacity-v3-test/metrics", include_in_schema=False)
async def capacity_v3_test_metrics() -> dict[str, object]:
    return await collect_capacity_metrics(
        engine,
        application_name="capacity-v3-api",
    )


@app.get("/capacity-v3-test/records", include_in_schema=False)
async def capacity_v3_test_records(run_id: str) -> dict[str, object]:
    if CAPACITY_V3_RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise HTTPException(status_code=422, detail="invalid Capacity v3 run ID")
    statement = (
        select(
            ImageGeneration.id,
            ImageGeneration.status,
            ImageGeneration.generation_type,
            ImageGeneration.output_object_key.is_not(None).label("output_present"),
        )
        .where(
            ImageGeneration.user_prompt.startswith(f"load-eval:{run_id}:"),
            ImageGeneration.deleted_at.is_(None),
        )
        .order_by(ImageGeneration.id)
    )
    async with engine.connect() as connection:
        rows = (await connection.execute(statement)).mappings().all()
    return {
        "run_id": run_id,
        "records": [
            {
                "id": str(row["id"]),
                "status": row["status"],
                "generation_type": row["generation_type"],
                "output_present": bool(row["output_present"]),
            }
            for row in rows
        ],
    }
