"""Tests for security headers middleware and input sanitization middleware.

Covers:
- SecurityHeadersMiddleware: all headers present, X-Request-ID UUID4,
  X-Response-Time numeric, Cache-Control skip for static, overrides,
  HSTS directives, CSP directives, Permissions-Policy, enable_hsts toggle.
- InputSanitizer: HTML stripping, SQL injection, command injection,
  path traversal, null bytes, unicode normalization, nested dict sanitization,
  JSON depth validation, payload size validation.
- InputSanitizerMiddleware: integration tests with a FastAPI test app covering
  webhook skip, health skip, empty body, non-JSON, clean passthrough,
  413 on oversized, 400 on deep JSON.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from isg_agent.middleware.security_headers import (
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)
from isg_agent.middleware.input_sanitizer import (
    InputSanitizer,
    InputSanitizerMiddleware,
)


# ---------------------------------------------------------------------------
# Test app factory — minimal FastAPI app with both middleware layers
# ---------------------------------------------------------------------------


def _create_test_app(
    hsts: bool = True,
    header_overrides: Dict[str, str] | None = None,
    max_json_depth: int = 10,
    max_body_bytes: int = 1_048_576,
) -> FastAPI:
    """Create a minimal FastAPI app with the security middleware stack."""
    app = FastAPI()

    # Input sanitizer (inner middleware — runs after headers)
    app.add_middleware(
        InputSanitizerMiddleware,
        max_json_depth=max_json_depth,
        max_body_bytes=max_body_bytes,
    )

    # Security headers (outer middleware — runs first)
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=hsts,
        overrides=header_overrides,
    )

    @app.get("/test")
    async def test_get() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/static/logo.png")
    async def static_file() -> Dict[str, str]:
        return {"file": "logo.png"}

    @app.get("/icons/favicon.ico")
    async def icon_file() -> Dict[str, str]:
        return {"file": "favicon.ico"}

    @app.post("/api/v1/data")
    async def post_data(request: Request) -> Dict[str, Any]:
        body_bytes = await request.body()
        if not body_bytes:
            return {"received": None}
        try:
            body = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            return {"received": "non-json"}
        return {"received": body}

    @app.post("/health")
    async def health_post(request: Request) -> Dict[str, str]:
        return {"status": "healthy"}

    @app.post("/api/v1/webhooks/stripe")
    async def webhook_stripe(request: Request) -> Dict[str, str]:
        return {"webhook": "received"}

    @app.get("/metrics")
    async def metrics() -> Dict[str, str]:
        return {"metrics": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sanitizer() -> InputSanitizer:
    """Provide an InputSanitizer instance."""
    return InputSanitizer()


@pytest.fixture()
def test_app() -> FastAPI:
    """Provide a test app with default settings."""
    return _create_test_app()


@pytest.fixture()
def no_hsts_app() -> FastAPI:
    """Provide a test app with HSTS disabled."""
    return _create_test_app(hsts=False)


@pytest.fixture()
def override_app() -> FastAPI:
    """Provide a test app with header overrides."""
    return _create_test_app(header_overrides={"X-Frame-Options": "SAMEORIGIN"})


@pytest.fixture()
def small_body_app() -> FastAPI:
    """Provide a test app with a 100-byte body limit."""
    return _create_test_app(max_body_bytes=100)


@pytest.fixture()
def shallow_depth_app() -> FastAPI:
    """Provide a test app with max JSON depth of 3."""
    return _create_test_app(max_json_depth=3)


# ===========================================================================
# PART 1: SecurityHeadersMiddleware tests
# ===========================================================================


class TestSecurityHeadersPresence:
    """All required security headers are present on normal responses."""

    @pytest.mark.asyncio
    async def test_x_content_type_options(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["x-content-type-options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["x-frame-options"] == "DENY"

    @pytest.mark.asyncio
    async def test_x_xss_protection(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["x-xss-protection"] == "1; mode=block"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=(), payment=(self)"

    @pytest.mark.asyncio
    async def test_content_security_policy(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_cache_control(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["cache-control"] == "no-store, no-cache, must-revalidate, private"

    @pytest.mark.asyncio
    async def test_pragma(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["pragma"] == "no-cache"

    @pytest.mark.asyncio
    async def test_all_default_headers_present(self, test_app: FastAPI) -> None:
        """Every header in SECURITY_HEADERS dict appears in the response."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        for header_name in SECURITY_HEADERS:
            assert header_name.lower() in r.headers, f"Missing header: {header_name}"


