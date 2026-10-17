from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.clients.s3_storage import S3StorageClient
from app.core.exceptions import StorageError


def build_storage() -> tuple[S3StorageClient, Mock]:
    storage = S3StorageClient.__new__(S3StorageClient)
    client = Mock()
    storage.settings = SimpleNamespace(s3_bucket="test-image-bucket")
    storage.client = client
    return storage, client


def test_delete_generated_image_uses_exact_generated_key() -> None:
    storage, client = build_storage()

    storage.delete_generated_image(object_key="generations/result.png")

    client.delete_object.assert_called_once_with(
        Bucket="test-image-bucket",
        Key="generations/result.png",
    )


@pytest.mark.parametrize(
    "object_key",
    [
        "uploads/reference.png",
        "generations/",
        "generations/../uploads/reference.png",
    ],
)
def test_delete_generated_image_rejects_unsafe_key(object_key: str) -> None:
    storage, client = build_storage()

    with pytest.raises(StorageError):
        storage.delete_generated_image(object_key=object_key)

    client.delete_object.assert_not_called()
