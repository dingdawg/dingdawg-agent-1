"""Model registry with fallback chains.

Manages available LLM providers, model selection, and fallback logic
when a primary provider is unavailable or rate-limited.
"""

from __future__ import annotations

import logging
from typing import Optional

from isg_agent.models.provider import LLMMessage, LLMProvider, LLMResponse, ProviderError

__all__ = [
    "ModelRegistry",
    "RegistryError",
    "ProviderNotFoundError",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RegistryError(Exception):
    """Base exception for model registry errors."""


class ProviderNotFoundError(RegistryError):
    """Raised when a requested provider is not registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Provider not registered: {name!r}")


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Manages LLM providers with optional fallback chains.

    Providers are registered by name and can be retrieved individually
    or used in a fallback chain where the registry tries providers in
    order until one succeeds.

    Example::

        registry = ModelRegistry()
        registry.register("openai", OpenAIProvider(api_key="..."))
        registry.register("anthropic", AnthropicProvider(api_key="..."))
        registry.set_fallback_chain(["openai", "anthropic"])

        # Uses primary; falls back to anthropic if openai fails
        response = await registry.complete_with_fallback(messages)
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._fallback_chain: list[str] = []

    # -- Registration -------------------------------------------------------

    def register(self, name: str, provider: LLMProvider) -> None:
        """Register a provider under the given name.

        Parameters
        ----------
        name:
            Unique identifier for this provider (e.g. "openai").
        provider:
            The :class:`LLMProvider` instance to register.
        """
        self._providers[name] = provider
        logger.debug("Registered LLM provider: %s", name)

    def unregister(self, name: str) -> None:
        """Remove a provider from the registry.

        Parameters
        ----------
        name:
            The provider name to remove.

        Raises
        ------
        ProviderNotFoundError
            If the name is not registered.
        """
        if name not in self._providers:
            raise ProviderNotFoundError(name)
        del self._providers[name]
        # Remove from fallback chain if present
        self._fallback_chain = [n for n in self._fallback_chain if n != name]
        logger.debug("Unregistered LLM provider: %s", name)

    def set_fallback_chain(self, chain: list[str]) -> None:
        """Define the ordered fallback chain for :meth:`complete_with_fallback`.

        Parameters
        ----------
        chain:
            Ordered list of provider names.  The first entry is the
            primary; subsequent entries are tried on failure.

        Raises
        ------
        ProviderNotFoundError
            If any name in the chain is not yet registered.
        """
        for name in chain:
            if name not in self._providers:
                raise ProviderNotFoundError(name)
        self._fallback_chain = list(chain)
        logger.debug("Fallback chain set: %s", chain)

    # -- Retrieval ----------------------------------------------------------

    def get(self, name: str) -> LLMProvider:
        """Return the registered provider with the given name.

        Parameters
        ----------
        name:
            The provider name.

        Raises
        ------
        ProviderNotFoundError
            If the name is not registered.
        """
        if name not in self._providers:
            raise ProviderNotFoundError(name)
        return self._providers[name]

    def list_providers(self) -> list[str]:
        """Return names of all registered providers."""
        return list(self._providers.keys())

    @property
    def fallback_chain(self) -> list[str]:
        """The current ordered fallback chain."""
        return list(self._fallback_chain)

    # -- Completions with fallback ------------------------------------------

    async def complete_with_fallback(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        preferred_provider: Optional[str] = None,
    ) -> LLMResponse:
        """Complete a request, falling back to secondary providers on error.

        Tries providers in :attr:`fallback_chain` order (or the
        ``preferred_provider`` first if given) until one succeeds.

        Parameters
        ----------
        messages:
            The conversation history.
        model:
            Model override forwarded to the provider.
        temperature:
            Sampling temperature.
        max_tokens:
            Maximum response tokens.
        preferred_provider:
            Try this provider first before the chain.

        Returns
        -------
        LLMResponse
            The first successful response.

        Raises
        ------
        RegistryError
            If no fallback chain is set and no preferred provider is given,
            or if all providers in the chain fail.
        ProviderNotFoundError
            If the preferred provider is not registered.
        """
        # Build the ordered trial list
        trial_names: list[str] = []
        if preferred_provider:
            if preferred_provider not in self._providers:
                raise ProviderNotFoundError(preferred_provider)
            trial_names.append(preferred_provider)

        for name in self._fallback_chain:
            if name not in trial_names:
                trial_names.append(name)

        if not trial_names:
            raise RegistryError(
                "No providers available. Register at least one provider and set a fallback chain."
            )

        last_error: Exception | None = None
        for name in trial_names:
            provider = self._providers[name]
            try:
                logger.debug("Attempting LLM completion via provider: %s", name)
                response = await provider.complete(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                logger.debug("LLM completion succeeded via provider: %s", name)
                return response
            except ProviderError as exc:
                logger.warning(
                    "Provider %s failed (%s), trying next in chain",
                    name,
                    exc,
                )
                last_error = exc

        raise RegistryError(
            f"All providers exhausted ({', '.join(trial_names)}). "
            "Last error: " + str(last_error)
        ) from last_error
