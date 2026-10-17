import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from types import TracebackType
from typing import Any, Literal, Protocol

from langfuse import Langfuse

ObservationType = Literal[
    "span",
    "chain",
    "generation",
]


class Observation(Protocol):
    """Small interface shared by real and disabled observations."""

    def update(self, **kwargs: Any) -> Any:
        """Update safe metadata, usage, or status fields."""


class NullObservation:
    """No-op observation used when Langfuse tracing is disabled."""

    def update(self, **_: Any) -> None:
        return None


def _environment_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def langfuse_tracing_enabled() -> bool:
    """Return whether application traces should be exported."""
    return _environment_flag(
        "LANGFUSE_TRACING_ENABLED",
        default=False,
    )


@lru_cache(maxsize=1)
def get_langfuse_client() -> Langfuse:
    """Create one Langfuse client without copying secrets into traces."""
    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_BASE_URL"),
        tracing_enabled=True,
        environment=os.getenv(
            "LANGFUSE_ENVIRONMENT",
            "local-evaluation",
        ),
    )


@contextmanager
def observe_operation(
    *,
    name: str,
    as_type: ObservationType = "span",
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
    model_parameters: dict[str, Any] | None = None,
) -> Iterator[Observation]:
    """
    Create a privacy-safe observation.

    Input and output are deliberately omitted. Callers may add only bounded,
    non-sensitive metadata such as dimensions, byte counts, status values,
    model names, and generated database identifiers.
    """
    if not langfuse_tracing_enabled():
        yield NullObservation()
        return

    client = get_langfuse_client()
    captured_error: Exception | None = None
    captured_traceback: TracebackType | None = None
    with client.start_as_current_observation(
        name=name,
        as_type=as_type,
        metadata=metadata,
        model=model,
        model_parameters=model_parameters,
    ) as observation:
        try:
            yield observation
        except Exception as error:  # noqa: BLE001 - privacy boundary
            # Do not let the SDK automatically capture the original exception
            # message or traceback: provider errors can contain bucket names,
            # object keys, request payloads, or signed URLs. Record only the
            # exception class, close the SDK context normally, then re-raise.
            mark_observation_error(observation, error)
            captured_error = error
            captured_traceback = error.__traceback__

    if captured_error is not None:
        raise captured_error.with_traceback(captured_traceback)


def mark_observation_error(
    observation: Observation,
    error: BaseException,
) -> None:
    """Record only the exception class, never provider payloads or URLs."""
    observation.update(
        level="ERROR",
        status_message=type(error).__name__,
        metadata={
            "status": "failed",
            "error_type": type(error).__name__,
        },
    )


def response_usage_details(usage: Any | None) -> dict[str, int] | None:
    """Normalize OpenAI Responses usage into exclusive Langfuse buckets."""
    if usage is None:
        return None

    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)

    cached_tokens = int(
        getattr(input_details, "cached_tokens", 0) or 0
    )
    cache_write_tokens = int(
        getattr(input_details, "cache_write_tokens", 0) or 0
    )
    reasoning_tokens = int(
        getattr(output_details, "reasoning_tokens", 0) or 0
    )

    details = {
        "input": max(
            input_tokens - cached_tokens - cache_write_tokens,
            0,
        ),
        "output": max(output_tokens - reasoning_tokens, 0),
    }
    if cached_tokens:
        details["input_cached_tokens"] = cached_tokens
    if cache_write_tokens:
        details["input_cache_write_tokens"] = cache_write_tokens
    if reasoning_tokens:
        details["output_reasoning_tokens"] = reasoning_tokens

    return details


def image_usage_details(usage: Any | None) -> dict[str, int] | None:
    """Normalize image-model usage without double-counting totals."""
    if usage is None:
        return None

    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    details: dict[str, int] = {}

    if input_details is not None:
        details["input_text_tokens"] = int(
            getattr(input_details, "text_tokens", 0) or 0
        )
        details["input_image_tokens"] = int(
            getattr(input_details, "image_tokens", 0) or 0
        )
    else:
        details["input"] = int(
            getattr(usage, "input_tokens", 0) or 0
        )

    if output_details is not None:
        details["output_text_tokens"] = int(
            getattr(output_details, "text_tokens", 0) or 0
        )
        details["output_image_tokens"] = int(
            getattr(output_details, "image_tokens", 0) or 0
        )
    else:
        details["output"] = int(
            getattr(usage, "output_tokens", 0) or 0
        )

    return details


def flush_langfuse() -> None:
    """Flush pending events during graceful application shutdown."""
    if langfuse_tracing_enabled():
        get_langfuse_client().shutdown()
