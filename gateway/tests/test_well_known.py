"""Tests for the /.well-known/ MCP discovery endpoints on DingDawg Agent Platform.

Covers two endpoints:

1. /.well-known/mcp.json — Legacy MCP capability advertisement
   - HTTP 200 response
   - Content-Type is application/json
   - No authentication required (public endpoint)
   - Schema shape: all required top-level keys present
   - Nested field completeness (server_info, capabilities, authentication, endpoints)
   - Supported protocols list content
   - Version field format validation
   - CORS header present (Access-Control-Allow-Origin: *)
   - Cache-Control header set correctly
   - Response is valid JSON (no decode errors)
   - Endpoint URLs are absolute (contain scheme + host)
   - Authentication.token_url is an absolute URL
   - Endpoints dict contains all required keys (agents, skills, templates, trigger)
   - Capabilities dict has correct types (bool values)
   - Schema_version is "1.0"
   - Server name and description are non-empty strings
   - Supported protocols includes mcp/1.0, a2a/0.3, ucp/1.0
   - Wrong method (POST) returns 405

2. /.well-known/mcp-server-card.json — SEP-1649 MCP Server Card (2026)
   - HTTP 200 response
   - Content-Type is application/json
   - Public — no auth (no 401, no 403)
   - CORS header present and is wildcard
   - Cache-Control: public, max-age=3600
   - Required SEP-1649 top-level fields ($schema, version, protocolVersion,
     serverInfo, transport, capabilities, authentication, tools, resources)
   - serverInfo contains name, title, version, description, provider
   - serverInfo.name and .title are non-empty strings
   - serverInfo.version matches semver format
   - transport.type is "streamable-http"
   - transport.endpoint is an absolute URL
   - authentication.required is True
   - authentication.schemes is a non-empty list
   - First scheme type is "bearer"
   - First scheme tokenEndpoint is an absolute URL
   - tools is ["dynamic"]
   - resources is ["dynamic"]
   - protocols dict contains "mcp" key with non-empty version
   - $schema references modelcontextprotocol
   - POST returns 405
"""

from __future__ import annotations

import os
import re

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WELL_KNOWN_PATH = "/.well-known/mcp.json"
_SECRET = "test-secret-well-known-suite"

_REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "server_info",
    "capabilities",
    "authentication",
    "endpoints",
    "supported_protocols",
}

_REQUIRED_SERVER_INFO_KEYS = {"name", "version", "description"}

_REQUIRED_CAPABILITIES_KEYS = {"tools", "resources", "prompts"}

_REQUIRED_AUTHENTICATION_KEYS = {"type", "token_url"}

_REQUIRED_ENDPOINT_KEYS = {"agents", "skills", "templates", "trigger"}

_REQUIRED_PROTOCOLS = {"mcp/1.0", "a2a/0.3", "ucp/1.0"}

# Semver-like pattern: major.minor.patch
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client bound to the full app (lifespan initialised)."""
    db_file = str(tmp_path / "test_well_known.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


# ---------------------------------------------------------------------------
# Basic HTTP behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_endpoint_returns_200(client):
    """GET /.well-known/mcp.json returns HTTP 200."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mcp_content_type_is_json(client):
    """Response Content-Type header is application/json."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_mcp_response_is_valid_json(client):
    """Response body can be decoded as JSON without error."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# No auth required (public endpoint)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_no_auth_required(client):
    """Request without Authorization header succeeds (public endpoint)."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mcp_no_auth_not_401(client):
    """Endpoint never returns 401 (not protected)."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_mcp_no_auth_not_403(client):
    """Endpoint never returns 403 (not role-gated)."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Top-level schema shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_top_level_keys_present(client):
    """All required top-level keys are present in the document."""
    resp = await client.get(_WELL_KNOWN_PATH)
    data = resp.json()
    missing = _REQUIRED_TOP_LEVEL_KEYS - set(data.keys())
    assert not missing, f"Missing top-level keys: {missing}"


@pytest.mark.asyncio
async def test_mcp_schema_version_is_string(client):
    """schema_version field is a string."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert isinstance(data["schema_version"], str)


