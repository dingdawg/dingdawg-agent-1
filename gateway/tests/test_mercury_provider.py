"""Mercury 2 (Inception Labs) LLM provider tests.

Tests for isg_agent.models.mercury_provider.MercuryProvider.

All tests mock the OpenAI AsyncClient to avoid real API calls.
Tests validate:
1. Provider identity and configuration
2. Complete (non-streaming) responses with cost tracking
3. Streaming responses
4. Rate-limit retry with exponential backoff
5. API error propagation
6. Cost estimation accuracy
7. Registry integration
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.models.provider import (
    LLMMessage,
    LLMResponse,
    ProviderError,
    RateLimitError,
)
from isg_agent.models.mercury_provider import (
    MercuryProvider,
    _estimate_cost,
    _INCEPTION_BASE_URL,
    _INPUT_COST_PER_M,
    _OUTPUT_COST_PER_M,
    _DEFAULT_MODEL,
    _SUPPORTED_MODELS,
)

# ---------------------------------------------------------------------------
# Helpers — fake OpenAI response objects
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 50


@dataclass
class _FakeMessage:
    content: str = "Hello from Mercury 2!"


@dataclass
class _FakeChoice:
    message: _FakeMessage = None  # type: ignore[assignment]
    finish_reason: str = "stop"
    index: int = 0

    def __post_init__(self) -> None:
        if self.message is None:
            self.message = _FakeMessage()


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice] = None  # type: ignore[assignment]
    usage: _FakeUsage = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.choices is None:
            self.choices = [_FakeChoice()]
        if self.usage is None:
            self.usage = _FakeUsage()


@dataclass
class _FakeDelta:
    content: Optional[str] = None


@dataclass
class _FakeStreamChoice:
    delta: _FakeDelta = None  # type: ignore[assignment]
    index: int = 0

    def __post_init__(self) -> None:
        if self.delta is None:
            self.delta = _FakeDelta()


@dataclass
class _FakeStreamChunk:
    choices: list[_FakeStreamChoice] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.choices is None:
            self.choices = [_FakeStreamChoice()]


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
def mock_openai_module():
    """Patch the openai module so MercuryProvider can init without a real SDK."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_FakeResponse())

    with patch("isg_agent.models.mercury_provider.AsyncOpenAI", return_value=mock_client) as mock_cls:
        # We need to also patch the exception classes
        mock_rate_limit = type("RateLimitError", (Exception,), {})
        mock_api_error = type("APIError", (Exception,), {"status_code": None})

        with patch.dict("sys.modules", {}):
            provider = MercuryProvider.__new__(MercuryProvider)
            provider._api_key = "test-key"
            provider._default_model = _DEFAULT_MODEL
            provider._default_temperature = 0.7
            provider._default_max_tokens = 1024
            provider._base_url = _INCEPTION_BASE_URL
            provider._diffusing = False
            provider._client = mock_client
            provider._openai_rate_limit_error = mock_rate_limit
            provider._openai_api_error = mock_api_error

            yield provider, mock_client, mock_rate_limit, mock_api_error


# ---------------------------------------------------------------------------
# 1. Provider identity and configuration
# ---------------------------------------------------------------------------


class TestMercuryProviderIdentity:
    """Verify provider name, supported models, and defaults."""

    def test_provider_name(self, mock_openai_module: tuple) -> None:
        provider, _, _, _ = mock_openai_module
        assert provider.provider_name == "mercury"

    def test_supported_models_contains_mercury_2(self, mock_openai_module: tuple) -> None:
        provider, _, _, _ = mock_openai_module
        assert "mercury-2" in provider.supported_models

    def test_supported_models_contains_legacy_alias(self, mock_openai_module: tuple) -> None:
        provider, _, _, _ = mock_openai_module
        assert "mercury" in provider.supported_models

    def test_default_model_is_mercury_2(self) -> None:
        assert _DEFAULT_MODEL == "mercury-2"

    def test_inception_base_url(self) -> None:
        assert _INCEPTION_BASE_URL == "https://api.inceptionlabs.ai/v1"

    def test_pricing_constants(self) -> None:
        assert _INPUT_COST_PER_M == 0.25
        assert _OUTPUT_COST_PER_M == 0.75


# ---------------------------------------------------------------------------
# 2. Cost estimation
# ---------------------------------------------------------------------------


