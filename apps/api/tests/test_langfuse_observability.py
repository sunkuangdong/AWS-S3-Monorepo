from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import langfuse_observability
from app.core.langfuse_observability import (
    NullObservation,
    image_usage_details,
    observe_operation,
    response_usage_details,
)


def test_response_usage_details_uses_exclusive_buckets() -> None:
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=40,
        input_tokens_details=SimpleNamespace(
            cached_tokens=20,
            cache_write_tokens=10,
        ),
        output_tokens_details=SimpleNamespace(
            reasoning_tokens=5,
        ),
    )

    assert response_usage_details(usage) == {
        "input": 90,
        "output": 35,
        "input_cached_tokens": 20,
        "input_cache_write_tokens": 10,
        "output_reasoning_tokens": 5,
    }


def test_image_usage_details_preserves_modalities() -> None:
    usage = SimpleNamespace(
        input_tokens=17,
        output_tokens=29,
        input_tokens_details=SimpleNamespace(
            text_tokens=11,
            image_tokens=6,
        ),
        output_tokens_details=SimpleNamespace(
            text_tokens=3,
            image_tokens=26,
        ),
    )

    assert image_usage_details(usage) == {
        "input_text_tokens": 11,
        "input_image_tokens": 6,
        "output_text_tokens": 3,
        "output_image_tokens": 26,
    }


def test_missing_usage_is_ignored() -> None:
    assert response_usage_details(None) is None
    assert image_usage_details(None) is None


def test_disabled_tracing_uses_noop_observation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")

    with observe_operation(
        name="test-operation",
        metadata={"status": "started"},
    ) as observation:
        assert isinstance(observation, NullObservation)
        observation.update(
            metadata={"status": "completed"},
        )


def test_error_trace_records_only_exception_type(
    monkeypatch,
) -> None:
    observation = Mock()
    sdk_received_exception = False

    class FakeObservationContext:
        def __enter__(self):
            return observation

        def __exit__(self, error_type, error, traceback):
            nonlocal sdk_received_exception
            sdk_received_exception = error_type is not None
            return False

    class FakeClient:
        def start_as_current_observation(self, **_):
            return FakeObservationContext()

    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setattr(
        langfuse_observability,
        "get_langfuse_client",
        lambda: FakeClient(),
    )

    with (
        pytest.raises(RuntimeError, match="sensitive provider details"),
        observe_operation(name="failing-operation"),
    ):
        raise RuntimeError("sensitive provider details")

    assert sdk_received_exception is False
    observation.update.assert_called_once_with(
        level="ERROR",
        status_message="RuntimeError",
        metadata={
            "status": "failed",
            "error_type": "RuntimeError",
        },
    )