@pytest.mark.asyncio
async def test_mcp_schema_version_is_1_0(client):
    """schema_version is '1.0'."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert data["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# server_info block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_server_info_keys_present(client):
    """server_info contains name, version, description."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    missing = _REQUIRED_SERVER_INFO_KEYS - set(data["server_info"].keys())
    assert not missing, f"server_info missing keys: {missing}"


@pytest.mark.asyncio
async def test_mcp_server_info_name_non_empty(client):
    """server_info.name is a non-empty string."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert isinstance(data["server_info"]["name"], str)
    assert len(data["server_info"]["name"]) > 0


@pytest.mark.asyncio
async def test_mcp_server_info_version_semver(client):
    """server_info.version matches major.minor.patch format."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    version = data["server_info"]["version"]
    assert _SEMVER_RE.match(version), f"Version '{version}' does not match semver"


@pytest.mark.asyncio
async def test_mcp_server_info_description_non_empty(client):
    """server_info.description is a non-empty string."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert isinstance(data["server_info"]["description"], str)
    assert len(data["server_info"]["description"]) > 0


# ---------------------------------------------------------------------------
# capabilities block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_capabilities_keys_present(client):
    """capabilities contains tools, resources, prompts."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    missing = _REQUIRED_CAPABILITIES_KEYS - set(data["capabilities"].keys())
    assert not missing, f"capabilities missing keys: {missing}"


@pytest.mark.asyncio
async def test_mcp_capabilities_values_are_bools(client):
    """All capabilities values are booleans."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    for key, val in data["capabilities"].items():
        assert isinstance(val, bool), f"capabilities.{key} should be bool, got {type(val)}"


@pytest.mark.asyncio
async def test_mcp_capabilities_tools_true(client):
    """capabilities.tools is True (platform supports tools)."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert data["capabilities"]["tools"] is True


@pytest.mark.asyncio
async def test_mcp_capabilities_resources_true(client):
    """capabilities.resources is True."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert data["capabilities"]["resources"] is True


# ---------------------------------------------------------------------------
# authentication block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_authentication_keys_present(client):
    """authentication contains type and token_url."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    missing = _REQUIRED_AUTHENTICATION_KEYS - set(data["authentication"].keys())
    assert not missing, f"authentication missing keys: {missing}"


@pytest.mark.asyncio
async def test_mcp_authentication_type_is_bearer(client):
    """authentication.type is 'bearer'."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert data["authentication"]["type"] == "bearer"


@pytest.mark.asyncio
async def test_mcp_authentication_token_url_absolute(client):
    """authentication.token_url is an absolute URL (contains scheme)."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    token_url = data["authentication"]["token_url"]
    assert token_url.startswith("http"), f"token_url should be absolute: {token_url}"


# ---------------------------------------------------------------------------
# endpoints block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_endpoints_keys_present(client):
    """endpoints contains agents, skills, templates, trigger."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    missing = _REQUIRED_ENDPOINT_KEYS - set(data["endpoints"].keys())
    assert not missing, f"endpoints missing keys: {missing}"


@pytest.mark.asyncio
async def test_mcp_endpoint_urls_absolute(client):
    """All endpoint URLs are absolute (start with http)."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    for key, url in data["endpoints"].items():
        assert url.startswith("http"), f"endpoints.{key} should be absolute: {url}"


@pytest.mark.asyncio
async def test_mcp_trigger_endpoint_has_placeholder(client):
    """endpoints.trigger contains '{agent_id}' placeholder."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert "{agent_id}" in data["endpoints"]["trigger"]


# ---------------------------------------------------------------------------
# supported_protocols
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_supported_protocols_is_list(client):
    """supported_protocols is a list."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert isinstance(data["supported_protocols"], list)


@pytest.mark.asyncio
async def test_mcp_supported_protocols_contains_mcp(client):
    """supported_protocols includes 'mcp/1.0'."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert "mcp/1.0" in data["supported_protocols"]


@pytest.mark.asyncio
async def test_mcp_supported_protocols_contains_a2a(client):
    """supported_protocols includes 'a2a/0.3'."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert "a2a/0.3" in data["supported_protocols"]


