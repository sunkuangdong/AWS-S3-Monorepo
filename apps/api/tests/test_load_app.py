import asyncio
from concurrent.futures import ThreadPoolExecutor

from evals.load_app import (
    app,
    image_generation_stub,
    storage_stub,
    vision_stub,
)
from evals.load_stubs import (
    DeterministicImageGenerationStub,
    DeterministicStorageStub,
    DeterministicVisionStub,
)
from fastapi.testclient import TestClient

from app.dependencies import (
    get_openai_image_generation_client,
    get_openai_vision_client,
    get_s3_storage_client,
)
from app.main import app as production_app


def test_load_app_overrides_only_external_clients() -> None:
    assert production_app.dependency_overrides == {}
    assert app.dependency_overrides[get_s3_storage_client]() is storage_stub
    assert app.dependency_overrides[get_openai_vision_client]() is vision_stub
    assert (
        app.dependency_overrides[get_openai_image_generation_client]()
        is image_generation_stub
    )

    with TestClient(app) as client:
        response = client.get("/load-test/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["load_test"] is True
    assert payload["cloud_calls_enabled"] is False
    assert payload["langfuse_tracing_enabled"] is False
    assert payload["real_postgresql_enabled"] is True
    assert all(
        stub["provider"] == "stub" and stub["network_enabled"] is False
        for stub in payload["stubs"].values()
    )


def test_storage_stub_assigns_unique_keys_under_worker_thread_concurrency() -> None:
    storage = DeterministicStorageStub()

    with ThreadPoolExecutor(max_workers=16) as executor:
        object_keys = list(
            executor.map(
                lambda _: storage.upload_generated_image(image_bytes=b"image"),
                range(100),
            )
        )

    assert len(object_keys) == 100
    assert len(set(object_keys)) == 100
    assert storage.snapshot()["generated_object_count"] == 100
    assert storage.snapshot()["calls"] == {"upload_generated_image": 100}


def test_model_stubs_are_deterministic_and_track_only_counts() -> None:
    vision = DeterministicVisionStub(delay_ms=0)
    image_generation = DeterministicImageGenerationStub(delay_ms=0)

    async def exercise() -> tuple[str, bytes, bytes]:
        description = await vision.analyze_image(
            "https://load-test.invalid/reference.png",
            "describe",
        )
        generated = await image_generation.generate_image(
            prompt="generate",
            width=1024,
            height=1024,
        )
        edited = await image_generation.edit_image(
            image_bytes=b"reference",
            file_name="reference.png",
            content_type="image/png",
            prompt="edit",
            width=1024,
            height=1024,
        )
        return description, generated, edited

    first = asyncio.run(exercise())
    second = asyncio.run(exercise())

    assert first == second
    assert vision.snapshot()["calls"] == {"analyze_image": 2}
    assert image_generation.snapshot()["calls"] == {
        "edit_image": 2,
        "generate_image": 2,
    }
