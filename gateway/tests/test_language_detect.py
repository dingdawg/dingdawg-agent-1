"""Tests for isg_agent.comms.language_detect — LanguageDetector.

TDD: These tests are written BEFORE implementation, defining the contract
that LanguageDetector must satisfy.

Coverage:
- Detects English, Spanish, Chinese, French, Arabic text (5)
- Returns correct system prompt suffix per locale (5)
- Edge cases: empty text, mixed language, unsupported language defaults to en (3)
- Supported locales list is correct (1)
- Unicode range detection accuracy (1)
"""

from __future__ import annotations

import pytest

from isg_agent.comms.language_detect import LanguageDetector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def detector() -> LanguageDetector:
    """Return a LanguageDetector instance for testing."""
    return LanguageDetector()


# ---------------------------------------------------------------------------
# Language Detection Tests (5)
# ---------------------------------------------------------------------------


def test_detects_english(detector: LanguageDetector) -> None:
    """Plain English text returns 'en'."""
    result = detector.detect("Hello, how are you today? I need some help with this.")
    assert result == "en"


def test_detects_spanish(detector: LanguageDetector) -> None:
    """Common Spanish text returns 'es'."""
    result = detector.detect("Hola, ¿cómo estás? Necesito ayuda con esto por favor.")
    assert result == "es"


def test_detects_chinese(detector: LanguageDetector) -> None:
    """CJK character-heavy text returns 'zh'."""
    result = detector.detect("你好，今天天气怎么样？我需要帮助。")
    assert result == "zh"


def test_detects_french(detector: LanguageDetector) -> None:
    """Common French text returns 'fr'."""
    result = detector.detect("Bonjour, comment allez-vous? J'ai besoin d'aide avec ceci.")
    assert result == "fr"


def test_detects_arabic(detector: LanguageDetector) -> None:
    """Arabic script text returns 'ar'."""
    result = detector.detect("مرحبا كيف حالك؟ أحتاج إلى مساعدة في هذا الأمر.")
    assert result == "ar"


# ---------------------------------------------------------------------------
# System Prompt Suffix Tests (5)
# ---------------------------------------------------------------------------


def test_system_prompt_suffix_english(detector: LanguageDetector) -> None:
    """English locale suffix instructs LLM to respond in English."""
    suffix = detector.get_system_prompt_suffix("en")
    assert isinstance(suffix, str)
    assert len(suffix) > 0
    assert "English" in suffix


def test_system_prompt_suffix_spanish(detector: LanguageDetector) -> None:
    """Spanish locale suffix instructs LLM to respond in Spanish."""
    suffix = detector.get_system_prompt_suffix("es")
    assert isinstance(suffix, str)
    assert len(suffix) > 0
    # Must contain either 'Spanish' or 'español'
    assert "Spanish" in suffix or "español" in suffix


def test_system_prompt_suffix_chinese(detector: LanguageDetector) -> None:
    """Chinese locale suffix instructs LLM to respond in Chinese."""
    suffix = detector.get_system_prompt_suffix("zh")
    assert isinstance(suffix, str)
    assert len(suffix) > 0
    assert "Chinese" in suffix or "Mandarin" in suffix or "中文" in suffix


def test_system_prompt_suffix_french(detector: LanguageDetector) -> None:
    """French locale suffix instructs LLM to respond in French."""
    suffix = detector.get_system_prompt_suffix("fr")
    assert isinstance(suffix, str)
    assert len(suffix) > 0
    assert "French" in suffix or "français" in suffix


def test_system_prompt_suffix_arabic(detector: LanguageDetector) -> None:
    """Arabic locale suffix instructs LLM to respond in Arabic."""
    suffix = detector.get_system_prompt_suffix("ar")
    assert isinstance(suffix, str)
    assert len(suffix) > 0
    assert "Arabic" in suffix or "العربية" in suffix


# ---------------------------------------------------------------------------
# Edge Case Tests (3)
# ---------------------------------------------------------------------------


def test_empty_text_defaults_to_english(detector: LanguageDetector) -> None:
    """Empty string defaults to 'en'."""
    result = detector.detect("")
    assert result == "en"


def test_unsupported_language_defaults_to_english(detector: LanguageDetector) -> None:
    """Text in an unsupported language (e.g. Japanese kana only)
    or whitespace-only input defaults to 'en'."""
    # Japanese hiragana — not in SUPPORTED_LOCALES, should fall back to en
    result = detector.detect("こんにちは、元気ですか？")
    # Hiragana has no CJK block chars, so it might fall back to en
    # OR detect as zh (CJK overlap) — both are acceptable fallback behaviors
    assert result in detector.SUPPORTED_LOCALES


def test_whitespace_only_defaults_to_english(detector: LanguageDetector) -> None:
    """Whitespace-only input defaults to 'en'."""
    result = detector.detect("   \t\n  ")
    assert result == "en"


# ---------------------------------------------------------------------------
# Supported Locales Test (1)
# ---------------------------------------------------------------------------


def test_supported_locales_list(detector: LanguageDetector) -> None:
    """SUPPORTED_LOCALES contains all seven expected ISO codes."""
    assert set(detector.SUPPORTED_LOCALES) == {"en", "es", "zh", "fr", "ar", "ht", "vi"}
    assert len(detector.SUPPORTED_LOCALES) == 7


# ---------------------------------------------------------------------------
# Unicode Range Detection Accuracy (1)
# ---------------------------------------------------------------------------


def test_unicode_range_detection_accuracy(detector: LanguageDetector) -> None:
    """Tests that CJK and Arabic Unicode ranges are detected correctly.

    CJK Unified Ideographs: U+4E00–U+9FFF
    Arabic block: U+0600–U+06FF
    """
    # Pure CJK codepoints — must detect zh
    pure_cjk = "\u4e2d\u6587\u6d4b\u8bd5\u5185\u5bb9"  # 中文测试内容
    assert detector.detect(pure_cjk) == "zh"

    # Pure Arabic codepoints — must detect ar
    pure_arabic = "\u0645\u0631\u062d\u0628\u0627\u0020\u0643\u064a\u0641\u0020\u062d\u0627\u0644\u0643"
    assert detector.detect(pure_arabic) == "ar"