@pytest.mark.asyncio
async def test_mcp_supported_protocols_contains_ucp(client):
    """supported_protocols includes 'ucp/1.0'."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    assert "ucp/1.0" in data["supported_protocols"]


@pytest.mark.asyncio
async def test_mcp_supported_protocols_all_present(client):
    """All three required protocols are present."""
    data = (await client.get(_WELL_KNOWN_PATH)).json()
    protocols = set(data["supported_protocols"])
    missing = _REQUIRED_PROTOCOLS - protocols
    assert not missing, f"Missing protocols: {missing}"


# ---------------------------------------------------------------------------
# HTTP headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_cors_header_present(client):
    """Access-Control-Allow-Origin header is present."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_mcp_cors_header_is_wildcard(client):
    """Access-Control-Allow-Origin is '*' (fully public)."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert resp.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_mcp_cache_control_header_present(client):
    """Cache-Control header is present."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert "cache-control" in resp.headers


@pytest.mark.asyncio
async def test_mcp_cache_control_is_public(client):
    """Cache-Control includes 'public' directive."""
    resp = await client.get(_WELL_KNOWN_PATH)
    assert "public" in resp.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# Wrong method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_post_returns_405(client):
    """POST to /.well-known/mcp.json returns HTTP 405 Method Not Allowed."""
    resp = await client.post(_WELL_KNOWN_PATH)
    assert resp.status_code == 405


# ===========================================================================
# /.well-known/mcp-server-card.json — SEP-1649 MCP Server Card (2026 standard)
# ===========================================================================

_SERVER_CARD_PATH = "/.well-known/mcp-server-card.json"

_SEP1649_REQUIRED_KEYS = {
    "$schema",
    "version",
    "protocolVersion",
    "serverInfo",
    "transport",
    "capabilities",
    "authentication",
    "tools",
    "resources",
}

_SERVER_INFO_REQUIRED_KEYS = {"name", "title", "version", "description", "provider"}


# ---------------------------------------------------------------------------
# Basic HTTP behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_returns_200(client):
    """GET /.well-known/mcp-server-card.json returns HTTP 200."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_server_card_content_type_is_json(client):
    """Response Content-Type includes application/json."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert "application/json" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_server_card_response_is_valid_json(client):
    """Response body parses as a JSON object."""
    resp = await client.get(_SERVER_CARD_PATH)
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_server_card_post_returns_405(client):
    """POST to /.well-known/mcp-server-card.json returns 405."""
    resp = await client.post(_SERVER_CARD_PATH)
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Public access — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_no_auth_required(client):
    """Request without Authorization header succeeds."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_server_card_not_401(client):
    """Endpoint never returns 401 Unauthorized."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_server_card_not_403(client):
    """Endpoint never returns 403 Forbidden."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# HTTP headers — caching and CORS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_cors_header_present(client):
    """Access-Control-Allow-Origin header is present."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_server_card_cors_header_is_wildcard(client):
    """Access-Control-Allow-Origin is '*' (fully public)."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert resp.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_server_card_cache_control_present(client):
    """Cache-Control header is present."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert "cache-control" in resp.headers


@pytest.mark.asyncio
async def test_server_card_cache_control_is_public(client):
    """Cache-Control includes 'public' directive."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert "public" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_server_card_cache_control_max_age(client):
    """Cache-Control includes max-age=3600 (1-hour browser cache)."""
    resp = await client.get(_SERVER_CARD_PATH)
    assert "max-age=3600" in resp.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# SEP-1649 top-level schema fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_required_top_level_keys(client):
    """All SEP-1649 required top-level keys are present."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    missing = _SEP1649_REQUIRED_KEYS - set(data.keys())
    assert not missing, f"Missing top-level keys: {missing}"


@pytest.mark.asyncio
async def test_server_card_schema_references_mcp(client):
    """$schema URL references the MCP server card schema namespace."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert "modelcontextprotocol" in data["$schema"]


@pytest.mark.asyncio
async def test_server_card_version_is_1_0(client):
    """version is '1.0' (SEP-1649 card format version)."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["version"] == "1.0"


