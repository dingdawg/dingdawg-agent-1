"""OpenAI LLM provider implementation.

Wraps the OpenAI async Python SDK for chat completions with
streaming support, token tracking, and rate-limit backoff.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Optional

from isg_agent.models.provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
    RateLimitError,
)

__all__ = ["OpenAIProvider"]

logger = logging.getLogger(__name__)

# Models this provider supports
_SUPPORTED_MODELS: frozenset[str] = frozenset(
    {
        "gpt-5",
        "gpt-5-mini",
        "gpt-5.2",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "o1",
        "o1-mini",
    }
)

# Default model when no override is given
_DEFAULT_MODEL = "gpt-4o-mini"

# Retry configuration for rate limits
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds


def _to_openai_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
    """Convert :class:`LLMMessage` objects to the OpenAI API format."""
    return [{"role": m.role, "content": m.content} for m in messages]


class OpenAIProvider(LLMProvider):
    """OpenAI chat-completion provider.

    Parameters
    ----------
    api_key:
        OpenAI API key. Required for real calls; may be empty for tests
        that mock the underlying client.
    default_model:
        Model to use when no override is passed to :meth:`complete`
        or :meth:`stream`.
    default_temperature:
        Default sampling temperature.
    default_max_tokens:
        Default maximum tokens for completions.
    """

    def __init__(
        self,
        api_key: str = "",
        default_model: str = _DEFAULT_MODEL,
        default_temperature: float = 0.7,
        default_max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens

        # Import lazily so the module can be imported without a valid key
        from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError, APIError

        self._client = AsyncOpenAI(api_key=api_key or "dummy-key-for-tests")
        self._openai_rate_limit_error = OpenAIRateLimitError
        self._openai_api_error = APIError

    @property
    def provider_name(self) -> str:
        return "openai"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Send messages and return a complete response.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff
        on rate-limit errors.
        """
        resolved_model = model or self._default_model
        oai_messages = _to_openai_messages(messages)
        last_exc: Exception | None = None

        # GPT-5+ and o-series models have different API parameter requirements:
        # - Use max_completion_tokens instead of max_tokens
        # - Only support temperature=1 (no custom temperature)
        _is_new_api = resolved_model.startswith(("gpt-5", "o1", "o3"))
        extra_kwargs: dict[str, object] = {}
        if _is_new_api:
            extra_kwargs["max_completion_tokens"] = max_tokens
        else:
            extra_kwargs["max_tokens"] = max_tokens
            extra_kwargs["temperature"] = temperature

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.chat.completions.create(
                    model=resolved_model,
                    messages=oai_messages,  # type: ignore[arg-type]
                    **extra_kwargs,
                )

                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = choice.finish_reason or "stop"
                usage = response.usage

                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                logger.debug(
                    "OpenAI complete: model=%s in=%d out=%d finish=%s",
                    resolved_model,
                    input_tokens,
                    output_tokens,
                    finish_reason,
                )

                return LLMResponse(
                    content=content,
                    model=resolved_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=finish_reason,
                )

            except self._openai_rate_limit_error as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "OpenAI rate limit hit (attempt %d/%d), waiting %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise RateLimitError(provider="openai") from exc

            except self._openai_api_error as exc:
                raise ProviderError(
                    message=str(exc),
                    provider="openai",
                    status_code=getattr(exc, "status_code", None),
                ) from exc

        # Should not reach here, but satisfy type checker
        raise ProviderError(
            message=f"All {_MAX_RETRIES} retries exhausted",
            provider="openai",
        ) from last_exc

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from OpenAI chat completion."""
        resolved_model = model or self._default_model
        oai_messages = _to_openai_messages(messages)

        _is_new_api = resolved_model.startswith(("gpt-5", "o1", "o3"))
        extra_kwargs: dict[str, object] = {}
        if _is_new_api:
            extra_kwargs["max_completion_tokens"] = max_tokens
        else:
            extra_kwargs["max_tokens"] = max_tokens
            extra_kwargs["temperature"] = temperature

        try:
            async with self._client.chat.completions.stream(
                model=resolved_model,
                messages=oai_messages,  # type: ignore[arg-type]
                **extra_kwargs,
            ) as stream:
                async for event in stream:
                    # Handle both old (.choices) and new (.content) SDK formats
                    if hasattr(event, 'choices') and event.choices:
                        for choice in event.choices:
                            delta = choice.delta
                            if delta and delta.content:
                                yield delta.content
                    elif hasattr(event, 'type') and event.type == 'content.delta':
                        if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
                            yield event.delta.text
                    elif hasattr(event, 'content') and event.content:
                        yield event.content

        except self._openai_rate_limit_error as exc:
            raise RateLimitError(provider="openai") from exc
        except self._openai_api_error as exc:
            raise ProviderError(
                message=str(exc),
                provider="openai",
                status_code=getattr(exc, "status_code", None),
            ) from exc
