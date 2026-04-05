"""Google Gemini multimodal LLM provider.

Supports text, image, and audio input via the Google AI Python SDK (google-genai).
Default model: gemini-2.0-flash (fast, multimodal, 1M token context).

Pricing (as of 2026-03):
  Flash:  $0.10/M input, $0.40/M output
  Pro:    $1.25/M input, $5.00/M output (up to 200K context)

Multimodal convention — callers embed media references in message content
using bracket tags that this provider parses into Gemini-native Part objects:

  [image:https://example.com/photo.jpg]          — image from URL
  [image_base64:image/png;iVBORw0KGgo...]        — inline base64 image
  [audio:https://example.com/recording.wav]       — audio from URL

The provider strips these tags from the text and converts them to the
appropriate Gemini content parts for multimodal generation.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import AsyncGenerator, Optional

from isg_agent.models.provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
    RateLimitError,
)

# Module-level import with ImportError guard so the module can be imported
# even when google-genai is not installed (test isolation, optional dep).
try:
    from google import genai
    from google.genai import types as genai_types
    from google.api_core import exceptions as google_exceptions
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]
    google_exceptions = None  # type: ignore[assignment]

__all__ = ["GoogleProvider"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUPPORTED_MODELS: frozenset[str] = frozenset(
    {
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    }
)

_DEFAULT_MODEL = "gemini-2.0-flash"

# Pricing per 1M tokens
_FLASH_INPUT_COST_PER_M = 0.10
_FLASH_OUTPUT_COST_PER_M = 0.40
_PRO_INPUT_COST_PER_M = 1.25
_PRO_OUTPUT_COST_PER_M = 5.00

# HTTP status codes treated as rate-limit / temporary overload
_RATE_LIMIT_CODES: frozenset[int] = frozenset({429, 503})

# ---------------------------------------------------------------------------
# Multimodal tag patterns
# ---------------------------------------------------------------------------

_IMAGE_URL_PATTERN = r"\[image:(https?://[^\]]+)\]"
_BASE64_IMAGE_PATTERN = r"\[image_base64:([^;]+);([^\]]+)\]"
_AUDIO_URL_PATTERN = r"\[audio:(https?://[^\]]+)\]"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_role(role: str) -> str:
    """Map LLMMessage roles to Gemini API roles.

    Gemini uses "user" and "model" (not "assistant").
    System messages are handled separately via system_instruction.
    """
    if role == "assistant":
        return "model"
    return role


def _split_system_and_conversation(
    messages: list[LLMMessage],
) -> tuple[Optional[str], list[LLMMessage]]:
    """Separate system messages from conversation messages.

    Gemini requires system instructions to be passed separately from
    the conversation. This function extracts all system-role messages,
    joins them into a single string, and returns the rest.

    Returns
    -------
    tuple[str | None, list[LLMMessage]]
        (system_instruction_text_or_None, conversation_messages)
    """
    system_parts: list[str] = []
    conversation: list[LLMMessage] = []

    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        else:
            conversation.append(msg)

    system_text = " ".join(system_parts) if system_parts else None
    return system_text, conversation


def _is_pro_model(model: str) -> bool:
    """Return True if the model uses pro-tier pricing."""
    return "pro" in model.lower()


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = _DEFAULT_MODEL,
) -> float:
    """Estimate USD cost based on token counts and model tier.

    Returns
    -------
    float
        Estimated cost in USD, rounded to 8 decimal places.
    """
    if _is_pro_model(model):
        input_rate = _PRO_INPUT_COST_PER_M
        output_rate = _PRO_OUTPUT_COST_PER_M
    else:
        input_rate = _FLASH_INPUT_COST_PER_M
        output_rate = _FLASH_OUTPUT_COST_PER_M

    cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
    return round(cost, 8)


def _map_finish_reason(reason: object) -> str:
    """Map Gemini finish reason to the normalized LLMResponse finish_reason.

    Gemini returns enum-like values: STOP, MAX_TOKENS, SAFETY, etc.
    We normalize to: "stop", "length", "error".
    """
    reason_str = str(reason).upper() if reason else "STOP"
    if "STOP" in reason_str:
        return "stop"
    if "MAX_TOKENS" in reason_str:
        return "length"
    # SAFETY, RECITATION, OTHER -> "error"
    return "error"


def _parse_multimodal_content(content: str) -> list[object]:
    """Parse message content for multimodal tags and return Gemini-compatible parts.

    If genai_types is not available (SDK not installed), returns the raw text
    so tests with mocked clients still work.

    Returns a list of content parts (strings for text, Part objects for media).
    """
    parts: list[object] = []
    remaining = content

    # Extract image URLs
    for match in re.finditer(_IMAGE_URL_PATTERN, remaining):
        url = match.group(1)
        if genai_types is not None:
            parts.append(genai_types.Part.from_uri(file_uri=url, mime_type="image/jpeg"))
        else:
            parts.append({"type": "image_url", "url": url})

    # Extract base64 images
    for match in re.finditer(_BASE64_IMAGE_PATTERN, remaining):
        mime_type = match.group(1)
        b64_data = match.group(2)
        if genai_types is not None:
            image_bytes = base64.b64decode(b64_data)
            parts.append(genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        else:
            parts.append({"type": "image_base64", "mime_type": mime_type, "data": b64_data})

    # Extract audio URLs
    for match in re.finditer(_AUDIO_URL_PATTERN, remaining):
        url = match.group(1)
        if genai_types is not None:
            parts.append(genai_types.Part.from_uri(file_uri=url, mime_type="audio/wav"))
        else:
            parts.append({"type": "audio_url", "url": url})

    # Strip all tags from the text and add the clean text as first part
    clean_text = re.sub(_IMAGE_URL_PATTERN, "", remaining)
    clean_text = re.sub(_BASE64_IMAGE_PATTERN, "", clean_text)
    clean_text = re.sub(_AUDIO_URL_PATTERN, "", clean_text)
    clean_text = clean_text.strip()

    if clean_text:
        parts.insert(0, clean_text)

    # If no media tags found, just return the original text
    if not parts:
        return [content]

    return parts


def _build_gemini_contents(
    messages: list[LLMMessage],
) -> list[dict[str, object]]:
    """Convert LLMMessage conversation (no system) to Gemini content dicts.

    Each message becomes a dict with 'role' and 'parts'.
    Multimodal tags in content are parsed into separate parts.
    """
    contents: list[dict[str, object]] = []
    for msg in messages:
        role = _map_role(msg.role)
        parts = _parse_multimodal_content(msg.content)
        contents.append({"role": role, "parts": parts})
    return contents


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class GoogleProvider(LLMProvider):
    """Google Gemini multimodal LLM provider.

    Uses the google-genai SDK for text, image, and audio understanding.
    Supports both synchronous complete() and streaming stream() calls.

    Parameters
    ----------
    api_key:
        Google AI API key. Required (non-empty).
    default_model:
        Model to use when no override is given (default: gemini-2.0-flash).
    """

    def __init__(
        self,
        api_key: str = "",
        default_model: str = _DEFAULT_MODEL,
    ) -> None:
        if not api_key:
            raise ValueError(
                "Google API key is required. Set GOOGLE_API_KEY or "
                "ISG_AGENT_GOOGLE_API_KEY environment variable."
            )

        self._api_key = api_key
        self._default_model = default_model

        if genai is None:
            raise ImportError(
                "The 'google-genai' package is required for GoogleProvider. "
                "Install it with: pip install google-genai"
            )

        self._client = genai.Client(api_key=api_key)
        # The model client handles generate_content calls
        self._model_client = self._client.models

        # Store the error class for isinstance checks in error handlers
        if google_exceptions is not None:
            self._google_error_cls = google_exceptions.GoogleAPIError
        else:
            self._google_error_cls = Exception

        self._rate_limit_codes = _RATE_LIMIT_CODES

    @property
    def provider_name(self) -> str:
        return "google"

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
        """Send messages and return a complete response from Gemini.

        Extracts system messages as system_instruction, maps roles,
        parses multimodal tags, and tracks cost in the extra dict.
        """
        resolved_model = model or self._default_model
        system_instruction, conversation = _split_system_and_conversation(messages)
        contents = _build_gemini_contents(conversation)

        # Build generation config
        config: dict[str, object] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_instruction:
            config["system_instruction"] = system_instruction

        try:
            response = await self._model_client.generate_content(
                model=resolved_model,
                contents=contents,
                config=config,
            )

            # Extract text from response
            content = ""
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    text_parts = []
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            text_parts.append(part.text)
                    content = "".join(text_parts)

                finish_reason = _map_finish_reason(
                    candidate.finish_reason if candidate else None
                )
            else:
                # Fallback: use .text property if available
                content = getattr(response, "text", "") or ""
                finish_reason = "stop"

            # Token counts from usage metadata
            usage = getattr(response, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
            output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
            cost_usd = _estimate_cost(input_tokens, output_tokens, resolved_model)

            logger.debug(
                "Google complete: model=%s in=%d out=%d finish=%s cost=$%.8f",
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
                    "provider": "google",
                    "cost_usd": cost_usd,
                    "input_cost_per_m": (
                        _PRO_INPUT_COST_PER_M if _is_pro_model(resolved_model) else _FLASH_INPUT_COST_PER_M
                    ),
                    "output_cost_per_m": (
                        _PRO_OUTPUT_COST_PER_M if _is_pro_model(resolved_model) else _FLASH_OUTPUT_COST_PER_M
                    ),
                },
            )

        except Exception as exc:
            # Check for rate-limit or temporary overload
            status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            if isinstance(status_code, int) and status_code in self._rate_limit_codes:
                raise RateLimitError(provider="google") from exc

            # Check if it's a known Google API error class
            if isinstance(exc, self._google_error_cls) and not isinstance(exc, (RateLimitError, ProviderError)):
                raise ProviderError(
                    message=str(exc),
                    provider="google",
                    status_code=status_code if isinstance(status_code, int) else None,
                ) from exc

            # Re-raise our own exceptions
            if isinstance(exc, (ProviderError, RateLimitError)):
                raise

            # Wrap all other exceptions as ProviderError
            raise ProviderError(
                message=str(exc),
                provider="google",
                status_code=None,
            ) from exc

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from Gemini as they are generated.

        Yields successive text chunks. Multimodal input is supported
        the same as for complete().
        """
        resolved_model = model or self._default_model
        system_instruction, conversation = _split_system_and_conversation(messages)
        contents = _build_gemini_contents(conversation)

        config: dict[str, object] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_instruction:
            config["system_instruction"] = system_instruction

        try:
            stream_response = await self._model_client.generate_content_stream(
                model=resolved_model,
                contents=contents,
                config=config,
            )

            async for chunk in stream_response:
                text = getattr(chunk, "text", None)
                if text:
                    yield text

        except Exception as exc:
            status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            if isinstance(status_code, int) and status_code in self._rate_limit_codes:
                raise RateLimitError(provider="google") from exc

            if isinstance(exc, (ProviderError, RateLimitError)):
                raise

            raise ProviderError(
                message=str(exc),
                provider="google",
                status_code=status_code if isinstance(status_code, int) else None,
            ) from exc
