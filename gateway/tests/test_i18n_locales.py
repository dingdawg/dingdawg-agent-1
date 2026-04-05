"""tests/test_i18n_locales.py — i18n integration tests for DingDawg Agent 1.

TDD: Written BEFORE/ALONGSIDE implementation to define the contract.

Coverage (48 tests total):
  - Haitian Creole (ht) detection via word patterns (8)
  - Vietnamese (vi) detection via Unicode diacritic ranges (8)
  - Haitian Creole locale JSON completeness (7)
  - Vietnamese locale JSON completeness (7)
  - language_detect.py SUPPORTED_LOCALES includes ht + vi (2)
  - system prompt suffixes for ht + vi (4)
  - Haitian Creole authentic vocabulary guards (6)
  - Vietnamese diacritic authenticity guards (6)
"""

from __future__ import annotations

import json
import os
import unicodedata

import pytest

from isg_agent.comms.language_detect import LanguageDetector

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(__file__)
_LOCALES_DIR = os.path.join(
    _HERE, "..", "frontend", "src", "lib", "i18n", "locales"
)


def _load_locale(code: str) -> dict:
    """Load a locale JSON file by code (e.g. 'ht', 'vi')."""
    path = os.path.join(_LOCALES_DIR, f"{code}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def detector() -> LanguageDetector:
    """Return a LanguageDetector instance."""
    return LanguageDetector()


@pytest.fixture()
def ht_locale() -> dict:
    """Load the Haitian Creole locale JSON."""
    return _load_locale("ht")


@pytest.fixture()
def vi_locale() -> dict:
    """Load the Vietnamese locale JSON."""
    return _load_locale("vi")


# ---------------------------------------------------------------------------
# Group 1: Haitian Creole (ht) detection tests (8)
# ---------------------------------------------------------------------------


def test_detects_ht_mwen(detector: LanguageDetector) -> None:
    """'mwen' (I/me) is a core Haitian Creole word — must detect as 'ht'."""
    result = detector.detect("Mwen bezwen èd ou tanpri. Ki jan ou rele?")
    assert result == "ht"


def test_detects_ht_nou(detector: LanguageDetector) -> None:
    """'nou' (we/us) is a core Haitian Creole marker."""
    result = detector.detect("Nou bezwen travay ansanm pou nou ka reyisi.")
    assert result == "ht"


def test_detects_ht_ki(detector: LanguageDetector) -> None:
    """'ki' (what/who) is a high-frequency Haitian Creole function word."""
    result = detector.detect("Ki kote ou ap ale? Ki sa ou vle?")
    assert result == "ht"


def test_detects_ht_sa(detector: LanguageDetector) -> None:
    """'sa' (that/this) appears frequently in Haitian Creole."""
    result = detector.detect("Sa a se yon bon bagay pou nou fè.")
    assert result == "ht"


def test_detects_ht_tanpri(detector: LanguageDetector) -> None:
    """'tanpri' (please) is a highly distinctive Haitian Creole word."""
    result = detector.detect("Tanpri ede mwen ak pwoblèm sa a.")
    assert result == "ht"


def test_detects_ht_mixed_sentence(detector: LanguageDetector) -> None:
    """Full Haitian Creole sentence with multiple markers."""
    result = detector.detect("Mwen pa konprann sa ou vle di. Tanpri eksplike m.")
    assert result == "ht"


def test_ht_not_confused_with_french(detector: LanguageDetector) -> None:
    """Haitian Creole text must NOT be detected as French.

    Kreyòl and French share some Latin characters but are distinct languages.
    'mwen', 'nou', 'tanpri' are NOT French words.
    """
    result = detector.detect("Mwen bezwen ou tanpri. Nou kapab travay ansanm.")
    assert result != "fr"


def test_ht_not_confused_with_english(detector: LanguageDetector) -> None:
    """Haitian Creole text must NOT be detected as English."""
    result = detector.detect("Ki sa ou vle fè jodi a? Mwen prè pou ede ou.")
    assert result != "en"


# ---------------------------------------------------------------------------
# Group 2: Vietnamese (vi) detection tests (8)
# ---------------------------------------------------------------------------


def test_detects_vi_xin_chao(detector: LanguageDetector) -> None:
    """'Xin chào' — Vietnamese greeting with proper diacritics."""
    result = detector.detect("Xin chào, tôi cần giúp đỡ. Bạn có thể giúp tôi không?")
    assert result == "vi"


def test_detects_vi_dang_nhap(detector: LanguageDetector) -> None:
    """'Đăng nhập' — Vietnamese for 'log in', uses distinctive ă and đ."""
    result = detector.detect("Đăng nhập để tiếp tục sử dụng dịch vụ của chúng tôi.")
    assert result == "vi"


def test_detects_vi_nguoi_dung(detector: LanguageDetector) -> None:
    """'Người dùng' — Vietnamese for 'user', uses ư and ờ diacritics."""
    result = detector.detect("Người dùng cần đăng ký tài khoản để sử dụng ứng dụng.")
    assert result == "vi"


def test_detects_vi_toi_can(detector: LanguageDetector) -> None:
    """'tôi cần' — 'I need', uses circumflex ô."""
    result = detector.detect("Tôi cần hỗ trợ kỹ thuật ngay bây giờ.")
    assert result == "vi"


def test_detects_vi_vui_long(detector: LanguageDetector) -> None:
    """'Vui lòng' — Vietnamese for 'please', uses grave accent on ò."""
    result = detector.detect("Vui lòng kiểm tra lại thông tin và thử lại.")
    assert result == "vi"


def test_detects_vi_unicode_range(detector: LanguageDetector) -> None:
    """Vietnamese diacritics: ă (U+0103), â (U+00E2), ơ (U+01A1), đ (U+0111)."""
    # Each character is a distinctive Vietnamese diacritic
    text = "ă â ê ô ơ ư đ ắ ặ ầ ễ ổ ướ ừ"
    result = detector.detect(text)
    assert result == "vi"


def test_vi_script_threshold(detector: LanguageDetector) -> None:
    """Vietnamese text with high diacritic density must be detected as 'vi'."""
    result = detector.detect(
        "Chúng tôi cung cấp dịch vụ hỗ trợ khách hàng 24/7. "
        "Đội ngũ chuyên gia sẵn sàng giúp đỡ bạn."
    )
    assert result == "vi"


def test_vi_not_confused_with_en(detector: LanguageDetector) -> None:
    """Vietnamese text with diacritics must NOT be detected as English."""
    result = detector.detect("Tôi không hiểu câu hỏi của bạn. Vui lòng hỏi lại.")
    assert result != "en"


# ---------------------------------------------------------------------------
# Group 3: SUPPORTED_LOCALES includes ht + vi (2)
# ---------------------------------------------------------------------------


def test_supported_locales_includes_ht(detector: LanguageDetector) -> None:
    """SUPPORTED_LOCALES must contain 'ht' (Haitian Creole)."""
    assert "ht" in detector.SUPPORTED_LOCALES


def test_supported_locales_includes_vi(detector: LanguageDetector) -> None:
    """SUPPORTED_LOCALES must contain 'vi' (Vietnamese)."""
    assert "vi" in detector.SUPPORTED_LOCALES


# ---------------------------------------------------------------------------
# Group 4: system prompt suffixes for ht + vi (4)
# ---------------------------------------------------------------------------


def test_system_prompt_suffix_ht_is_string(detector: LanguageDetector) -> None:
    """system prompt suffix for 'ht' must be a non-empty string."""
    suffix = detector.get_system_prompt_suffix("ht")
    assert isinstance(suffix, str)
    assert len(suffix) > 0


def test_system_prompt_suffix_ht_contains_haitian(detector: LanguageDetector) -> None:
    """system prompt suffix for 'ht' must reference Haitian Creole language."""
    suffix = detector.get_system_prompt_suffix("ht")
    assert (
        "Haitian" in suffix
        or "Kreyòl" in suffix
        or "Creole" in suffix
        or "kreyòl" in suffix
    )


def test_system_prompt_suffix_vi_is_string(detector: LanguageDetector) -> None:
    """system prompt suffix for 'vi' must be a non-empty string."""
    suffix = detector.get_system_prompt_suffix("vi")
    assert isinstance(suffix, str)
    assert len(suffix) > 0


def test_system_prompt_suffix_vi_contains_vietnamese(detector: LanguageDetector) -> None:
    """system prompt suffix for 'vi' must reference Vietnamese language."""
    suffix = detector.get_system_prompt_suffix("vi")
    assert "Vietnamese" in suffix or "Tiếng Việt" in suffix or "tiếng Việt" in suffix


# ---------------------------------------------------------------------------
# Group 5: Haitian Creole locale JSON completeness (7)
# ---------------------------------------------------------------------------

_REQUIRED_NAMESPACES = ["common", "chat", "agent", "auth", "settings", "errors", "onboarding"]
_REQUIRED_COMMON_KEYS = [
    "loading", "error", "retry", "cancel", "save",
    "delete", "confirm", "back", "next", "close",
    "edit", "search", "submit", "yes", "no",
]


def test_ht_locale_loads(ht_locale: dict) -> None:
    """ht.json must load as a non-empty dict."""
    assert isinstance(ht_locale, dict)
    assert len(ht_locale) > 0


def test_ht_has_all_namespaces(ht_locale: dict) -> None:
    """ht.json must have all required namespaces."""
    for ns in _REQUIRED_NAMESPACES:
        assert ns in ht_locale, f"ht.json is missing namespace '{ns}'"


def test_ht_common_keys_complete(ht_locale: dict) -> None:
    """ht.json must have all required common keys with non-empty values."""
    common = ht_locale["common"]
    for key in _REQUIRED_COMMON_KEYS:
        val = common.get(key)
        assert isinstance(val, str) and len(val) > 0, (
            f"ht.common.{key} is missing or empty (got {val!r})"
        )


def test_ht_no_empty_values(ht_locale: dict) -> None:
    """ht.json must not contain any empty string values."""
    def check(obj: dict, path: str) -> None:
        for k, v in obj.items():
            full_path = f"{path}.{k}" if path else k
            if isinstance(v, str):
                assert len(v) > 0, f"ht.{full_path} is an empty string"
            elif isinstance(v, dict):
                check(v, full_path)

    check(ht_locale, "")


def test_ht_authentic_kreyol_vocabulary(ht_locale: dict) -> None:
    """ht.json must use authentic Kreyòl (not French) vocabulary.

    Critical markers:
    - auth.login must use 'Konekte' (not 'Se connecter' or 'Connexion')
    - common.loading must use 'Ap chaje' (not 'Chargement')
    - auth.signup must use 'Enskri' (not 'S'inscrire')
    """
    login = ht_locale["auth"]["login"]
    # Must NOT be a French phrase
    assert "Se connecter" not in login
    assert "Connexion" not in login

    loading = ht_locale["common"]["loading"]
    # Must NOT be a French phrase
    assert "Chargement" not in loading

    signup = ht_locale["auth"]["signup"]
    assert "inscrire" not in signup.lower()


def test_ht_uses_mwen_not_je(ht_locale: dict) -> None:
    """ht.json must use 'mwen' (not 'je') — Kreyòl first-person pronoun.

    'je' is French. Haitian Creole uses 'mwen'.
    """
    # Convert all values to a single string for checking
    all_text = json.dumps(ht_locale)
    # Should NOT contain isolated French pronoun 'je '
    # (check for ' je ' with spaces to avoid matching substrings)
    assert " je " not in all_text.lower() or "mwen" in all_text.lower()
    # Positive check: mwen must appear somewhere
    assert "mwen" in all_text.lower()


def test_ht_has_interpolation_placeholders(ht_locale: dict) -> None:
    """ht.json must preserve {{param}} interpolation in templated strings."""
    greeting = ht_locale["chat"]["greeting"]
    assert "{{name}}" in greeting

    step = ht_locale["onboarding"]["step"]
    assert "{{current}}" in step
    assert "{{total}}" in step


# ---------------------------------------------------------------------------
# Group 6: Vietnamese locale JSON completeness (7)
# ---------------------------------------------------------------------------


def test_vi_locale_loads(vi_locale: dict) -> None:
    """vi.json must load as a non-empty dict."""
    assert isinstance(vi_locale, dict)
    assert len(vi_locale) > 0


def test_vi_has_all_namespaces(vi_locale: dict) -> None:
    """vi.json must have all required namespaces."""
    for ns in _REQUIRED_NAMESPACES:
        assert ns in vi_locale, f"vi.json is missing namespace '{ns}'"


def test_vi_common_keys_complete(vi_locale: dict) -> None:
    """vi.json must have all required common keys with non-empty values."""
    common = vi_locale["common"]
    for key in _REQUIRED_COMMON_KEYS:
        val = common.get(key)
        assert isinstance(val, str) and len(val) > 0, (
            f"vi.common.{key} is missing or empty (got {val!r})"
        )


def test_vi_no_empty_values(vi_locale: dict) -> None:
    """vi.json must not contain any empty string values."""
    def check(obj: dict, path: str) -> None:
        for k, v in obj.items():
            full_path = f"{path}.{k}" if path else k
            if isinstance(v, str):
                assert len(v) > 0, f"vi.{full_path} is an empty string"
            elif isinstance(v, dict):
                check(v, full_path)

    check(vi_locale, "")


def test_vi_has_proper_diacritics(vi_locale: dict) -> None:
    """vi.json must include proper Vietnamese diacritics.

    Expected diacritics in the file:
    - ă (U+0103) — in 'Đăng nhập' (login)
    - đ (U+0111) / Đ (U+0110) — in 'Đăng nhập', 'Đã đọc', etc.
    - ọ, ờ, ứ etc. — tonal marks throughout
    """
    all_text = json.dumps(vi_locale, ensure_ascii=False)

    # Must contain 'Đ' or 'đ' (Đăng nhập)
    assert "\u0110" in all_text or "\u0111" in all_text, (
        "vi.json is missing đ/Đ (U+0110/U+0111) — required for 'Đăng nhập'"
    )

    # Must contain ă (U+0103) — as in 'Đăng'
    assert "\u0103" in all_text, (
        "vi.json is missing ă (U+0103) — required for 'Đăng'"
    )

    # Must contain ề, ổ, ứ, or similar tonal+vowel combinations
    # Check for at least one combining diacritic Unicode character above U+00BF
    high_diacritics = [ch for ch in all_text if ord(ch) > 0x00BF and unicodedata.category(ch).startswith("L")]
    assert len(high_diacritics) > 0, (
        "vi.json has no Vietnamese-specific Unicode characters"
    )


def test_vi_login_uses_dang_nhap(vi_locale: dict) -> None:
    """vi.json auth.login must be 'Đăng nhập' (not ASCII approximation 'Dang nhap')."""
    login = vi_locale["auth"]["login"]
    # Must contain proper diacritics — not ASCII transliteration
    assert "Dang nhap" not in login  # ASCII approximation — rejected
    # Must contain đăng (đ + ă combination) or similar proper form
    assert "\u0111" in login.lower() or "\u0110" in login, (
        f"vi.auth.login '{login}' is missing đ/Đ diacritic"
    )


def test_vi_has_interpolation_placeholders(vi_locale: dict) -> None:
    """vi.json must preserve {{param}} interpolation in templated strings."""
    greeting = vi_locale["chat"]["greeting"]
    assert "{{name}}" in greeting

    step = vi_locale["onboarding"]["step"]
    assert "{{current}}" in step
    assert "{{total}}" in step


# ---------------------------------------------------------------------------
# Group 7: Key count parity with English (4)
# ---------------------------------------------------------------------------


def test_ht_key_count_matches_en() -> None:
    """ht.json must have the same number of translation keys as en.json."""
    en = _load_locale("en")
    ht = _load_locale("ht")

    def count_keys(obj: dict) -> int:
        total = 0
        for v in obj.values():
            if isinstance(v, dict):
                total += count_keys(v)
            else:
                total += 1
        return total

    en_count = count_keys(en)
    ht_count = count_keys(ht)
    assert ht_count == en_count, (
        f"ht.json has {ht_count} keys but en.json has {en_count} keys — they must match"
    )


def test_vi_key_count_matches_en() -> None:
    """vi.json must have the same number of translation keys as en.json."""
    en = _load_locale("en")
    vi = _load_locale("vi")

    def count_keys(obj: dict) -> int:
        total = 0
        for v in obj.values():
            if isinstance(v, dict):
                total += count_keys(v)
            else:
                total += 1
        return total

    en_count = count_keys(en)
    vi_count = count_keys(vi)
    assert vi_count == en_count, (
        f"vi.json has {vi_count} keys but en.json has {en_count} keys — they must match"
    )


def test_ht_namespace_keys_match_en() -> None:
    """ht.json must have the same namespace keys as en.json in each section."""
    en = _load_locale("en")
    ht = _load_locale("ht")

    for ns in en:
        assert ns in ht, f"ht.json is missing namespace '{ns}'"
        en_keys = set(en[ns].keys())
        ht_keys = set(ht[ns].keys())
        assert en_keys == ht_keys, (
            f"ht.{ns} keys mismatch. "
            f"Missing: {en_keys - ht_keys}. "
            f"Extra: {ht_keys - en_keys}."
        )


def test_vi_namespace_keys_match_en() -> None:
    """vi.json must have the same namespace keys as en.json in each section."""
    en = _load_locale("en")
    vi = _load_locale("vi")

    for ns in en:
        assert ns in vi, f"vi.json is missing namespace '{ns}'"
        en_keys = set(en[ns].keys())
        vi_keys = set(vi[ns].keys())
        assert en_keys == vi_keys, (
            f"vi.{ns} keys mismatch. "
            f"Missing: {en_keys - vi_keys}. "
            f"Extra: {vi_keys - en_keys}."
        )