@pytest.mark.asyncio
async def test_server_card_protocol_version_non_empty(client):
    """protocolVersion is a non-empty string."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert isinstance(data["protocolVersion"], str)
    assert len(data["protocolVersion"]) > 0


# ---------------------------------------------------------------------------
# serverInfo block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_server_info_required_keys(client):
    """serverInfo contains all required SEP-1649 keys."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    missing = _SERVER_INFO_REQUIRED_KEYS - set(data["serverInfo"].keys())
    assert not missing, f"serverInfo missing keys: {missing}"


@pytest.mark.asyncio
async def test_server_card_server_info_name_non_empty(client):
    """serverInfo.name is a non-empty string."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    name = data["serverInfo"]["name"]
    assert isinstance(name, str) and len(name) > 0


@pytest.mark.asyncio
async def test_server_card_server_info_title_non_empty(client):
    """serverInfo.title is a non-empty string."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    title = data["serverInfo"]["title"]
    assert isinstance(title, str) and len(title) > 0


@pytest.mark.asyncio
async def test_server_card_server_info_version_semver(client):
    """serverInfo.version matches semver major.minor.patch format."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    version = data["serverInfo"]["version"]
    assert _SEMVER_RE.match(version), f"'{version}' is not semver"


@pytest.mark.asyncio
async def test_server_card_server_info_description_non_empty(client):
    """serverInfo.description is a non-empty string."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    desc = data["serverInfo"]["description"]
    assert isinstance(desc, str) and len(desc) > 0


# ---------------------------------------------------------------------------
# transport block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_transport_is_dict(client):
    """transport is a dict."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert isinstance(data["transport"], dict)


@pytest.mark.asyncio
async def test_server_card_transport_type_is_streamable_http(client):
    """transport.type is 'streamable-http'."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["transport"]["type"] == "streamable-http"


@pytest.mark.asyncio
async def test_server_card_transport_endpoint_is_absolute(client):
    """transport.endpoint is an absolute URL."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["transport"]["endpoint"].startswith("http")


# ---------------------------------------------------------------------------
# authentication block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_authentication_required_true(client):
    """authentication.required is True."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["authentication"]["required"] is True


@pytest.mark.asyncio
async def test_server_card_authentication_schemes_non_empty(client):
    """authentication.schemes is a non-empty list."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    schemes = data["authentication"]["schemes"]
    assert isinstance(schemes, list) and len(schemes) > 0


@pytest.mark.asyncio
async def test_server_card_authentication_scheme_type_bearer(client):
    """First scheme type is 'bearer'."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["authentication"]["schemes"][0]["type"] == "bearer"


@pytest.mark.asyncio
async def test_server_card_token_endpoint_is_absolute(client):
    """First scheme tokenEndpoint is an absolute URL."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    token_url = data["authentication"]["schemes"][0]["tokenEndpoint"]
    assert token_url.startswith("http"), f"tokenEndpoint not absolute: {token_url}"


# ---------------------------------------------------------------------------
# Primitive fields (tools, resources, prompts)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_tools_is_dynamic(client):
    """tools advertises ['dynamic'] for tenant-specific capabilities."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["tools"] == ["dynamic"]


@pytest.mark.asyncio
async def test_server_card_resources_is_dynamic(client):
    """resources advertises ['dynamic']."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert data["resources"] == ["dynamic"]


@pytest.mark.asyncio
async def test_server_card_prompts_is_list(client):
    """prompts is a list."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert isinstance(data["prompts"], list)


# ---------------------------------------------------------------------------
# protocols block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_card_protocols_contains_mcp(client):
    """protocols dict contains 'mcp' key."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    assert "mcp" in data["protocols"]


@pytest.mark.asyncio
async def test_server_card_protocols_mcp_version_non_empty(client):
    """protocols.mcp.version is a non-empty string."""
    data = (await client.get(_SERVER_CARD_PATH)).json()
    mcp_version = data["protocols"]["mcp"].get("version", "")
    assert isinstance(mcp_version, str) and len(mcp_version) > 0
