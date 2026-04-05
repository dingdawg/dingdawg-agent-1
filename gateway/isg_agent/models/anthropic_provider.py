"""Anthropic LLM provider implementation.

Wraps the Anthropic async Python SDK for Claude chat completions with
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

__all__ = ["AnthropicProvider"]

logger = logging.getLogger(__name__)

# Models this provider supports
_SUPPORTED_MODELS: frozenset[str] = frozenset(
    {
        # Current generation (Claude 4.x)
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5-20251001",
        # Legacy (deprecated — may return errors)
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    }
)

# Default model when no override is given
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Retry configuration for rate limits
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds

# Anthropic requires a non-empty system message to be provided separately
_DEFAULT_SYSTEM = "You are a helpful AI assistant."


def _split_messages(
    messages: list[LLMMessage],
) -> tuple[str, list[dict[str, str]]]:
    """Split messages into system prompt and conversation messages.

    Anthropic requires the system prompt to be passed separately from
    the conversation messages. This function extracts any leading
    "system" role messages and returns the rest as conversation turns.

    Returns
    -------
    tuple[str, list[dict]]
        (system_prompt, conversation_messages)
    """
    system_parts: list[str] = []
    conversation: list[dict[str, str]] = []

    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        else:
            conversation.append({"role": msg.role, "content": msg.content})

    system = " ".join(system_parts) if system_parts else _DEFAULT_SYSTEM
    return system, conversation


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider.

    Parameters
    ----------
    api_key:
        Anthropic API key. Required for real calls; may be empty for tests
        that mock the underlying client.
    default_model:
        Model to use when no override is passed.
    default_temperature:
        Default sampling temperature (0.0–1.0).
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
        from anthropic import AsyncAnthropic, RateLimitError as AnthRateLimit, APIError

        self._client = AsyncAnthropic(api_key=api_key or "dummy-key-for-tests")
        self._anth_rate_limit_error = AnthRateLimit
        self._anth_api_error = APIError

    @property
    def provider_name(self) -> str:
        return "anthropic"

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
        system, conversation = _split_messages(messages)
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=resolved_model,
                    system=system,
                    messages=conversation,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Extract text content from the first content block
                content = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        content += block.text

                finish_reason = response.stop_reason or "stop"
                usage = response.usage

                input_tokens = usage.input_tokens if usage else 0
                output_tokens = usage.output_tokens if usage else 0

                logger.debug(
                    "Anthropic complete: model=%s in=%d out=%d finish=%s",
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

            except self._anth_rate_limit_error as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "Anthropic rate limit hit (attempt %d/%d), waiting %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise RateLimitError(provider="anthropic") from exc

            except self._anth_api_error as exc:
                raise ProviderError(
                    message=str(exc),
                    provider="anthropic",
                    status_code=getattr(exc, "status_code", None),
                ) from exc

        # Should not reach here, but satisfy type checker
        raise ProviderError(
            message=f"All {_MAX_RETRIES} retries exhausted",
            provider="anthropic",
        ) from last_exc

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from Anthropic Claude."""
        resolved_model = model or self._default_model
        system, conversation = _split_messages(messages)

        try:
            async with self._client.messages.stream(
                model=resolved_model,
                system=system,
                messages=conversation,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            ) as stream:
                async for text_chunk in stream.text_stream:
                    yield text_chunk

        except self._anth_rate_limit_error as exc:
            raise RateLimitError(provider="anthropic") from exc
        except self._anth_api_error as exc:
            raise ProviderError(
                message=str(exc),
                provider="anthropic",
                status_code=getattr(exc, "status_code", None),
            ) from exc
