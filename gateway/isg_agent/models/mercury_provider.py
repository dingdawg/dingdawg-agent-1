"""Mercury 2 (Inception Labs) LLM provider implementation.

Wraps the OpenAI-compatible Inception API for Mercury 2 diffusion-based
chat completions with streaming support, token tracking, and rate-limit backoff.

Mercury 2 is a diffusion-based reasoning LLM that generates tokens via
parallel refinement rather than sequential autoregressive decoding, achieving
1000+ tokens/sec at $0.25/M input, $0.75/M output.

API reference: https://docs.inceptionlabs.ai/get-started/models
Authentication: Bearer token via INCEPTION_API_KEY env var
Base URL: https://api.inceptionlabs.ai/v1
OpenAI-compatible: Yes (drop-in via openai Python SDK)
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

# Module-level imports so tests can patch at
# ``isg_agent.models.mercury_provider.AsyncOpenAI`` etc.
try:
    from openai import AsyncOpenAI
    from openai import RateLimitError as OpenAIRateLimitError
    from openai import APIError as OpenAIAPIError
except ImportError:  # openai SDK not installed
    AsyncOpenAI = None  # type: ignore[misc,assignment]
    OpenAIRateLimitError = None  # type: ignore[misc,assignment]
    OpenAIAPIError = None  # type: ignore[misc,assignment]

__all__ = ["MercuryProvider"]

logger = logging.getLogger(__name__)

# Models this provider supports
_SUPPORTED_MODELS: frozenset[str] = frozenset(
    {
        "mercury-2",
        "mercury",  # Legacy / alias
    }
)

# Default model when no override is given
_DEFAULT_MODEL = "mercury-2"

# Inception API base URL (OpenAI-compatible)
_INCEPTION_BASE_URL = "https://api.inceptionlabs.ai/v1"

# Retry configuration for rate limits
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds

# Pricing per 1M tokens (used for cost tracking in extra field)
_INPUT_COST_PER_M = 0.25   # USD per 1M input tokens
_OUTPUT_COST_PER_M = 0.75  # USD per 1M output tokens


def _to_openai_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
    """Convert :class:`LLMMessage` objects to the OpenAI API format."""
    return [{"role": m.role, "content": m.content} for m in messages]


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a request based on Inception's published pricing.

    Returns
    -------
    float
        Estimated cost in USD, rounded to 8 decimal places.
    """
    input_cost = (input_tokens / 1_000_000) * _INPUT_COST_PER_M
    output_cost = (output_tokens / 1_000_000) * _OUTPUT_COST_PER_M
    return round(input_cost + output_cost, 8)


class MercuryProvider(LLMProvider):
    """Inception Labs Mercury 2 provider (OpenAI-compatible).

    Uses the OpenAI Python SDK pointed at Inception's API endpoint.
    Mercury 2 is a diffusion-based reasoning model that generates text
    via parallel token refinement rather than sequential decoding.

    Parameters
    ----------
    api_key:
        Inception API key (INCEPTION_API_KEY). Required for real calls;
        may be empty for tests that mock the underlying client.
    default_model:
        Model to use when no override is passed.
    default_temperature:
        Default sampling temperature (0.0-2.0).
    default_max_tokens:
        Default maximum tokens for completions.
    base_url:
        Override the Inception API base URL (useful for testing or
        self-hosted deployments).
    diffusing:
        Enable the diffusion visualization mode. When True, the model
        streams intermediate noisy tokens that refine into the final
        output. These noisy tokens are not billed. Default False.
    """

    def __init__(
        self,
        api_key: str = "",
        default_model: str = _DEFAULT_MODEL,
        default_temperature: float = 0.7,
        default_max_tokens: int = 1024,
        base_url: str = _INCEPTION_BASE_URL,
        diffusing: bool = False,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens
        self._base_url = base_url
        self._diffusing = diffusing

        if AsyncOpenAI is None:
            raise ImportError(
                "The 'openai' package is required for MercuryProvider. "
                "Install it with: pip install openai"
            )

        self._client = AsyncOpenAI(
            api_key=api_key or "dummy-key-for-tests",
            base_url=base_url,
        )
        self._openai_rate_limit_error = OpenAIRateLimitError
        self._openai_api_error = OpenAIAPIError

    @property
    def provider_name(self) -> str:
        return "mercury"

    @property
    def supported_models(self) -> frozenset[str]:
        """Return the set of model identifiers this provider handles."""
        return _SUPPORTED_MODELS

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Send messages and return a complete response from Mercury 2.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff
        on rate-limit errors.  Includes cost estimation in the ``extra``
        field of the response.
        """
        resolved_model = model or self._default_model
        oai_messages = _to_openai_messages(messages)
        last_exc: Exception | None = None

        # Build kwargs -- Mercury 2 uses standard OpenAI params
        # plus the optional 'diffusing' parameter
        extra_kwargs: dict[str, object] = {
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

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
                cost_usd = _estimate_cost(input_tokens, output_tokens)

                logger.debug(
                    "Mercury complete: model=%s in=%d out=%d finish=%s cost=$%.8f",
                    resolved_model,
                    input_tokens,
                    output_tokens,
                    finish_reason,
                    cost_usd,
                )

                return LLMResponse(
                    content=content,
                    model=resolved_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=finish_reason,
                    extra={
                        "provider": "mercury",
                        "cost_usd": cost_usd,
                        "input_cost_per_m": _INPUT_COST_PER_M,
                        "output_cost_per_m": _OUTPUT_COST_PER_M,
                        "diffusing": self._diffusing,
                    },
                )

            except self._openai_rate_limit_error as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "Mercury rate limit hit (attempt %d/%d), waiting %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise RateLimitError(provider="mercury") from exc

            except self._openai_api_error as exc:
                raise ProviderError(
                    message=str(exc),
                    provider="mercury",
                    status_code=getattr(exc, "status_code", None),
                ) from exc

        # Should not reach here, but satisfy type checker
        raise ProviderError(
            message=f"All {_MAX_RETRIES} retries exhausted",
            provider="mercury",
        ) from last_exc

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from Mercury 2 chat completion.

        Mercury 2's diffusion-based generation can stream intermediate
        refinement steps when ``diffusing=True`` is enabled on the provider.
        In standard mode, it streams final tokens like any OpenAI-compatible
        endpoint.
        """
        resolved_model = model or self._default_model
        oai_messages = _to_openai_messages(messages)

        extra_kwargs: dict[str, object] = {
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response_stream = await self._client.chat.completions.create(
                model=resolved_model,
                messages=oai_messages,  # type: ignore[arg-type]
                stream=True,
                **extra_kwargs,
            )

            async for chunk in response_stream:
                # Handle both OpenAI-style (.choices) and other formats (.content, .delta)
                if hasattr(chunk, 'choices') and chunk.choices:
                    for choice in chunk.choices:
                        delta = choice.delta
                        if delta and delta.content:
                            yield delta.content
                elif hasattr(chunk, 'delta') and hasattr(chunk.delta, 'content') and chunk.delta.content:
                    yield chunk.delta.content
                elif hasattr(chunk, 'content') and chunk.content:
                    yield chunk.content
                elif hasattr(chunk, 'text') and chunk.text:
                    yield chunk.text

        except self._openai_rate_limit_error as exc:
            raise RateLimitError(provider="mercury") from exc
        except self._openai_api_error as exc:
            raise ProviderError(
                message=str(exc),
                provider="mercury",
                status_code=getattr(exc, "status_code", None),
            ) from exc