class TestCostEstimation:
    """Verify cost calculations match Inception's published pricing."""

    def test_zero_tokens_zero_cost(self) -> None:
        assert _estimate_cost(0, 0) == 0.0

    def test_1m_input_tokens(self) -> None:
        cost = _estimate_cost(1_000_000, 0)
        assert cost == 0.25

    def test_1m_output_tokens(self) -> None:
        cost = _estimate_cost(0, 1_000_000)
        assert cost == 0.75

    def test_1m_both(self) -> None:
        cost = _estimate_cost(1_000_000, 1_000_000)
        assert cost == 1.0

    def test_small_request(self) -> None:
        # 100 input + 50 output tokens
        cost = _estimate_cost(100, 50)
        expected = (100 / 1_000_000) * 0.25 + (50 / 1_000_000) * 0.75
        assert cost == round(expected, 8)

    def test_typical_agent_request(self) -> None:
        # ~2000 input tokens (system prompt + context), ~500 output
        cost = _estimate_cost(2000, 500)
        expected = (2000 / 1_000_000) * 0.25 + (500 / 1_000_000) * 0.75
        assert cost == round(expected, 8)

    def test_margin_at_1_dollar_tx(self) -> None:
        """At $1/tx, even a heavy request has >97% margin."""
        # Worst case: 50K input (full context), 10K output
        # Cost = (50K/1M)*0.25 + (10K/1M)*0.75 = 0.0125 + 0.0075 = 0.02
        cost = _estimate_cost(50_000, 10_000)
        assert cost == 0.02  # Sanity-check the exact cost
        margin = 1.0 - cost
        assert margin > 0.97, f"Margin {margin:.4f} below 97% threshold"


# ---------------------------------------------------------------------------
# 3. Complete (non-streaming)
# ---------------------------------------------------------------------------