class TestRequestIdHeader:
    """X-Request-ID header tests."""

    @pytest.mark.asyncio
    async def test_request_id_present(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert "x-request-id" in r.headers

    @pytest.mark.asyncio
    async def test_request_id_is_valid_uuid4(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        request_id = r.headers["x-request-id"]
        parsed = uuid.UUID(request_id, version=4)
        assert str(parsed) == request_id

    @pytest.mark.asyncio
    async def test_request_id_propagated_from_client(self, test_app: FastAPI) -> None:
        """If the client sends X-Request-ID, the server echoes it back."""
        custom_id = "custom-trace-id-12345"
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test", headers={"X-Request-ID": custom_id})
        assert r.headers["x-request-id"] == custom_id

    @pytest.mark.asyncio
    async def test_request_ids_are_unique_across_requests(self, test_app: FastAPI) -> None:
        ids = set()
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            for _ in range(10):
                r = await c.get("/test")
                ids.add(r.headers["x-request-id"])
        assert len(ids) == 10


class TestResponseTimeHeader:
    """X-Response-Time header tests."""

    @pytest.mark.asyncio
    async def test_response_time_present(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert "x-response-time" in r.headers

    @pytest.mark.asyncio
    async def test_response_time_is_numeric_ms(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        value = r.headers["x-response-time"]
        assert value.endswith("ms")
        numeric_part = value.rstrip("ms")
        parsed = float(numeric_part)
        assert parsed >= 0.0

    @pytest.mark.asyncio
    async def test_response_time_is_reasonable(self, test_app: FastAPI) -> None:
        """Response time for a trivial endpoint should be under 5 seconds."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        value = r.headers["x-response-time"]
        ms = float(value.rstrip("ms"))
        assert ms < 5000.0


class TestCacheControlStaticSkip:
    """Cache-Control should be skipped for static asset paths."""

    @pytest.mark.asyncio
    async def test_static_path_no_cache_control(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/static/logo.png")
        # Cache-Control from our middleware should NOT be set
        cache_control = r.headers.get("cache-control", "")
        assert "no-store" not in cache_control

    @pytest.mark.asyncio
    async def test_icons_path_no_cache_control(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/icons/favicon.ico")
        cache_control = r.headers.get("cache-control", "")
        assert "no-store" not in cache_control

    @pytest.mark.asyncio
    async def test_static_path_no_pragma(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/static/logo.png")
        assert r.headers.get("pragma", "") != "no-cache"

    @pytest.mark.asyncio
    async def test_non_static_path_has_cache_control(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["cache-control"] == "no-store, no-cache, must-revalidate, private"

    @pytest.mark.asyncio
    async def test_static_path_still_has_other_security_headers(self, test_app: FastAPI) -> None:
        """Static paths skip cache headers but still get other security headers."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/static/logo.png")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"


class TestHeaderOverrides:
    """Header override mechanism tests."""

    @pytest.mark.asyncio
    async def test_override_replaces_default(self, override_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=override_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.headers["x-frame-options"] == "SAMEORIGIN"

    @pytest.mark.asyncio
    async def test_suppress_header_with_empty_string(self) -> None:
        app = _create_test_app(header_overrides={"Pragma": ""})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/test")
        assert "pragma" not in r.headers

    @pytest.mark.asyncio
    async def test_other_headers_unaffected_by_override(self, override_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=override_app), base_url="http://test") as c:
            r = await c.get("/test")
        # X-Frame-Options is overridden, but others stay default
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


class TestHSTSDirectives:
    """HSTS header directive tests."""

    @pytest.mark.asyncio
    async def test_hsts_present_when_enabled(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        hsts = r.headers["strict-transport-security"]
        assert "max-age=31536000" in hsts

    @pytest.mark.asyncio
    async def test_hsts_includes_subdomains(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        hsts = r.headers["strict-transport-security"]
        assert "includeSubDomains" in hsts

    @pytest.mark.asyncio
    async def test_hsts_includes_preload(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        hsts = r.headers["strict-transport-security"]
        assert "preload" in hsts

    @pytest.mark.asyncio
    async def test_hsts_absent_when_disabled(self, no_hsts_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=no_hsts_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert "strict-transport-security" not in r.headers

    @pytest.mark.asyncio
    async def test_hsts_all_three_directives(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        hsts = r.headers["strict-transport-security"]
        assert hsts == "max-age=31536000; includeSubDomains; preload"


class TestCSPDirectives:
    """Content-Security-Policy directive tests."""

    @pytest.mark.asyncio
    async def test_csp_default_src(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp

    @pytest.mark.asyncio
    async def test_csp_script_src(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp

    @pytest.mark.asyncio
    async def test_csp_style_src(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "style-src 'self' 'unsafe-inline'" in csp

    @pytest.mark.asyncio
    async def test_csp_img_src(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "img-src 'self' data: https:" in csp

    @pytest.mark.asyncio
    async def test_csp_font_src(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "font-src 'self' https://fonts.gstatic.com" in csp

    @pytest.mark.asyncio
    async def test_csp_connect_src_stripe(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "connect-src 'self' https://api.stripe.com" in csp

    @pytest.mark.asyncio
    async def test_csp_frame_ancestors_none(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_csp_base_uri(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "base-uri 'self'" in csp

    @pytest.mark.asyncio
    async def test_csp_form_action(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        csp = r.headers["content-security-policy"]
        assert "form-action 'self'" in csp


# ===========================================================================
# PART 2: InputSanitizer unit tests
# ===========================================================================


class TestHTMLTagStripping:
    """HTML/XSS tag stripping tests."""

    def test_script_tag_removed(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "</script>" not in result
        assert "alert" not in result

    def test_script_tag_with_attributes(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string('<script type="text/javascript">evil()</script>')
        assert "<script" not in result

    def test_img_onerror(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string('<img src="x" onerror="alert(1)">')
        assert "onerror" not in result

    def test_svg_onload(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string('<svg onload="alert(1)">')
        assert "onload" not in result

    def test_iframe_removed(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string('<iframe src="http://evil.com"></iframe>')
        assert "<iframe" not in result

    def test_javascript_protocol(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string('javascript:alert(1)')
        assert "javascript:" not in result

    def test_all_html_tags_stripped(self, sanitizer: InputSanitizer) -> None:
        """ALL HTML tags are stripped to prevent XSS — text content preserved."""
        result = sanitizer.sanitize_string("<b>bold text</b> and <p>paragraph</p>")
        assert "<b>" not in result
        assert "<p>" not in result
        assert "bold text" in result
        assert "paragraph" in result

    def test_expression_css_attack(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("background: expression(alert(1))")
        assert "expression(" not in result


class TestSQLInjectionStripping:
    """SQL injection pattern stripping tests."""

    def test_drop_table(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("'; DROP TABLE users; --")
        assert "DROP TABLE" not in result

    def test_union_select(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("1 UNION SELECT * FROM passwords")
        assert "UNION SELECT" not in result.upper()

    def test_or_1_equals_1(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("admin' OR 1=1 --")
        assert "1=1" not in result or "OR" not in result.upper()

    def test_information_schema(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("SELECT * FROM INFORMATION_SCHEMA.TABLES")
        assert "INFORMATION_SCHEMA" not in result

    def test_sleep_injection(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("1; SELECT SLEEP(10)")
        assert "SLEEP(" not in result.upper()

    def test_sql_comment_at_end(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("admin'--")
        assert result.rstrip() != "admin'--"

    def test_clean_sql_like_text_preserved(self, sanitizer: InputSanitizer) -> None:
        """Normal text that looks vaguely like SQL should pass through."""
        result = sanitizer.sanitize_string("Please select the best union plan")
        assert "select" in result.lower()


class TestCommandInjectionStripping:
    """Command injection pattern stripping tests."""

    def test_semicolon_rm_rf(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("file.txt; rm -rf /")
        assert "rm -rf" not in result

    def test_pipe_cat_passwd(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("input | cat /etc/passwd")
        assert "cat /etc/" not in result

    def test_backtick_command(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("hello `whoami` world")
        assert "`whoami`" not in result

    def test_dollar_paren_command(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("hello $(id) world")
        assert "$(id)" not in result

    def test_shell_path_injection(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("/bin/bash -c 'evil'")
        assert "/bin/bash" not in result

    def test_clean_text_with_semicolon(self, sanitizer: InputSanitizer) -> None:
        """Normal semicolons in text should be preserved."""
        result = sanitizer.sanitize_string("Hello; how are you?")
        assert result == "Hello; how are you?"


class TestPathTraversalStripping:
    """Path traversal pattern stripping tests."""

    def test_dot_dot_slash(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("../../etc/passwd")
        assert "../" not in result

    def test_dot_dot_backslash(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("..\\..\\windows\\system32")
        assert "..\\" not in result

    def test_url_encoded_traversal(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("%2e%2e%2f%2e%2e%2fetc/passwd")
        assert "%2e%2e" not in result.lower()

    def test_etc_passwd_absolute(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.sanitize_string("read /etc/passwd now")
        assert "/etc/passwd" not in result

    def test_clean_relative_path(self, sanitizer: InputSanitizer) -> None:
        """Single dot paths and normal paths should be preserved."""
        result = sanitizer.sanitize_string("./config/settings.json")
        assert result == "./config/settings.json"


class TestNullByteRemoval:
    """Null byte removal tests."""

    def test_literal_null_byte(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.remove_null_bytes("file\x00.txt")
        assert "\x00" not in result
        assert result == "file.txt"

    def test_percent_encoded_null(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.remove_null_bytes("file%00.txt")
        assert "%00" not in result

    def test_backslash_x00(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.remove_null_bytes("file\\x00.txt")
        assert "\\x00" not in result

    def test_backslash_zero(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.remove_null_bytes("file\\0.txt")
        assert "\\0" not in result

    def test_clean_string_unchanged(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.remove_null_bytes("normal text")
        assert result == "normal text"


class TestUnicodeNormalization:
    """Unicode normalization and confusable character tests."""

    def test_fullwidth_less_than(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.normalize_unicode("\uff1cscript\uff1e")
        assert "<script>" in result

    def test_fullwidth_semicolon(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.normalize_unicode("value\uff1b DROP TABLE")
        assert ";" in result

    def test_fullwidth_pipe(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.normalize_unicode("input\uff5ccat")
        assert "|" in result

    def test_smart_quotes_normalized(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.normalize_unicode("\u2018hello\u2019")
        assert result == "'hello'"

    def test_fullwidth_dots(self, sanitizer: InputSanitizer) -> None:
        result = sanitizer.normalize_unicode("\uff0e\uff0e/etc")
        assert result == "../etc"

    def test_nfc_normalization(self, sanitizer: InputSanitizer) -> None:
        """Composed and decomposed forms should normalize to the same NFC string."""
        # e + combining acute accent vs precomposed e-acute
        decomposed = "e\u0301"
        composed = "\u00e9"
        assert sanitizer.normalize_unicode(decomposed) == sanitizer.normalize_unicode(composed)

    def test_sanitize_string_catches_unicode_xss(self, sanitizer: InputSanitizer) -> None:
        """Fullwidth angle brackets should be normalized THEN script tag stripped."""
        result = sanitizer.sanitize_string("\uff1cscript\uff1ealert(1)\uff1c/script\uff1e")
        assert "alert" not in result
        assert "<script>" not in result


class TestNestedDictSanitization:
    """Recursive dictionary sanitization tests."""

    def test_flat_dict(self, sanitizer: InputSanitizer) -> None:
        data = {"name": "<script>evil</script>", "age": 25}
        result = sanitizer.sanitize_dict(data)
        assert "<script>" not in result["name"]
        assert result["age"] == 25

    def test_nested_dict(self, sanitizer: InputSanitizer) -> None:
        data = {"user": {"bio": "<script>xss</script>"}}
        result = sanitizer.sanitize_dict(data)
        assert "<script>" not in result["user"]["bio"]

    def test_list_in_dict(self, sanitizer: InputSanitizer) -> None:
        data = {"tags": ["safe", "<script>evil</script>", "normal"]}
        result = sanitizer.sanitize_dict(data)
        assert "<script>" not in result["tags"][1]
        assert result["tags"][0] == "safe"
        assert result["tags"][2] == "normal"

    def test_deeply_nested(self, sanitizer: InputSanitizer) -> None:
        data = {"a": {"b": {"c": {"d": "<script>deep</script>"}}}}
        result = sanitizer.sanitize_dict(data)
        assert "<script>" not in result["a"]["b"]["c"]["d"]

    def test_non_string_values_preserved(self, sanitizer: InputSanitizer) -> None:
        data = {"count": 42, "active": True, "ratio": 3.14, "nothing": None}
        result = sanitizer.sanitize_dict(data)
        assert result == data

    def test_mixed_types(self, sanitizer: InputSanitizer) -> None:
        data = {
            "name": "safe value",
            "count": 10,
            "items": [1, "clean", {"inner": "<script>x</script>"}],
        }
        result = sanitizer.sanitize_dict(data)
        assert result["name"] == "safe value"
        assert result["count"] == 10
        assert result["items"][0] == 1
        assert result["items"][1] == "clean"
        assert "<script>" not in result["items"][2]["inner"]


class TestJSONDepthValidation:
    """JSON depth bomb validation tests."""

    def test_flat_dict_passes(self, sanitizer: InputSanitizer) -> None:
        assert sanitizer.validate_json_depth({"a": 1, "b": 2}) is True

    def test_depth_10_passes(self, sanitizer: InputSanitizer) -> None:
        data: Any = "leaf"
        for _ in range(10):
            data = {"nested": data}
        assert sanitizer.validate_json_depth(data, max_depth=10) is True

    def test_depth_11_fails_at_max_10(self, sanitizer: InputSanitizer) -> None:
        data: Any = "leaf"
        for _ in range(11):
            data = {"nested": data}
        assert sanitizer.validate_json_depth(data, max_depth=10) is False

    def test_deep_list_nesting(self, sanitizer: InputSanitizer) -> None:
        data: Any = "leaf"
        for _ in range(15):
            data = [data]
        assert sanitizer.validate_json_depth(data, max_depth=10) is False

    def test_mixed_dict_list_depth(self, sanitizer: InputSanitizer) -> None:
        data: Any = "leaf"
        for i in range(12):
            if i % 2 == 0:
                data = {"k": data}
            else:
                data = [data]
        assert sanitizer.validate_json_depth(data, max_depth=10) is False

    def test_wide_but_shallow_passes(self, sanitizer: InputSanitizer) -> None:
        """Many keys at the same level should not trigger depth check."""
        data = {f"key_{i}": f"value_{i}" for i in range(1000)}
        assert sanitizer.validate_json_depth(data, max_depth=10) is True

    def test_custom_max_depth(self, sanitizer: InputSanitizer) -> None:
        data: Any = "leaf"
        for _ in range(5):
            data = {"n": data}
        assert sanitizer.validate_json_depth(data, max_depth=3) is False
        assert sanitizer.validate_json_depth(data, max_depth=5) is True


class TestPayloadSizeValidation:
    """Payload size limit tests."""

    def test_small_payload_passes(self, sanitizer: InputSanitizer) -> None:
        body = b'{"key": "value"}'
        assert sanitizer.validate_payload_size(body) is True

    def test_exact_limit_passes(self, sanitizer: InputSanitizer) -> None:
        body = b"x" * 1_048_576
        assert sanitizer.validate_payload_size(body, max_bytes=1_048_576) is True

    def test_over_limit_fails(self, sanitizer: InputSanitizer) -> None:
        body = b"x" * 1_048_577
        assert sanitizer.validate_payload_size(body, max_bytes=1_048_576) is False

    def test_empty_body_passes(self, sanitizer: InputSanitizer) -> None:
        assert sanitizer.validate_payload_size(b"") is True

    def test_custom_limit(self, sanitizer: InputSanitizer) -> None:
        body = b"x" * 101
        assert sanitizer.validate_payload_size(body, max_bytes=100) is False
        assert sanitizer.validate_payload_size(body, max_bytes=200) is True


class TestCleanInputPassthrough:
    """Clean input should pass through completely unchanged."""

    def test_normal_string(self, sanitizer: InputSanitizer) -> None:
        text = "Hello, my name is John Doe. I am 30 years old."
        assert sanitizer.sanitize_string(text) == text

    def test_normal_dict(self, sanitizer: InputSanitizer) -> None:
        data = {"name": "John", "email": "john@example.com", "age": 30}
        assert sanitizer.sanitize_dict(data) == data

    def test_empty_string(self, sanitizer: InputSanitizer) -> None:
        assert sanitizer.sanitize_string("") == ""

    def test_empty_dict(self, sanitizer: InputSanitizer) -> None:
        assert sanitizer.sanitize_dict({}) == {}

    def test_numbers_and_booleans(self, sanitizer: InputSanitizer) -> None:
        data = {"a": 1, "b": 2.5, "c": True, "d": False, "e": None}
        assert sanitizer.sanitize_dict(data) == data


# ===========================================================================
# PART 3: InputSanitizerMiddleware integration tests
# ===========================================================================


class TestMiddlewareWebhookSkip:
    """Webhook paths should skip sanitization."""

    @pytest.mark.asyncio
    async def test_webhook_path_skips_sanitization(self, test_app: FastAPI) -> None:
        payload = {"data": "<script>alert(1)</script>"}
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/webhooks/stripe",
                json=payload,
            )
        assert r.status_code == 200


class TestMiddlewareHealthSkip:
    """Health endpoint should skip sanitization."""

    @pytest.mark.asyncio
    async def test_health_post_skips_sanitization(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post(
                "/health",
                json={"check": "<script>test</script>"},
            )
        assert r.status_code == 200


class TestMiddlewareEmptyBody:
    """Empty body should pass through without errors."""

    @pytest.mark.asyncio
    async def test_empty_body_post(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/data",
                content=b"",
                headers={"content-type": "application/json"},
            )
        # Middleware passes empty body through; route handler returns received=None
        assert r.status_code == 200
        assert r.json()["received"] is None


class TestMiddlewareNonJSON:
    """Non-JSON content types should pass through without sanitization."""

    @pytest.mark.asyncio
    async def test_form_data_passthrough(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/data",
                content=b"key=value",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        # Middleware passes non-JSON through; route handler returns "non-json"
        assert r.status_code == 200
        assert r.json()["received"] == "non-json"


class TestMiddlewarePayloadSize:
    """Oversized payloads should return 413."""

    @pytest.mark.asyncio
    async def test_oversized_payload_returns_413(self, small_body_app: FastAPI) -> None:
        large_payload = {"data": "x" * 200}
        async with AsyncClient(transport=ASGITransport(app=small_body_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/data",
                json=large_payload,
            )
        assert r.status_code == 413
        body = r.json()
        assert body["error"] == "payload_too_large"

    @pytest.mark.asyncio
    async def test_small_payload_passes(self, small_body_app: FastAPI) -> None:
        small_payload = {"k": "v"}
        async with AsyncClient(transport=ASGITransport(app=small_body_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/data",
                json=small_payload,
            )
        assert r.status_code == 200


class TestMiddlewareJSONDepth:
    """Deeply nested JSON should return 400."""

    @pytest.mark.asyncio
    async def test_deep_json_returns_400(self, shallow_depth_app: FastAPI) -> None:
        # Build a dict with depth 5 (exceeds max of 3)
        data: Any = "leaf"
        for _ in range(5):
            data = {"n": data}
        async with AsyncClient(transport=ASGITransport(app=shallow_depth_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/data",
                json=data,
            )
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "json_depth_exceeded"

    @pytest.mark.asyncio
    async def test_shallow_json_passes(self, shallow_depth_app: FastAPI) -> None:
        data = {"level1": {"level2": "value"}}
        async with AsyncClient(transport=ASGITransport(app=shallow_depth_app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/data",
                json=data,
            )
        assert r.status_code == 200


class TestMiddlewareSanitization:
    """End-to-end sanitization through the middleware."""

    @pytest.mark.asyncio
    async def test_xss_sanitized_in_request_body(self, test_app: FastAPI) -> None:
        payload = {"name": "John", "bio": "<script>alert('xss')</script>Safe text"}
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post("/api/v1/data", json=payload)
        assert r.status_code == 200
        received = r.json()["received"]
        assert "<script>" not in received["bio"]
        assert "Safe text" in received["bio"]
        assert received["name"] == "John"

    @pytest.mark.asyncio
    async def test_clean_data_passes_through_unchanged(self, test_app: FastAPI) -> None:
        payload = {"name": "Alice", "email": "alice@example.com", "count": 42}
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post("/api/v1/data", json=payload)
        assert r.status_code == 200
        received = r.json()["received"]
        assert received == payload

    @pytest.mark.asyncio
    async def test_get_request_not_sanitized(self, test_app: FastAPI) -> None:
        """GET requests should not trigger sanitization (no body)."""
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/test")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_sql_injection_sanitized(self, test_app: FastAPI) -> None:
        payload = {"query": "'; DROP TABLE users; --"}
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post("/api/v1/data", json=payload)
        assert r.status_code == 200
        received = r.json()["received"]
        assert "DROP TABLE" not in received["query"]

    @pytest.mark.asyncio
    async def test_combined_attack_sanitized(self, test_app: FastAPI) -> None:
        """Multiple attack vectors in a single payload should all be sanitized."""
        payload = {
            "xss": "<script>alert(1)</script>",
            "sqli": "1 UNION SELECT * FROM users",
            "cmd": "file; rm -rf /",
            "traversal": "../../etc/passwd",
        }
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.post("/api/v1/data", json=payload)
        assert r.status_code == 200
        received = r.json()["received"]
        assert "<script>" not in received["xss"]
        assert "UNION SELECT" not in received["sqli"].upper()
        assert "rm -rf" not in received["cmd"]
        assert "../" not in received["traversal"]


class TestMiddlewareMetricsSkip:
    """Metrics endpoint should skip sanitization."""

    @pytest.mark.asyncio
    async def test_metrics_skips_sanitization(self, test_app: FastAPI) -> None:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
            r = await c.get("/metrics")
        assert r.status_code == 200
