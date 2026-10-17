from typing import Annotated
from unittest.mock import Mock

from fastapi import Depends, FastAPI
from fastapi.dependencies.utils import get_dependant
from fastapi.testclient import TestClient

from app.dependencies import (
    get_image_generation_repository,
    get_image_service,
    get_openai_image_generation_client,
    get_openai_vision_client,
    get_s3_storage_client,
)
from app.services.image_service import ImageService


def test_image_service_declares_all_runtime_dependencies() -> None:
    dependant = get_dependant(path="/", call=get_image_service)
    dependency_calls = {dependency.call for dependency in dependant.dependencies}

    assert dependency_calls == {
        get_image_generation_repository,
        get_s3_storage_client,
        get_openai_vision_client,
        get_openai_image_generation_client,
    }


def test_external_clients_can_be_overridden_without_replacing_service() -> None:
    repository = Mock(name="repository")
    storage = Mock(name="storage")
    vision = Mock(name="vision")
    image_generation = Mock(name="image_generation")
    test_app = FastAPI()

    @test_app.get("/dependency-check")
    def dependency_check(
        service: Annotated[ImageService, Depends(get_image_service)],
    ) -> dict[str, bool]:
        return {
            "service_is_real": type(service) is ImageService,
            "repository_injected": service.generation_repository is repository,
            "storage_injected": service.storage_client is storage,
            "vision_injected": service.vision_client is vision,
            "image_generation_injected": (
                service.image_generation_client is image_generation
            ),
        }

    test_app.dependency_overrides[get_image_generation_repository] = lambda: repository
    test_app.dependency_overrides[get_s3_storage_client] = lambda: storage
    test_app.dependency_overrides[get_openai_vision_client] = lambda: vision
    test_app.dependency_overrides[get_openai_image_generation_client] = (
        lambda: image_generation
    )

    with TestClient(test_app) as client:
        response = client.get("/dependency-check")

    assert response.status_code == 200
    assert response.json() == {
        "service_is_real": True,
        "repository_injected": True,
        "storage_injected": True,
        "vision_injected": True,
        "image_generation_injected": True,
    }
