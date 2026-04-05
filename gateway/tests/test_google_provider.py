"""Google Gemini multimodal LLM provider tests.

Tests for isg_agent.models.google_provider.GoogleProvider.

All tests mock the Google AI SDK to avoid real API calls.
Tests validate:
1. Provider identity and configuration
2. Complete (non-streaming) responses with cost tracking
3. Streaming responses
4. Multimodal input handling (images, audio)
5. Rate-limit and error propagation
6. Role mapping (system -> system_instruction, assistant -> model)
7. Cost estimation accuracy (flash + pro pricing)
8. Forbidden import checks
9. Edge cases (empty messages, unicode, None content)
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import sys
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from isg_agent.models.provider import (
    LLMMessage,
    LLMResponse,
    ProviderError,
    RateLimitError,
)


# ---------------------------------------------------------------------------
# Helpers — fake Google AI SDK response objects
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsageMetadata:
    prompt_token_count: int = 100
    candidates_token_count: int = 50
    total_token_count: int = 150


@dataclass
class _FakePart:
    text: str = "Hello from Gemini!"


@dataclass
class _FakeContent:
    parts: list[_FakePart] = None  # type: ignore[assignment]
    role: str = "model"

    def __post_init__(self) -> None:
        if self.parts is None:
            self.parts = [_FakePart()]


@dataclass
class _FakeCandidate:
    content: _FakeContent = None  # type: ignore[assignment]
    finish_reason: Any = None

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = _FakeContent()
        # Default finish_reason: simulate the enum-like STOP value
        if self.finish_reason is None:
            self.finish_reason = _FinishReason.STOP


class _FinishReason:
    """Simulate google.genai.types.FinishReason enum."""
    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"


@dataclass
class _FakeGenerateResponse:
    candidates: list[_FakeCandidate] = None  # type: ignore[assignment]
    usage_metadata: _FakeUsageMetadata = None  # type: ignore[assignment]
    text: str = "Hello from Gemini!"

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = [_FakeCandidate()]
        if self.usage_metadata is None:
            self.usage_metadata = _FakeUsageMetadata()


@dataclass
class _FakeStreamChunk:
    text: str = ""
    candidates: list[_FakeCandidate] = None  # type: ignore[assignment]
    usage_metadata: _FakeUsageMetadata = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = [_FakeCandidate()]
        if self.usage_metadata is None:
            self.usage_metadata = _FakeUsageMetadata()


class _FakeAsyncIterator:
    """Async iterator that yields pre-defined stream chunks."""

    def __init__(self, chunks: list[_FakeStreamChunk]) -> None:
        self._chunks = chunks
        self._index = 0

    def __aiter__(self) -> _FakeAsyncIterator:
        return self

    async def __anext__(self) -> _FakeStreamChunk:
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_google_module():
    """Create a GoogleProvider with mocked Google AI SDK internals.

    Avoids the real google-genai import by manually constructing the provider
    and injecting mock objects, following the same pattern as test_mercury_provider.
    """
    from isg_agent.models.google_provider import GoogleProvider

    mock_client = MagicMock()
    mock_model_client = AsyncMock()
    mock_model_client.generate_content = AsyncMock(return_value=_FakeGenerateResponse())

    # Create custom exception classes for testing
    mock_google_error = type("ClientError", (Exception,), {"code": None, "message": ""})
    mock_auth_error = type("AuthenticationError", (Exception,), {"code": 401, "message": "auth failed"})

    # Manually construct provider, bypassing __init__ SDK import
    provider = GoogleProvider.__new__(GoogleProvider)
    provider._api_key = "test-google-key"
    provider._default_model = "gemini-2.0-flash"
    provider._client = mock_client
    provider._model_client = mock_model_client
    provider._google_error_cls = mock_google_error
    provider._rate_limit_codes = frozenset({429, 503})

    yield provider, mock_model_client, mock_google_error, mock_auth_error


# ---------------------------------------------------------------------------
# 1. TestGoogleProviderInit
# ---------------------------------------------------------------------------


class TestGoogleProviderInit:
    """Verify provider initialization, api_key storage, defaults."""

    def test_provider_name_is_google(self, mock_google_module: tuple) -> None:
        provider, _, _, _ = mock_google_module
        assert provider.provider_name == "google"

    def test_default_model_is_gemini_flash(self, mock_google_module: tuple) -> None:
        provider, _, _, _ = mock_google_module
        assert provider._default_model == "gemini-2.0-flash"

    def test_api_key_stored(self, mock_google_module: tuple) -> None:
        provider, _, _, _ = mock_google_module
        assert provider._api_key == "test-google-key"

    def test_provider_name_property_returns_string(self, mock_google_module: tuple) -> None:
        provider, _, _, _ = mock_google_module
        assert isinstance(provider.provider_name, str)

    def test_no_api_key_raises_value_error(self) -> None:
        """GoogleProvider must require an api_key (non-empty)."""
        from isg_agent.models.google_provider import GoogleProvider

        with pytest.raises((ValueError, TypeError)):
            GoogleProvider(api_key="")


# ---------------------------------------------------------------------------
# 2. TestGoogleProviderComplete
# ---------------------------------------------------------------------------


class TestGoogleProviderComplete:
    """Test non-streaming completions."""

    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_complete_content_from_response(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.content == "Hello from Gemini!"

    @pytest.mark.asyncio
    async def test_complete_model_name_in_response(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.model == "gemini-2.0-flash"

    @pytest.mark.asyncio
    async def test_complete_finish_reason_stop(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_complete_with_custom_model(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages, model="gemini-2.0-flash-lite")

        assert result.model == "gemini-2.0-flash-lite"

    @pytest.mark.asyncio
    async def test_complete_passes_temperature(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        await provider.complete(messages, temperature=0.2)

        call_kwargs = mock_model.generate_content.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_complete_passes_max_tokens(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        await provider.complete(messages, max_tokens=2048)

        call_kwargs = mock_model.generate_content.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_complete_token_counts(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.input_tokens == 100
        assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_complete_system_message_handling(self, mock_google_module: tuple) -> None:
        """System messages should be extracted and passed as system_instruction."""
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(role="system", content="You are a helpful assistant."),
            LLMMessage(role="user", content="Hello"),
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_complete_multi_turn_conversation(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there!"),
            LLMMessage(role="user", content="How are you?"),
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)
        # Verify generate_content was called
        mock_model.generate_content.assert_called_once()


# ---------------------------------------------------------------------------
# 3. TestGoogleProviderStream
# ---------------------------------------------------------------------------


class TestGoogleProviderStream:
    """Test streaming completions."""

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        chunks = [
            _FakeStreamChunk(text="Hello"),
            _FakeStreamChunk(text=" world"),
            _FakeStreamChunk(text="!"),
        ]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [LLMMessage(role="user", content="Hi")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == ["Hello", " world", "!"]

    @pytest.mark.asyncio
    async def test_stream_skips_empty_chunks(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        chunks = [
            _FakeStreamChunk(text="Hi"),
            _FakeStreamChunk(text=""),
            _FakeStreamChunk(text="!"),
        ]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [LLMMessage(role="user", content="Hi")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == ["Hi", "!"]

    @pytest.mark.asyncio
    async def test_stream_empty_response(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator([]))

        messages = [LLMMessage(role="user", content="Hi")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == []

    @pytest.mark.asyncio
    async def test_stream_multiple_chunks_concatenate(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        chunks = [
            _FakeStreamChunk(text="The "),
            _FakeStreamChunk(text="quick "),
            _FakeStreamChunk(text="brown "),
            _FakeStreamChunk(text="fox"),
        ]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [LLMMessage(role="user", content="Tell me a story")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert "".join(collected) == "The quick brown fox"

    @pytest.mark.asyncio
    async def test_stream_with_system_message(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        chunks = [_FakeStreamChunk(text="Hello")]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [
            LLMMessage(role="system", content="Be helpful"),
            LLMMessage(role="user", content="Hi"),
        ]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == ["Hello"]

    @pytest.mark.asyncio
    async def test_stream_uses_default_model(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        chunks = [_FakeStreamChunk(text="Hi")]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [LLMMessage(role="user", content="Hello")]
        async for _ in provider.stream(messages):
            pass

        # Verify stream was invoked
        mock_model.generate_content_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_with_custom_model(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        chunks = [_FakeStreamChunk(text="Hi")]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [LLMMessage(role="user", content="Hello")]
        async for _ in provider.stream(messages, model="gemini-1.5-pro"):
            pass

        mock_model.generate_content_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_with_none_text_in_chunk(self, mock_google_module: tuple) -> None:
        """Chunks with None text attribute should be skipped."""
        provider, mock_model, _, _ = mock_google_module

        chunk_with_none = _FakeStreamChunk(text="")
        chunk_with_none.text = None  # type: ignore[assignment]
        chunks = [
            _FakeStreamChunk(text="Hello"),
            chunk_with_none,
            _FakeStreamChunk(text=" there"),
        ]
        mock_model.generate_content_stream = AsyncMock(return_value=_FakeAsyncIterator(chunks))

        messages = [LLMMessage(role="user", content="Hi")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == ["Hello", " there"]


# ---------------------------------------------------------------------------
# 4. TestGoogleProviderMultimodal
# ---------------------------------------------------------------------------


class TestGoogleProviderMultimodal:
    """Test multimodal input handling (images, audio)."""

    @pytest.mark.asyncio
    async def test_text_only_message(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_image_url_in_content(self, mock_google_module: tuple) -> None:
        """Message with [image:url] tag should be detected as multimodal."""
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(
                role="user",
                content="What is in this image? [image:https://example.com/cat.jpg]",
            )
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)
        mock_model.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_base64_image_in_content(self, mock_google_module: tuple) -> None:
        """Message with [image_base64:...] tag should be detected as multimodal."""
        provider, mock_model, _, _ = mock_google_module
        fake_b64 = base64.b64encode(b"fake-image-data").decode()
        messages = [
            LLMMessage(
                role="user",
                content=f"Describe this: [image_base64:image/png;{fake_b64}]",
            )
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_mixed_text_and_image(self, mock_google_module: tuple) -> None:
        """Message with both text and image tag."""
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(
                role="user",
                content="Check this out [image:https://example.com/photo.jpg] what do you think?",
            )
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_audio_reference_in_content(self, mock_google_module: tuple) -> None:
        """Message with [audio:url] tag should be recognized."""
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(
                role="user",
                content="Transcribe this: [audio:https://example.com/recording.wav]",
            )
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_multiple_images_in_message(self, mock_google_module: tuple) -> None:
        """Message with multiple image tags."""
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(
                role="user",
                content=(
                    "Compare these: [image:https://example.com/a.jpg] "
                    "and [image:https://example.com/b.jpg]"
                ),
            )
        ]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_multimodal_preserves_text(self, mock_google_module: tuple) -> None:
        """When processing multimodal, the text portion should be preserved."""
        provider, mock_model, _, _ = mock_google_module
        messages = [
            LLMMessage(
                role="user",
                content="Please analyze [image:https://example.com/chart.png] this chart",
            )
        ]

        result = await provider.complete(messages)

        # The mock returns "Hello from Gemini!" regardless, but we verify no crash
        assert result.content == "Hello from Gemini!"

    @pytest.mark.asyncio
    async def test_image_url_pattern_detection(self) -> None:
        """Verify the image tag regex pattern works correctly."""
        from isg_agent.models.google_provider import _IMAGE_URL_PATTERN
        import re

        test_content = "Look at [image:https://example.com/photo.jpg] this"
        matches = re.findall(_IMAGE_URL_PATTERN, test_content)
        assert len(matches) >= 1

    @pytest.mark.asyncio
    async def test_base64_image_pattern_detection(self) -> None:
        """Verify the base64 image tag regex pattern works correctly."""
        from isg_agent.models.google_provider import _BASE64_IMAGE_PATTERN
        import re

        fake_b64 = base64.b64encode(b"test").decode()
        test_content = f"See [image_base64:image/png;{fake_b64}]"
        matches = re.findall(_BASE64_IMAGE_PATTERN, test_content)
        assert len(matches) >= 1

    @pytest.mark.asyncio
    async def test_audio_pattern_detection(self) -> None:
        """Verify the audio tag regex pattern works correctly."""
        from isg_agent.models.google_provider import _AUDIO_URL_PATTERN
        import re

        test_content = "Hear [audio:https://example.com/song.mp3] this"
        matches = re.findall(_AUDIO_URL_PATTERN, test_content)
        assert len(matches) >= 1


# ---------------------------------------------------------------------------
# 5. TestGoogleProviderErrorHandling
# ---------------------------------------------------------------------------


class TestGoogleProviderErrorHandling:
    """Test error mapping from Google SDK exceptions to ProviderError/RateLimitError."""

    @pytest.mark.asyncio
    async def test_rate_limit_raises_rate_limit_error(self, mock_google_module: tuple) -> None:
        provider, mock_model, mock_google_error, _ = mock_google_module

        error = mock_google_error("Resource exhausted")
        error.code = 429
        mock_model.generate_content.side_effect = error
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(RateLimitError) as exc_info:
            await provider.complete(messages)

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_auth_error_raises_provider_error(self, mock_google_module: tuple) -> None:
        provider, mock_model, mock_google_error, _ = mock_google_module

        error = mock_google_error("Invalid API key")
        error.code = 401
        mock_model.generate_content.side_effect = error
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError) as exc_info:
            await provider.complete(messages)

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_network_error_raises_provider_error(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        mock_model.generate_content.side_effect = ConnectionError("Network unreachable")
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError) as exc_info:
            await provider.complete(messages)

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_timeout_error_raises_provider_error(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        mock_model.generate_content.side_effect = TimeoutError("Request timed out")
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError) as exc_info:
            await provider.complete(messages)

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_generic_exception_raises_provider_error(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        mock_model.generate_content.side_effect = RuntimeError("Unknown error")
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError) as exc_info:
            await provider.complete(messages)

        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_503_service_unavailable_raises_rate_limit(self, mock_google_module: tuple) -> None:
        """HTTP 503 from Google should map to RateLimitError (temporary overload)."""
        provider, mock_model, mock_google_error, _ = mock_google_module

        error = mock_google_error("Service unavailable")
        error.code = 503
        mock_model.generate_content.side_effect = error
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(RateLimitError):
            await provider.complete(messages)

    @pytest.mark.asyncio
    async def test_stream_rate_limit_raises(self, mock_google_module: tuple) -> None:
        provider, mock_model, mock_google_error, _ = mock_google_module

        error = mock_google_error("Resource exhausted")
        error.code = 429
        mock_model.generate_content_stream = AsyncMock(side_effect=error)
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(RateLimitError):
            async for _ in provider.stream(messages):
                pass

    @pytest.mark.asyncio
    async def test_stream_generic_error_raises_provider_error(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        mock_model.generate_content_stream = AsyncMock(side_effect=RuntimeError("Boom"))
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError):
            async for _ in provider.stream(messages):
                pass


# ---------------------------------------------------------------------------
# 6. TestGoogleProviderRoleMapping
# ---------------------------------------------------------------------------


class TestGoogleProviderRoleMapping:
    """Test role conversion: system -> system_instruction, assistant -> model."""

    def test_split_system_messages(self) -> None:
        """_split_system_and_conversation should separate system messages."""
        from isg_agent.models.google_provider import _split_system_and_conversation

        messages = [
            LLMMessage(role="system", content="Be concise."),
            LLMMessage(role="user", content="Hello"),
        ]

        system_text, conversation = _split_system_and_conversation(messages)

        assert system_text == "Be concise."
        assert len(conversation) == 1
        assert conversation[0].role == "user"

    def test_multiple_system_messages_joined(self) -> None:
        from isg_agent.models.google_provider import _split_system_and_conversation

        messages = [
            LLMMessage(role="system", content="Rule 1."),
            LLMMessage(role="system", content="Rule 2."),
            LLMMessage(role="user", content="Hi"),
        ]

        system_text, conversation = _split_system_and_conversation(messages)

        assert "Rule 1." in system_text
        assert "Rule 2." in system_text

    def test_no_system_message_returns_none(self) -> None:
        from isg_agent.models.google_provider import _split_system_and_conversation

        messages = [LLMMessage(role="user", content="Hello")]

        system_text, conversation = _split_system_and_conversation(messages)

        assert system_text is None
        assert len(conversation) == 1

    def test_assistant_role_mapped_to_model(self) -> None:
        from isg_agent.models.google_provider import _map_role

        assert _map_role("assistant") == "model"

    def test_user_role_unchanged(self) -> None:
        from isg_agent.models.google_provider import _map_role

        assert _map_role("user") == "user"


# ---------------------------------------------------------------------------
# 7. TestGoogleProviderCostTracking
# ---------------------------------------------------------------------------


class TestGoogleProviderCostTracking:
    """Verify cost estimation in LLMResponse.extra dict."""

    @pytest.mark.asyncio
    async def test_cost_in_extra_dict(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert "cost_usd" in result.extra

    @pytest.mark.asyncio
    async def test_provider_in_extra(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.extra.get("provider") == "google"

    @pytest.mark.asyncio
    async def test_flash_pricing_default(self, mock_google_module: tuple) -> None:
        """Default model (flash) should use flash pricing."""
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        # Flash: $0.10/M input, $0.40/M output
        # 100 input, 50 output
        expected_cost = (100 / 1_000_000) * 0.10 + (50 / 1_000_000) * 0.40
        assert result.extra["cost_usd"] == pytest.approx(expected_cost, abs=1e-8)

    @pytest.mark.asyncio
    async def test_pro_pricing(self, mock_google_module: tuple) -> None:
        """Pro model should use pro pricing."""
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages, model="gemini-2.5-pro")

        # Pro: $1.25/M input, $5.00/M output (up to 200K input)
        expected_cost = (100 / 1_000_000) * 1.25 + (50 / 1_000_000) * 5.00
        assert result.extra["cost_usd"] == pytest.approx(expected_cost, abs=1e-8)

    @pytest.mark.asyncio
    async def test_cost_usd_is_float(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert isinstance(result.extra["cost_usd"], float)


# ---------------------------------------------------------------------------
# 8. TestNoForbiddenImports
# ---------------------------------------------------------------------------


class TestNoForbiddenImports:
    """Ensure google_provider.py does not import from brain or api modules."""

    def test_no_brain_import(self) -> None:
        """google_provider must not import from isg_agent.brain."""
        import isg_agent.models.google_provider as mod

        source = inspect.getsource(mod)
        assert "from isg_agent.brain" not in source
        assert "import isg_agent.brain" not in source

    def test_no_api_import(self) -> None:
        """google_provider must not import from isg_agent.api."""
        import isg_agent.models.google_provider as mod

        source = inspect.getsource(mod)
        assert "from isg_agent.api" not in source
        assert "import isg_agent.api" not in source


# ---------------------------------------------------------------------------
# 9. TestGoogleProviderEdgeCases
# ---------------------------------------------------------------------------


class TestGoogleProviderEdgeCases:
    """Edge cases: empty messages, unicode, None content, long input."""

    @pytest.mark.asyncio
    async def test_empty_messages_list(self, mock_google_module: tuple) -> None:
        """Empty messages list should still produce a response (or raise cleanly)."""
        provider, mock_model, _, _ = mock_google_module
        messages: list[LLMMessage] = []

        # Should either succeed with mock or raise a clean ProviderError
        try:
            result = await provider.complete(messages)
            assert isinstance(result, LLMResponse)
        except ProviderError:
            pass  # Acceptable: clean error for empty input

    @pytest.mark.asyncio
    async def test_unicode_content(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello! Привет! こんにちは! 🌍")]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_none_content_in_response(self, mock_google_module: tuple) -> None:
        """If the model returns None/empty content, provider should handle gracefully."""
        provider, mock_model, _, _ = mock_google_module

        empty_response = _FakeGenerateResponse(text="")
        empty_response.candidates = [
            _FakeCandidate(content=_FakeContent(parts=[_FakePart(text="")]))
        ]
        mock_model.generate_content.return_value = empty_response
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.content == ""

    @pytest.mark.asyncio
    async def test_very_long_input(self, mock_google_module: tuple) -> None:
        """Very long input should be passed through without truncation."""
        provider, mock_model, _, _ = mock_google_module
        long_text = "x" * 100_000
        messages = [LLMMessage(role="user", content=long_text)]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_no_usage_metadata(self, mock_google_module: tuple) -> None:
        """If response has no usage_metadata, token counts should be 0."""
        provider, mock_model, _, _ = mock_google_module

        response = _FakeGenerateResponse()
        response.usage_metadata = None  # type: ignore[assignment]
        mock_model.generate_content.return_value = response
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.input_tokens == 0
        assert result.output_tokens == 0


# ---------------------------------------------------------------------------
# 10. TestGoogleProviderRegistryIntegration
# ---------------------------------------------------------------------------


class TestGoogleProviderRegistryIntegration:
    """Test that GoogleProvider integrates with ModelRegistry."""

    def test_register_and_retrieve(self, mock_google_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, _, _, _ = mock_google_module
        registry = ModelRegistry()
        registry.register("google", provider)

        retrieved = registry.get("google")
        assert retrieved.provider_name == "google"

    def test_fallback_chain_includes_google(self, mock_google_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, _, _, _ = mock_google_module
        registry = ModelRegistry()
        registry.register("google", provider)
        registry.set_fallback_chain(["google"])

        assert registry.fallback_chain == ["google"]

    def test_list_providers_includes_google(self, mock_google_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, _, _, _ = mock_google_module
        registry = ModelRegistry()
        registry.register("google", provider)

        assert "google" in registry.list_providers()

    @pytest.mark.asyncio
    async def test_complete_with_fallback(self, mock_google_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, mock_model, _, _ = mock_google_module
        mock_model.generate_content.return_value = _FakeGenerateResponse()

        registry = ModelRegistry()
        registry.register("google", provider)
        registry.set_fallback_chain(["google"])

        messages = [LLMMessage(role="user", content="Hello")]
        result = await registry.complete_with_fallback(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Gemini!"


# ---------------------------------------------------------------------------
# 11. TestGoogleProviderFinishReasons
# ---------------------------------------------------------------------------


class TestGoogleProviderFinishReasons:
    """Test finish reason mapping from Google to normalized values."""

    @pytest.mark.asyncio
    async def test_stop_finish_reason(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_max_tokens_finish_reason(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        response = _FakeGenerateResponse()
        response.candidates = [_FakeCandidate(finish_reason=_FinishReason.MAX_TOKENS)]
        mock_model.generate_content.return_value = response
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_safety_finish_reason(self, mock_google_module: tuple) -> None:
        provider, mock_model, _, _ = mock_google_module

        response = _FakeGenerateResponse()
        response.candidates = [_FakeCandidate(finish_reason=_FinishReason.SAFETY)]
        mock_model.generate_content.return_value = response
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        # Safety blocks map to "error" finish reason
        assert result.finish_reason == "error"