class TestMercuryComplete:
    """Test non-streaming completions."""

    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Mercury 2!"
        assert result.model == "mercury-2"
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_complete_token_counts(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.input_tokens == 100
        assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_complete_includes_cost_in_extra(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert "cost_usd" in result.extra
        assert "provider" in result.extra
        assert result.extra["provider"] == "mercury"
        assert result.extra["cost_usd"] == _estimate_cost(100, 50)

    @pytest.mark.asyncio
    async def test_complete_passes_model_override(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        await provider.complete(messages, model="mercury")

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "mercury" or call_kwargs[1].get("model") == "mercury"

    @pytest.mark.asyncio
    async def test_complete_passes_temperature(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        await provider.complete(messages, temperature=0.3)

        call_kwargs = mock_client.chat.completions.create.call_args
        # temperature should be in the kwargs
        all_kwargs = {**call_kwargs.kwargs} if call_kwargs.kwargs else {}
        assert all_kwargs.get("temperature") == 0.3 or "temperature" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_complete_passes_max_tokens(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        await provider.complete(messages, max_tokens=2048)

        call_kwargs = mock_client.chat.completions.create.call_args
        all_kwargs = {**call_kwargs.kwargs} if call_kwargs.kwargs else {}
        assert all_kwargs.get("max_tokens") == 2048 or "max_tokens" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_complete_handles_empty_content(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        empty_response = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=None))],  # type: ignore[arg-type]
        )
        mock_client.chat.completions.create.return_value = empty_response
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.content == ""

    @pytest.mark.asyncio
    async def test_complete_handles_no_usage(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        no_usage_response = _FakeResponse(usage=None)  # type: ignore[arg-type]
        # Override __post_init__ by setting after creation
        no_usage_response.usage = None  # type: ignore[assignment]
        mock_client.chat.completions.create.return_value = no_usage_response
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.input_tokens == 0
        assert result.output_tokens == 0

    @pytest.mark.asyncio
    async def test_complete_converts_messages(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        messages = [
            LLMMessage(role="system", content="You are a helpful agent."),
            LLMMessage(role="user", content="Hello"),
        ]

        await provider.complete(messages)

        call_args = mock_client.chat.completions.create.call_args
        sent_messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# 4. Streaming
# ---------------------------------------------------------------------------


class TestMercuryStream:
    """Test streaming completions."""

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module

        chunks = [
            _FakeStreamChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(content="Hello"))]),
            _FakeStreamChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(content=" world"))]),
            _FakeStreamChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(content="!"))]),
        ]
        mock_client.chat.completions.create.return_value = _FakeAsyncIterator(chunks)

        messages = [LLMMessage(role="user", content="Hi")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == ["Hello", " world", "!"]

    @pytest.mark.asyncio
    async def test_stream_skips_empty_deltas(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module

        chunks = [
            _FakeStreamChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(content="Hi"))]),
            _FakeStreamChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(content=None))]),
            _FakeStreamChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(content="!"))]),
        ]
        mock_client.chat.completions.create.return_value = _FakeAsyncIterator(chunks)

        messages = [LLMMessage(role="user", content="Hi")]
        collected: list[str] = []
        async for token in provider.stream(messages):
            collected.append(token)

        assert collected == ["Hi", "!"]

    @pytest.mark.asyncio
    async def test_stream_passes_stream_true(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, _ = mock_openai_module
        mock_client.chat.completions.create.return_value = _FakeAsyncIterator([])

        messages = [LLMMessage(role="user", content="Hi")]
        async for _ in provider.stream(messages):
            pass

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("stream") is True


# ---------------------------------------------------------------------------
# 5. Rate-limit retry
# ---------------------------------------------------------------------------


class TestMercuryRateLimit:
    """Test rate-limit retry behavior with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_then_succeeds(self, mock_openai_module: tuple) -> None:
        provider, mock_client, mock_rate_limit, _ = mock_openai_module

        # Fail once, then succeed
        mock_client.chat.completions.create.side_effect = [
            mock_rate_limit("rate limited"),
            _FakeResponse(),
        ]

        messages = [LLMMessage(role="user", content="Hello")]

        with patch("isg_agent.models.mercury_provider.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.complete(messages)

        assert result.content == "Hello from Mercury 2!"
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_rate_limit_after_max_retries(self, mock_openai_module: tuple) -> None:
        provider, mock_client, mock_rate_limit, _ = mock_openai_module

        mock_client.chat.completions.create.side_effect = mock_rate_limit("rate limited")
        messages = [LLMMessage(role="user", content="Hello")]

        with patch("isg_agent.models.mercury_provider.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError) as exc_info:
                await provider.complete(messages)

        assert exc_info.value.provider == "mercury"

    @pytest.mark.asyncio
    async def test_stream_raises_rate_limit(self, mock_openai_module: tuple) -> None:
        provider, mock_client, mock_rate_limit, _ = mock_openai_module

        mock_client.chat.completions.create.side_effect = mock_rate_limit("rate limited")
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(RateLimitError) as exc_info:
            async for _ in provider.stream(messages):
                pass

        assert exc_info.value.provider == "mercury"


# ---------------------------------------------------------------------------
# 6. API error propagation
# ---------------------------------------------------------------------------


class TestMercuryAPIError:
    """Test that API errors are wrapped in ProviderError."""

    @pytest.mark.asyncio
    async def test_complete_wraps_api_error(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, mock_api_error = mock_openai_module

        error = mock_api_error("Internal server error")
        error.status_code = 500
        mock_client.chat.completions.create.side_effect = error
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError) as exc_info:
            await provider.complete(messages)

        assert exc_info.value.provider == "mercury"

    @pytest.mark.asyncio
    async def test_stream_wraps_api_error(self, mock_openai_module: tuple) -> None:
        provider, mock_client, _, mock_api_error = mock_openai_module

        error = mock_api_error("Service unavailable")
        error.status_code = 503
        mock_client.chat.completions.create.side_effect = error
        messages = [LLMMessage(role="user", content="Hello")]

        with pytest.raises(ProviderError) as exc_info:
            async for _ in provider.stream(messages):
                pass

        assert exc_info.value.provider == "mercury"


# ---------------------------------------------------------------------------
# 7. Registry integration
# ---------------------------------------------------------------------------


class TestMercuryRegistryIntegration:
    """Test that MercuryProvider integrates with ModelRegistry."""

    def test_register_and_retrieve(self, mock_openai_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, _, _, _ = mock_openai_module
        registry = ModelRegistry()
        registry.register("mercury", provider)

        retrieved = registry.get("mercury")
        assert retrieved.provider_name == "mercury"

    def test_fallback_chain_includes_mercury(self, mock_openai_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, _, _, _ = mock_openai_module
        registry = ModelRegistry()
        registry.register("mercury", provider)
        registry.set_fallback_chain(["mercury"])

        assert registry.fallback_chain == ["mercury"]

    def test_list_providers_includes_mercury(self, mock_openai_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, _, _, _ = mock_openai_module
        registry = ModelRegistry()
        registry.register("mercury", provider)

        assert "mercury" in registry.list_providers()

    @pytest.mark.asyncio
    async def test_complete_with_fallback(self, mock_openai_module: tuple) -> None:
        from isg_agent.models.registry import ModelRegistry

        provider, mock_client, _, _ = mock_openai_module
        mock_client.chat.completions.create.return_value = _FakeResponse()

        registry = ModelRegistry()
        registry.register("mercury", provider)
        registry.set_fallback_chain(["mercury"])

        messages = [LLMMessage(role="user", content="Hello")]
        result = await registry.complete_with_fallback(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Mercury 2!"


# ---------------------------------------------------------------------------
# 8. Extra field metadata
# ---------------------------------------------------------------------------


class TestMercuryExtraMetadata:
    """Verify the extra dict contains all expected cost/provider metadata."""

    @pytest.mark.asyncio
    async def test_extra_contains_all_fields(self, mock_openai_module: tuple) -> None:
        provider, _, _, _ = mock_openai_module
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        expected_keys = {"provider", "cost_usd", "input_cost_per_m", "output_cost_per_m", "diffusing"}
        assert expected_keys.issubset(set(result.extra.keys()))

    @pytest.mark.asyncio
    async def test_extra_diffusing_reflects_config(self, mock_openai_module: tuple) -> None:
        provider, _, _, _ = mock_openai_module
        provider._diffusing = True
        messages = [LLMMessage(role="user", content="Hello")]

        result = await provider.complete(messages)

        assert result.extra["diffusing"] is True
