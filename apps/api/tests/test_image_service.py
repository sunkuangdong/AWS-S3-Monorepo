from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.core.exceptions import ImageGenerationError, InvalidObjectKeyError
from app.models.image_generation import ImageGeneration
from app.schemas.image_generation import CreateImageGenerationRequest
from app.services.image_service import ImageService


def _mark_completed(
    generation: ImageGeneration,
    *,
    image_analysis: str | None,
    final_prompt: str,
    output_object_key: str,
) -> ImageGeneration:
    generation.image_analysis = image_analysis
    generation.final_prompt = final_prompt
    generation.output_object_key = output_object_key
    generation.status = "completed"
    return generation


def build_service() -> tuple[ImageService, Mock, AsyncMock, AsyncMock, AsyncMock]:
    storage = Mock()
    storage.settings = SimpleNamespace(presigned_url_expires=600)
    storage.upload_generated_image.return_value = "generated/result.png"
    storage.create_presigned_download_url.return_value = "https://example.test/result.png"

    vision = AsyncMock()
    image_generation = AsyncMock()
    image_generation.generate_image.return_value = b"generated-image"
    repository = AsyncMock()

    async def create(generation: ImageGeneration) -> ImageGeneration:
        generation.id = uuid4()
        generation.created_at = datetime.now(UTC)
        return generation

    repository.create.side_effect = create
    repository.mark_completed.side_effect = (
        lambda generation, **updates: _mark_completed(generation, **updates)
    )

    return (
        ImageService(storage, vision, image_generation, repository),
        storage,
        vision,
        image_generation,
        repository,
    )


@pytest.mark.parametrize(
    "object_key",
    ["private/image.png", "uploads/", "uploads/../private/image.png"],
)
def test_validate_object_key_rejects_unsafe_paths(object_key: str) -> None:
    with pytest.raises(InvalidObjectKeyError):
        ImageService.validate_object_key(object_key)


def test_validate_object_key_accepts_upload_path() -> None:
    ImageService.validate_object_key("uploads/2026/reference.png")


@pytest.mark.anyio
async def test_create_text_generation_completes_workflow() -> None:
    service, storage, vision, image_generation, repository = build_service()

    result = await service.create_generation(
        CreateImageGenerationRequest(prompt="A lighthouse in a storm")
    )

    assert result.status == "completed"
    assert result.generation_type == "text_to_image"
    assert result.output_object_key == "generated/result.png"
    assert result.output_url == "https://example.test/result.png"
    image_generation.generate_image.assert_awaited_once_with(
        prompt="A lighthouse in a storm",
        width=1024,
        height=1024,
    )
    vision.analyze_image.assert_not_awaited()
    storage.upload_generated_image.assert_called_once_with(
        image_bytes=b"generated-image"
    )
    assert repository.commit.await_count == 2


@pytest.mark.anyio
async def test_reference_image_uses_vision_and_editing_workflow() -> None:
    service, storage, vision, image_generation, _ = build_service()
    vision.analyze_image.return_value = "A tabby cat by a window"
    storage.download_image.return_value = SimpleNamespace(
        data=b"reference-image",
        file_name="cat.png",
        content_type="image/png",
    )
    image_generation.edit_image.return_value = b"edited-image"

    result = await service.create_generation(
        CreateImageGenerationRequest(
            prompt="Change the weather to snow",
            input_object_key="uploads/cat.png",
        )
    )

    assert result.status == "completed"
    assert result.generation_type == "image_to_image"
    assert result.image_analysis == "A tabby cat by a window"
    vision.analyze_image.assert_awaited_once()
    storage.download_image.assert_called_once_with(object_key="uploads/cat.png")
    edit_call = image_generation.edit_image.await_args.kwargs
    assert edit_call["image_bytes"] == b"reference-image"
    assert "Change the weather to snow" in edit_call["prompt"]
    assert "A tabby cat by a window" in edit_call["prompt"]


@pytest.mark.anyio
async def test_failed_generation_is_persisted_as_failed() -> None:
    service, _, _, image_generation, repository = build_service()
    image_generation.generate_image.side_effect = ImageGenerationError("provider failed")

    async def get_by_id(generation_id):
        return ImageGeneration(
            id=generation_id,
            user_prompt="A lighthouse",
            final_prompt="A lighthouse",
            generation_type="text_to_image",
            width=1024,
            height=1024,
            status="pending",
            created_at=datetime.now(UTC),
        )

    repository.get_by_id.side_effect = get_by_id

    with pytest.raises(ImageGenerationError):
        await service.create_generation(
            CreateImageGenerationRequest(prompt="A lighthouse")
        )

    repository.rollback.assert_awaited_once()
    repository.mark_failed.assert_awaited_once()
    assert repository.commit.await_count == 2
