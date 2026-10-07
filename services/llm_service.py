"""Thin wrapper around the Anthropic API. It only ever returns TEXT; it has no
tools and no ability to act on the system."""
from __future__ import annotations

import logging

from config.settings import settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Base class for LLM problems (all are recoverable via fallback)."""


class LLMUnavailable(LLMError):
    """No key, bad key, timeout, network or server problem."""


class LLMOutputError(LLMError):
    """The model answered, but not with usable structured JSON."""


class AnthropicLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.api_key != "your_key_here"

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover
                raise LLMUnavailable("The 'anthropic' package is not installed.") from e
            self._client = anthropic.Anthropic(
                api_key=self.api_key, timeout=settings.llm_timeout, max_retries=1)
        return self._client

    def complete(self, system: str, user: str) -> str:
        if not self.available:
            raise LLMUnavailable("No API key configured.")
        client = self._get_client()
        import anthropic
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError as e:
            raise LLMUnavailable("The API key was rejected (invalid or expired).") from e
        except anthropic.APITimeoutError as e:
            raise LLMUnavailable("The AI service timed out.") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailable("Could not reach the AI service (network problem).") from e
        except anthropic.APIError as e:
            log.warning("Anthropic API error: %s", type(e).__name__)
            raise LLMUnavailable("The AI service returned an error.") from e
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if not text.strip():
            raise LLMOutputError("Empty response from the model.")
        return text
