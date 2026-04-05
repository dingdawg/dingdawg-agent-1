"""Abstract LLM provider interface.

Defines the base contract that all LLM providers must implement.
Supports streaming and non-streaming completions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

__all__ = [
    "LLMMessage",
    "LLMResponse",
    "LLMProvider",
    "ProviderError",
    "RateLimitError",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LLMMessage:
    """A single message in an LLM conversation.

    Attributes
    ----------
    role:
        The message role: "system", "user", or "assistant".
    content:
        The text content of the message.
    """

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """The complete response from an LLM provider.

    Attributes
    ----------
    content:
        The text content of the response.
    model:
        The model identifier that generated the response.
    input_tokens:
        Number of tokens in the input messages.
    output_tokens:
        Number of tokens in the generated response.
    finish_reason:
        Reason generation stopped: "stop", "length", "tool_use", or "error".
    """

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str  # "stop", "length", "tool_use", "error"
    extra: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base exception for LLM provider errors.

    Attributes
    ----------
    message:
        Human-readable description of the error.
    provider:
        Name of the provider that raised the error.
    status_code:
        HTTP status code if applicable, else None.
    """

    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        status_code: Optional[int] = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message}")


class RateLimitError(ProviderError):
    """Raised when the provider returns a rate limit response (HTTP 429).

    Attributes
    ----------
    retry_after:
        Suggested seconds to wait before retrying, or None if not provided.
    """

    def __init__(
        self,
        provider: str = "unknown",
        retry_after: Optional[float] = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(
            message="Rate limit exceeded",
            provider=provider,
            status_code=429,
        )


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Base class for LLM provider implementations.

    All providers must implement :meth:`complete` and :meth:`stream`.
    Providers should handle their own retry logic for transient errors
    and raise :class:`ProviderError` or :class:`RateLimitError` on failure.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for this provider (e.g. "openai", "anthropic")."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Send messages and return a complete response.

        Parameters
        ----------
        messages:
            The conversation history as a list of :class:`LLMMessage`.
        model:
            Override the default model for this call.
        temperature:
            Sampling temperature (0.0–2.0 for OpenAI, 0.0–1.0 for Anthropic).
        max_tokens:
            Maximum tokens to generate in the response.

        Returns
        -------
        LLMResponse
            The complete response with token counts and finish reason.

        Raises
        ------
        RateLimitError
            If the provider returns HTTP 429.
        ProviderError
            For all other provider-side errors.
        """

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens as they are generated.

        Yields successive text chunks from the response stream.
        The stream ends when the provider signals completion.

        Parameters
        ----------
        messages:
            The conversation history.
        model:
            Override the default model.
        temperature:
            Sampling temperature.
        max_tokens:
            Maximum tokens to generate.

        Yields
        ------
        str
            Successive text chunks.

        Raises
        ------
        RateLimitError
            If the provider returns HTTP 429.
        ProviderError
            For all other provider-side errors.
        """
        # Must be declared as async generator — implementations override this
        return  # pragma: no cover
        yield  # noqa: unreachable — makes this an async generator  # pragma: no cover
