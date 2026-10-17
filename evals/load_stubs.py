"""Deterministic, network-free substitutes used by the load-test application."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any

from app.clients.s3_storage import StoredImage
from app.core.exceptions import StorageError
from app.schemas.image import PresignUploadResponse


@dataclass(frozen=True)
class StubStorageSettings:
    """Only the storage setting consumed by ImageService responses."""

    presigned_url_expires: int = 600


class CallTracker:
    """Keep privacy-safe call counts across async and worker-thread operations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()

    def record(self, operation: str) -> None:
        with self._lock:
            self._counts[operation] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))


class DeterministicStorageStub:
    """Thread-safe in-memory S3 substitute with no boto3 or network access."""

    REFERENCE_OBJECT_KEY = "uploads/load-reference.png"
    REFERENCE_IMAGE_BYTES = b"deterministic-load-reference-image"

    def __init__(self, *, delay_ms: int = 0) -> None:
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        self.delay_ms = delay_ms
        self.settings = StubStorageSettings()
        self.calls = CallTracker()
        self._lock = Lock()
        self._next_object_number = 0
        self._objects: dict[str, bytes] = {
            self.REFERENCE_OBJECT_KEY: self.REFERENCE_IMAGE_BYTES,
        }

    def _delay(self) -> None:
        if self.delay_ms:
            time.sleep(self.delay_ms / 1_000)

    def _next_key(self, prefix: str, suffix: str) -> str:
        with self._lock:
            self._next_object_number += 1
            number = self._next_object_number
        return f"{prefix}/load-{number:08d}{suffix}"

    def create_presigned_upload(
        self,
        file_name: str,
        content_type: str,
    ) -> PresignUploadResponse:
        self.calls.record("create_presigned_upload")
        self._delay()
        suffix = Path(file_name).suffix.lower() or ".png"
        object_key = self._next_key("uploads", suffix)
        return PresignUploadResponse(
            upload_url="https://load-test.invalid/upload",
            fields={"Content-Type": content_type},
            object_key=object_key,
            expires_in=self.settings.presigned_url_expires,
        )

    def create_presigned_download_url(self, object_key: str) -> str:
        self.calls.record("create_presigned_download_url")
        self._delay()
        return f"https://load-test.invalid/read/{object_key}"

    def create_presigned_attachment_url(self, *, object_key: str) -> str:
        self.calls.record("create_presigned_attachment_url")
        self._delay()
        return f"https://load-test.invalid/download/{object_key}"

    def download_image(self, *, object_key: str) -> StoredImage:
        self.calls.record("download_image")
        self._delay()
        with self._lock:
            image_bytes = self._objects.get(object_key)
        if image_bytes is None:
            raise StorageError("load-test reference object does not exist")
        return StoredImage(
            data=image_bytes,
            file_name=Path(object_key).name,
            content_type="image/png",
        )

    def upload_generated_image(self, *, image_bytes: bytes) -> str:
        self.calls.record("upload_generated_image")
        self._delay()
        if not image_bytes:
            raise ValueError("generated image content must not be empty")
        object_key = self._next_key("generations", ".png")
        with self._lock:
            self._objects[object_key] = bytes(image_bytes)
        return object_key

    def delete_generated_image(self, *, object_key: str) -> None:
        self.calls.record("delete_generated_image")
        self._delay()
        path = PurePosixPath(object_key)
        if len(path.parts) != 2 or path.parts[0] != "generations":
            raise StorageError("load-test stub refuses to delete a non-generation object")
        with self._lock:
            self._objects.pop(object_key, None)

    def snapshot(self) -> dict[str, Any]:
        """Return bounded operational state without object keys or bytes."""
        with self._lock:
            generated_object_count = sum(
                key.startswith("generations/") for key in self._objects
            )
        return {
            "provider": "stub",
            "network_enabled": False,
            "delay_ms": self.delay_ms,
            "generated_object_count": generated_object_count,
            "calls": self.calls.snapshot(),
        }


class DeterministicVisionStub:
    """Async OpenAI Vision substitute with fixed delay and response shape."""

    DESCRIPTION = "A deterministic reference subject on a neutral background."

    def __init__(self, *, delay_ms: int = 50) -> None:
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        self.delay_ms = delay_ms
        self.calls = CallTracker()

    async def analyze_image(self, image_url: str, prompt: str) -> str:
        if not image_url or not prompt:
            raise ValueError("image_url and prompt must not be empty")
        self.calls.record("analyze_image")
        await asyncio.sleep(self.delay_ms / 1_000)
        return self.DESCRIPTION

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": "stub",
            "network_enabled": False,
            "delay_ms": self.delay_ms,
            "calls": self.calls.snapshot(),
        }


class DeterministicImageGenerationStub:
    """Async OpenAI Images substitute returning small deterministic byte strings."""

    def __init__(self, *, delay_ms: int = 250) -> None:
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        self.delay_ms = delay_ms
        self.calls = CallTracker()

    async def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        if not prompt:
            raise ValueError("prompt must not be empty")
        self.calls.record("generate_image")
        await asyncio.sleep(self.delay_ms / 1_000)
        return f"load-generated:{width}x{height}".encode()

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
        if not image_bytes or not file_name or not content_type or not prompt:
            raise ValueError("image edit inputs must not be empty")
        self.calls.record("edit_image")
        await asyncio.sleep(self.delay_ms / 1_000)
        return f"load-edited:{width}x{height}".encode()

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": "stub",
            "network_enabled": False,
            "delay_ms": self.delay_ms,
            "calls": self.calls.snapshot(),
        }
