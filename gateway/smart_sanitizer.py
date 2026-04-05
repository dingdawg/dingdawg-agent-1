from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Pattern, Sequence


class SmartSanitizerError(Exception):
    """Raised when sanitizer configuration or execution fails."""


def _validate_non_empty_string(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise SmartSanitizerError(
            f"{name} must be a string, got {type(value).__name__}."
        )

    normalized = value.strip()
    if not normalized:
        raise SmartSanitizerError(f"{name} must not be empty.")

    return normalized


def _validate_terms(terms: Sequence[str], name: str) -> list[str]:
    if not isinstance(terms, Sequence) or isinstance(terms, (str, bytes)):
        raise SmartSanitizerError(f"{name} must be a sequence of strings.")

    normalized_terms: list[str] = []
    seen: set[str] = set()

    for index, term in enumerate(terms):
        normalized = _validate_non_empty_string(term, f"{name}[{index}]")
        key = normalized.casefold()
        if key not in seen:
            normalized_terms.append(normalized)
            seen.add(key)

    return normalized_terms


def _whole_phrase_pattern(term: str) -> Pattern[str]:
    """
    Match a complete phrase only, not a substring inside another word.

    Examples:
    - 'worker' matches 'worker'
    - 'AI worker platform' matches that exact phrase
    - 'worker' does not match 'workers' or 'networker'
    """
    escaped = re.escape(term)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


@dataclass(slots=True)
class SmartSanitizer:
    """
    Sanitizes configured sensitive phrases using whole-phrase matching only.
    """

    sensitive_phrases: Sequence[str]
    replacement: str = "[REDACTED]"
    _patterns: list[tuple[str, Pattern[str]]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        validated_replacement = _validate_non_empty_string(
            self.replacement,
            "replacement",
        )
        validated_phrases = _validate_terms(
            self.sensitive_phrases,
            "sensitive_phrases",
        )

        object.__setattr__(self, "replacement", validated_replacement)
        object.__setattr__(self, "sensitive_phrases", validated_phrases)
        object.__setattr__(
            self,
            "_patterns",
            [(phrase, _whole_phrase_pattern(phrase)) for phrase in validated_phrases],
        )

    def sanitize_text(self, text: str) -> str:
        normalized_text = _validate_non_empty_string(text, "text")
        result = normalized_text

        for _, pattern in self._patterns:
            result = pattern.sub(self.replacement, result)

        return result

    def contains_sensitive_phrase(self, text: str) -> bool:
        normalized_text = _validate_non_empty_string(text, "text")
        return any(pattern.search(normalized_text) is not None for _, pattern in self._patterns)

    def matched_phrases(self, text: str) -> list[str]:
        normalized_text = _validate_non_empty_string(text, "text")
        matches: list[str] = []

        for phrase, pattern in self._patterns:
            if pattern.search(normalized_text) is not None:
                matches.append(phrase)

        return matches


def sanitize_text(
    text: str,
    sensitive_phrases: Sequence[str],
    replacement: str = "[REDACTED]",
) -> str:
    sanitizer = SmartSanitizer(
        sensitive_phrases=sensitive_phrases,
        replacement=replacement,
    )
    return sanitizer.sanitize_text(text)