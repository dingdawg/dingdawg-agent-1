"""Comprehensive tests for the dependency audit engine and threat intel engine.

Covers:
- Requirements parsing (requirements.txt and pyproject.toml)
- Vulnerability dataclass integrity
- AuditReport generation, severity counting, JSON export
- VulnCache SQLite operations with TTL
- OSV.dev API integration (mocked)
- Offline mode
- Package version comparison
- CVE ingestion with NVD + OSV mocking
- Advisory text parsing and IOC extraction
- Exposure checking against our stack
- Mitigation suggestion generation
- Hardened control distillation
- Stack mapping and auto-population
- MITRE ATT&CK tactic classification
- Risk score computation
- Auto-safe vs approval-required classification
- Rollback plan generation
- SQLite persistence for threat intel
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from isg_agent.security.dependency_audit import (
    AuditReport,
    DependencyAuditor,
    VulnCache,
    Vulnerability,
    parse_pyproject_toml,
    parse_requirements_txt,
    version_lt,
)
from isg_agent.security.threat_intel import (
    ExposureReport,
    HardenedControl,
    Mitigation,
    ThreatAssessment,
    ThreatIntelDB,
    ThreatIntelEngine,
    _classify_mitre_tactics,
    _classify_severity_from_cvss,
    _compute_risk_score,
    _determine_blast_radius,
    _extract_iocs_from_text,
    _extract_affected_packages_from_text,
    _is_auto_safe,
    _requires_approval,
    detect_installed_stack,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def tmp_cache_db(tmp_path: Path) -> Path:
    return tmp_path / "vuln_cache.db"


@pytest.fixture()
def tmp_intel_db(tmp_path: Path) -> Path:
    return tmp_path / "threat_intel.db"


@pytest.fixture()
def vuln_cache(tmp_cache_db: Path) -> VulnCache:
    cache = VulnCache(db_path=tmp_cache_db)
    yield cache
    cache.close()


@pytest.fixture()
def intel_db(tmp_intel_db: Path) -> ThreatIntelDB:
    db = ThreatIntelDB(db_path=tmp_intel_db)
    yield db
    db.close()


@pytest.fixture()
def sample_vulnerability() -> Vulnerability:
    return Vulnerability(
        cve_id="CVE-2024-12345",
        package="fastapi",
        installed_version="0.109.0",
        fixed_version="0.110.0",
        severity="HIGH",
        description="Remote code execution in FastAPI via crafted request.",
        advisory_url="https://osv.dev/vulnerability/GHSA-xxxx",
    )


@pytest.fixture()
def sample_requirements_txt(tmp_path: Path) -> Path:
    content = """# Production dependencies
fastapi==0.115.6
uvicorn[standard]==0.32.1
websockets==13.1
pydantic==2.10.4
httpx==0.28.1
python-jose[cryptography]==3.3.0
openai==1.58.1
"""
    path = tmp_path / "requirements.txt"
    path.write_text(content)
    return path


@pytest.fixture()
def sample_pyproject_toml(tmp_path: Path) -> Path:
    content = '''[project]
name = "test-project"
version = "0.1.0"

dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic>=2.5",
    "httpx>=0.27.0",
    "openai>=1.50.0",
    "stripe>=8.0.0",
]
'''
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


@pytest.fixture()
def mock_osv_response() -> dict:
    """Mock OSV.dev API response for a package query."""
    return {
        "vulns": [
            {
                "id": "GHSA-abcd-1234-efgh",
                "aliases": ["CVE-2024-99999"],
                "summary": "Critical vulnerability in example package allowing RCE.",
                "severity": [{"type": "CVSS_V3", "score": "9.8"}],
                "affected": [
                    {
                        "package": {"name": "fastapi", "ecosystem": "PyPI"},
                        "ranges": [
                            {
                                "type": "ECOSYSTEM",
                                "events": [
                                    {"introduced": "0"},
                                    {"fixed": "0.116.0"},
                                ],
                            }
                        ],
                    }
                ],
                "references": [
                    {"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-abcd"},
                    {"type": "WEB", "url": "https://example.com/details"},
                ],
            }
        ]
    }


@pytest.fixture()
def mock_nvd_response() -> dict:
    """Mock NVD API response for a CVE query."""
    return {
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2024-99999",
                    "descriptions": [
                        {
                            "lang": "en",
                            "value": "Remote code execution in fastapi via crafted input.",
                        }
                    ],
                    "metrics": {
                        "cvssMetricV31": [
                            {
                                "cvssData": {
                                    "baseScore": 9.8,
                                    "attackVector": "NETWORK",
                                }
                            }
                        ]
                    },
                    "configurations": [
                        {
                            "nodes": [
                                {
                                    "cpeMatch": [
                                        {
                                            "criteria": "cpe:2.3:a:tiangolo:fastapi:*:*:*:*:*:*:*:*",
                                            "vulnerable": True,
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            }
        ]
    }


@pytest.fixture()
def mock_osv_vuln_response() -> dict:
    """Mock OSV.dev single-vuln API response."""
    return {
        "id": "CVE-2024-99999",
        "summary": "Remote code execution in fastapi.",
        "details": "A crafted HTTP request can trigger RCE in fastapi < 0.116.0.",
        "affected": [
            {
                "package": {"name": "fastapi", "ecosystem": "PyPI"},
                "ranges": [
                    {
                        "type": "ECOSYSTEM",
                        "events": [{"introduced": "0"}, {"fixed": "0.116.0"}],
                    }
                ],
            }
        ],
        "severity": [{"type": "CVSS_V3", "score": "9.8"}],
        "references": [
            {"type": "ADVISORY", "url": "https://nvd.nist.gov/vuln/detail/CVE-2024-99999"}
        ],
    }


def _make_response(status_code: int, json_data: dict, url: str = "https://mock") -> httpx.Response:
    """Build an httpx.Response with a request set so raise_for_status works."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", url),
    )
    return resp


def _make_mock_http_client(responses: dict[str, dict]) -> httpx.Client:
    """Build a mock httpx.Client that returns canned responses by URL pattern.

    *responses* maps URL-substring -> raw JSON dict (not httpx.Response).
    """
    client = MagicMock(spec=httpx.Client)

    def mock_post(url, **kwargs):
        for pattern, json_data in responses.items():
            if pattern in url:
                return _make_response(200, json_data, url)
        return _make_response(404, {}, url)

    def mock_get(url, **kwargs):
        for pattern, json_data in responses.items():
            if pattern in url:
                return _make_response(200, json_data, url)
        return _make_response(404, {}, url)

    client.post = mock_post
    client.get = mock_get
    client.close = MagicMock()
    return client


# ============================================================================
# Part 1: Dependency Audit Tests
# ============================================================================


class TestVulnerabilityDataclass:
    """Test Vulnerability dataclass fields and serialization."""

    def test_all_fields_present(self, sample_vulnerability: Vulnerability) -> None:
        assert sample_vulnerability.cve_id == "CVE-2024-12345"
        assert sample_vulnerability.package == "fastapi"
        assert sample_vulnerability.installed_version == "0.109.0"
        assert sample_vulnerability.fixed_version == "0.110.0"
        assert sample_vulnerability.severity == "HIGH"
        assert sample_vulnerability.description != ""
        assert sample_vulnerability.advisory_url != ""

    def test_to_dict(self, sample_vulnerability: Vulnerability) -> None:
        d = sample_vulnerability.to_dict()
        assert isinstance(d, dict)
        assert d["cve_id"] == "CVE-2024-12345"
        assert d["package"] == "fastapi"
        assert d["severity"] == "HIGH"
        assert d["fixed_version"] == "0.110.0"

    def test_optional_fixed_version(self) -> None:
        v = Vulnerability(
            cve_id="CVE-2024-00001",
            package="somepkg",
            installed_version="1.0.0",
            fixed_version=None,
            severity="LOW",
            description="No fix available yet.",
            advisory_url="https://example.com",
        )
        assert v.fixed_version is None
        assert v.to_dict()["fixed_version"] is None

    def test_severity_values(self) -> None:
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            v = Vulnerability(
                cve_id="CVE-2024-00002",
                package="test",
                installed_version="1.0",
                fixed_version=None,
                severity=sev,
                description="test",
                advisory_url="",
            )
            assert v.severity == sev


class TestAuditReport:
    """Test AuditReport dataclass and report generation."""

    def test_empty_report(self) -> None:
        report = AuditReport()
        assert report.packages_scanned == 0
        assert report.vulnerabilities == []
        assert report.critical_count == 0

    def test_to_json_structure(self, sample_vulnerability: Vulnerability) -> None:
        report = AuditReport(
            packages_scanned=5,
            vulnerabilities=[sample_vulnerability],
            critical_count=0,
            high_count=1,
            scan_timestamp="2024-01-01T00:00:00Z",
            recommendations=["Upgrade fastapi"],
        )
        j = report.to_json()
        assert j["packages_scanned"] == 5
        assert len(j["vulnerabilities"]) == 1
        assert j["high_count"] == 1
        assert isinstance(j["recommendations"], list)

    def test_to_json_serializable(self, sample_vulnerability: Vulnerability) -> None:
        report = AuditReport(
            packages_scanned=1,
            vulnerabilities=[sample_vulnerability],
            scan_timestamp="2024-01-01T00:00:00Z",
        )
        # Must be JSON-serializable
        serialized = json.dumps(report.to_json())
        assert isinstance(serialized, str)

    def test_recount(self) -> None:
        vulns = [
            Vulnerability("CVE-1", "a", "1.0", None, "CRITICAL", "", ""),
            Vulnerability("CVE-2", "b", "1.0", None, "CRITICAL", "", ""),
            Vulnerability("CVE-3", "c", "1.0", None, "HIGH", "", ""),
            Vulnerability("CVE-4", "d", "1.0", None, "MEDIUM", "", ""),
            Vulnerability("CVE-5", "e", "1.0", None, "LOW", "", ""),
            Vulnerability("CVE-6", "f", "1.0", None, "LOW", "", ""),
        ]
        report = AuditReport(vulnerabilities=vulns)
        report._recount()
        assert report.critical_count == 2
        assert report.high_count == 1
        assert report.medium_count == 1
        assert report.low_count == 2

    def test_recommendations_for_critical(self) -> None:
        report = AuditReport(
            packages_scanned=1,
            vulnerabilities=[
                Vulnerability("CVE-1", "a", "1.0", "2.0", "CRITICAL", "", ""),
            ],
        )
        report._recount()
        recs = DependencyAuditor._build_recommendations(report)
        assert any("URGENT" in r for r in recs)
        assert any("Upgrade targets" in r for r in recs)

    def test_recommendations_no_vulns(self) -> None:
        report = AuditReport(packages_scanned=5, vulnerabilities=[])
        report._recount()
        recs = DependencyAuditor._build_recommendations(report)
        assert any("No known vulnerabilities" in r for r in recs)


class TestParseRequirementsTxt:
    """Test requirements.txt parsing."""

    def test_basic_pinned(self) -> None:
        text = "fastapi==0.115.6\npydantic==2.10.4\n"
        result = parse_requirements_txt(text)
        assert ("fastapi", "0.115.6") in result
        assert ("pydantic", "2.10.4") in result

    def test_with_extras(self) -> None:
        text = "uvicorn[standard]==0.32.1\npython-jose[cryptography]==3.3.0\n"
        result = parse_requirements_txt(text)
        assert ("uvicorn", "0.32.1") in result
        assert ("python-jose", "3.3.0") in result

    def test_comments_and_blanks(self) -> None:
        text = "# This is a comment\n\nfastapi==0.115.0\n  # Another comment\n"
        result = parse_requirements_txt(text)
        assert len(result) == 1
        assert result[0][0] == "fastapi"

    def test_gte_operator(self) -> None:
        text = "fastapi>=0.115.0\n"
        result = parse_requirements_txt(text)
        assert len(result) == 1
        assert result[0] == ("fastapi", "0.115.0")

    def test_tilde_operator(self) -> None:
        text = "fastapi~=0.115.0\n"
        result = parse_requirements_txt(text)
        assert len(result) == 1
        assert result[0] == ("fastapi", "0.115.0")

    def test_skip_flags(self) -> None:
        text = "-r base.txt\n--index-url https://pypi.org/simple\nfastapi==1.0\n"
        result = parse_requirements_txt(text)
        assert len(result) == 1
        assert result[0][0] == "fastapi"

    def test_empty_text(self) -> None:
        result = parse_requirements_txt("")
        assert result == []

    def test_no_version_specified(self) -> None:
        text = "fastapi\n"
        result = parse_requirements_txt(text)
        assert len(result) == 1
        assert result[0] == ("fastapi", "0.0.0")


class TestParsePyprojectToml:
    """Test pyproject.toml parsing."""

    def test_basic_dependencies(self) -> None:
        text = '''[project]
dependencies = [
    "fastapi>=0.115.0",
    "pydantic>=2.5",
]
'''
        result = parse_pyproject_toml(text)
        assert ("fastapi", "0.115.0") in result
        assert ("pydantic", "2.5") in result

    def test_with_extras(self) -> None:
        text = '''[project]
dependencies = [
    "uvicorn[standard]>=0.32.0",
]
'''
        result = parse_pyproject_toml(text)
        assert ("uvicorn", "0.32.0") in result

    def test_empty_dependencies(self) -> None:
        text = '''[project]
dependencies = [
]
'''
        result = parse_pyproject_toml(text)
        assert result == []

    def test_no_dependencies_section(self) -> None:
        text = '''[project]
name = "test"
'''
        result = parse_pyproject_toml(text)
        assert result == []


class TestVersionComparison:
    """Test version comparison helpers."""

    def test_lt_major(self) -> None:
        assert version_lt("1.0.0", "2.0.0") is True

    def test_lt_minor(self) -> None:
        assert version_lt("1.1.0", "1.2.0") is True

    def test_lt_patch(self) -> None:
        assert version_lt("1.0.1", "1.0.2") is True

    def test_not_lt_equal(self) -> None:
        assert version_lt("1.0.0", "1.0.0") is False

    def test_not_lt_greater(self) -> None:
        assert version_lt("2.0.0", "1.0.0") is False

    def test_two_part_version(self) -> None:
        assert version_lt("1.5", "1.6") is True
        assert version_lt("1.6", "1.5") is False

    def test_different_length_versions(self) -> None:
        assert version_lt("1.0", "1.0.1") is True

    def test_invalid_version_string(self) -> None:
        # Should not crash; returns (0,) for unparseable strings
        assert version_lt("abc", "1.0") is True


class TestVulnCache:
    """Test SQLite vulnerability cache."""

    def test_put_and_get(self, vuln_cache: VulnCache) -> None:
        data = [{"cve_id": "CVE-2024-00001", "severity": "HIGH"}]
        vuln_cache.put("pkg:1.0", data)
        result = vuln_cache.get("pkg:1.0")
        assert result == data

    def test_get_missing_key(self, vuln_cache: VulnCache) -> None:
        result = vuln_cache.get("nonexistent:1.0")
        assert result is None

    def test_ttl_expired(self, vuln_cache: VulnCache) -> None:
        data = [{"cve_id": "CVE-2024-00002"}]
        vuln_cache.put("old:1.0", data)
        # Manually expire by updating fetched_at
        vuln_cache._conn.execute(
            "UPDATE vuln_cache SET fetched_at = ? WHERE cache_key = ?",
            (time.time() - 90_000, "old:1.0"),  # 25 hours ago
        )
        vuln_cache._conn.commit()
        result = vuln_cache.get("old:1.0")
        assert result is None

    def test_overwrite_existing(self, vuln_cache: VulnCache) -> None:
        vuln_cache.put("pkg:1.0", [{"v": 1}])
        vuln_cache.put("pkg:1.0", [{"v": 2}])
        result = vuln_cache.get("pkg:1.0")
        assert result == [{"v": 2}]

    def test_empty_list_cached(self, vuln_cache: VulnCache) -> None:
        vuln_cache.put("clean:1.0", [])
        result = vuln_cache.get("clean:1.0")
        assert result == []

    def test_busy_timeout_set(self, vuln_cache: VulnCache) -> None:
        row = vuln_cache._conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000


class TestDependencyAuditorScanRequirements:
    """Test DependencyAuditor.scan_requirements with mocked HTTP."""

    def test_scan_requirements_txt_with_osv_results(
        self, sample_requirements_txt: Path, tmp_cache_db: Path, mock_osv_response: dict
    ) -> None:
        http_client = _make_mock_http_client({"osv.dev": mock_osv_response})

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=http_client
        )
        report = auditor.scan_requirements(str(sample_requirements_txt))

        assert report.packages_scanned == 7
        # Each package gets the same mock response with 1 vuln
        assert len(report.vulnerabilities) >= 1
        assert report.scan_timestamp != ""
        auditor.close()

    def test_scan_pyproject_toml(
        self, sample_pyproject_toml: Path, tmp_cache_db: Path, mock_osv_response: dict
    ) -> None:
        http_client = _make_mock_http_client({"osv.dev": mock_osv_response})

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=http_client
        )
        report = auditor.scan_requirements(str(sample_pyproject_toml))

        assert report.packages_scanned == 6
        auditor.close()

    def test_scan_nonexistent_file(self, tmp_cache_db: Path) -> None:
        auditor = DependencyAuditor(cache_db_path=tmp_cache_db)
        report = auditor.scan_requirements("/nonexistent/path/requirements.txt")
        assert report.packages_scanned == 0
        assert report.vulnerabilities == []
        auditor.close()

    def test_offline_mode_returns_empty(
        self, sample_requirements_txt: Path, tmp_cache_db: Path
    ) -> None:
        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, offline=True
        )
        report = auditor.scan_requirements(str(sample_requirements_txt))
        # No cached data, offline mode: no vulns
        assert report.packages_scanned == 7
        assert len(report.vulnerabilities) == 0
        auditor.close()

    def test_offline_mode_uses_cache(
        self, sample_requirements_txt: Path, tmp_cache_db: Path
    ) -> None:
        # Pre-populate cache
        cache = VulnCache(db_path=tmp_cache_db)
        cache.put(
            "fastapi:0.115.6",
            [
                {
                    "cve_id": "CVE-2024-CACHED",
                    "package": "fastapi",
                    "installed_version": "0.115.6",
                    "fixed_version": "0.116.0",
                    "severity": "HIGH",
                    "description": "Cached vuln",
                    "advisory_url": "https://example.com",
                }
            ],
        )
        cache.close()

        auditor = DependencyAuditor(cache_db_path=tmp_cache_db, offline=True)
        report = auditor.scan_requirements(str(sample_requirements_txt))
        # Should find cached vuln for fastapi
        fastapi_vulns = [v for v in report.vulnerabilities if v.package == "fastapi"]
        assert len(fastapi_vulns) == 1
        assert fastapi_vulns[0].cve_id == "CVE-2024-CACHED"
        auditor.close()


class TestDependencyAuditorCheckPackage:
    """Test DependencyAuditor.check_package."""

    def test_check_package_with_mock(
        self, tmp_cache_db: Path, mock_osv_response: dict
    ) -> None:
        http_client = _make_mock_http_client({"osv.dev": mock_osv_response})

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=http_client
        )
        vulns = auditor.check_package("fastapi", "0.115.0")

        assert len(vulns) == 1
        assert vulns[0].cve_id == "CVE-2024-99999"
        assert vulns[0].fixed_version == "0.116.0"
        assert vulns[0].advisory_url == "https://github.com/advisories/GHSA-abcd"
        auditor.close()

    def test_check_package_caches_result(
        self, tmp_cache_db: Path, mock_osv_response: dict
    ) -> None:
        http_client = _make_mock_http_client({"osv.dev": mock_osv_response})

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=http_client
        )
        # First call: network
        vulns1 = auditor.check_package("fastapi", "0.115.0")
        # Second call: should come from cache
        vulns2 = auditor.check_package("fastapi", "0.115.0")
        assert vulns1[0].cve_id == vulns2[0].cve_id
        auditor.close()

    def test_check_package_network_error(self, tmp_cache_db: Path) -> None:
        """Network error should return empty, not crash."""
        client = MagicMock(spec=httpx.Client)
        client.post = MagicMock(side_effect=httpx.HTTPError("Connection failed"))
        client.close = MagicMock()

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=client
        )
        vulns = auditor.check_package("fastapi", "0.115.0")
        assert vulns == []
        auditor.close()

    def test_check_package_no_vulns(self, tmp_cache_db: Path) -> None:
        http_client = _make_mock_http_client({"osv.dev": {"vulns": []}})

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=http_client
        )
        vulns = auditor.check_package("safepkg", "1.0.0")
        assert vulns == []
        auditor.close()


class TestDependencyAuditorScanInstalled:
    """Test scanning installed packages."""

    def test_scan_installed_returns_report(self, tmp_cache_db: Path) -> None:
        # Use empty OSV response so no network needed
        http_client = _make_mock_http_client({"osv.dev": {"vulns": []}})

        auditor = DependencyAuditor(
            cache_db_path=tmp_cache_db, http_client=http_client
        )
        report = auditor.scan_installed()
        # At minimum pytest itself should be installed
        assert report.packages_scanned > 0
        assert report.scan_timestamp != ""
        auditor.close()


class TestDependencyAuditorGenerateReport:
    """Test report generation."""

    def test_generate_report_empty(self, tmp_cache_db: Path) -> None:
        auditor = DependencyAuditor(cache_db_path=tmp_cache_db, offline=True)
        report = auditor.generate_report()
        assert report.packages_scanned == 0
        assert report.vulnerabilities == []
        auditor.close()

    def test_generate_report_severity_counts(self, tmp_cache_db: Path) -> None:
        auditor = DependencyAuditor(cache_db_path=tmp_cache_db, offline=True)
        auditor._scanned_packages = [("a", "1.0"), ("b", "1.0")]
        auditor._all_vulns = [
            Vulnerability("CVE-1", "a", "1.0", None, "CRITICAL", "", ""),
            Vulnerability("CVE-2", "b", "1.0", None, "HIGH", "", ""),
        ]
        report = auditor.generate_report()
        assert report.packages_scanned == 2
        assert report.critical_count == 1
        assert report.high_count == 1
        assert report.medium_count == 0
        assert report.low_count == 0
        auditor.close()


# ============================================================================
# Part 2: Threat Intel Tests
# ============================================================================


class TestThreatAssessmentDataclass:
    """Test ThreatAssessment dataclass."""

    def test_all_fields(self) -> None:
        ta = ThreatAssessment(
            threat_id="CVE-2024-99999",
            title="Test threat",
            severity="HIGH",
            attack_vector="NETWORK",
            affected_components=["fastapi"],
            iocs=["CVE-2024-99999"],
            mitre_tactics=["Initial Access"],
            applies_to_us=True,
            confidence=0.9,
        )
        assert ta.threat_id == "CVE-2024-99999"
        assert ta.applies_to_us is True
        assert ta.confidence == 0.9

    def test_to_dict(self) -> None:
        ta = ThreatAssessment(
            threat_id="T1",
            title="Title",
            severity="LOW",
            attack_vector="LOCAL",
        )
        d = ta.to_dict()
        assert d["threat_id"] == "T1"
        assert d["affected_components"] == []
        assert d["confidence"] == 0.0

    def test_default_values(self) -> None:
        ta = ThreatAssessment(
            threat_id="T2",
            title="T",
            severity="INFO",
            attack_vector="PHYSICAL",
        )
        assert ta.affected_components == []
        assert ta.iocs == []
        assert ta.mitre_tactics == []
        assert ta.applies_to_us is False
        assert ta.confidence == 0.0


class TestExposureReport:
    """Test ExposureReport dataclass."""

    def test_fields_and_defaults(self) -> None:
        er = ExposureReport(threat_id="CVE-2024-00001")
        assert er.exposed is False
        assert er.exposed_components == []
        assert er.risk_score == 0.0
        assert er.recommended_actions == []

    def test_to_dict(self) -> None:
        er = ExposureReport(
            threat_id="CVE-2024-00001",
            exposed=True,
            exposed_components=["fastapi"],
            risk_score=8.5,
            recommended_actions=["Patch now"],
        )
        d = er.to_dict()
        assert d["exposed"] is True
        assert d["risk_score"] == 8.5


class TestMitigation:
    """Test Mitigation dataclass."""

    def test_all_fields(self) -> None:
        m = Mitigation(
            action="PATCH",
            target="fastapi",
            description="Upgrade to latest version.",
            blast_radius="MEDIUM",
            auto_safe=False,
            requires_approval=True,
            rollback_plan="Pin back to old version.",
        )
        assert m.action == "PATCH"
        assert m.requires_approval is True
        assert m.rollback_plan != ""

    def test_to_dict(self) -> None:
        m = Mitigation(
            action="MONITOR",
            target="*",
            description="Watch logs.",
            blast_radius="LOW",
        )
        d = m.to_dict()
        assert d["action"] == "MONITOR"

    def test_action_types(self) -> None:
        valid_actions = {"PATCH", "CONFIG", "BLOCK", "ROTATE", "MONITOR", "ISOLATE"}
        for action in valid_actions:
            m = Mitigation(
                action=action, target="x", description="x", blast_radius="LOW"
            )
            assert m.action == action


class TestHardenedControl:
    """Test HardenedControl dataclass."""

    def test_all_fields(self) -> None:
        hc = HardenedControl(
            control_id="HC-abc123",
            source_threat="CVE-2024-99999",
            check_type="DEPENDENCY",
            check_function="check_cve_2024_99999",
            created_at="2024-01-01T00:00:00Z",
            last_verified="2024-01-01T00:00:00Z",
        )
        assert hc.control_id.startswith("HC-")
        assert hc.check_type == "DEPENDENCY"

    def test_to_dict(self) -> None:
        hc = HardenedControl(
            control_id="HC-1",
            source_threat="T1",
            check_type="CONFIG",
            check_function="check_t1",
        )
        d = hc.to_dict()
        assert d["check_type"] == "CONFIG"
        assert d["last_verified"] is None

    def test_check_types(self) -> None:
        valid = {"DEPENDENCY", "CONFIG", "HEADER", "PERMISSION", "RATE_LIMIT"}
        for ct in valid:
            hc = HardenedControl(
                control_id="HC-x",
                source_threat="T",
                check_type=ct,
                check_function="f",
            )
            assert hc.check_type == ct


class TestThreatIntelDB:
    """Test SQLite persistence for threat intel."""

    def test_save_and_get_assessment(self, intel_db: ThreatIntelDB) -> None:
        ta = ThreatAssessment(
            threat_id="CVE-2024-TEST",
            title="Test",
            severity="HIGH",
            attack_vector="NETWORK",
        )
        intel_db.save_assessment(ta)
        loaded = intel_db.get_assessment("CVE-2024-TEST")
        assert loaded is not None
        assert loaded.threat_id == "CVE-2024-TEST"
        assert loaded.severity == "HIGH"

    def test_get_missing_assessment(self, intel_db: ThreatIntelDB) -> None:
        result = intel_db.get_assessment("NONEXISTENT")
        assert result is None

    def test_save_and_get_control(self, intel_db: ThreatIntelDB) -> None:
        hc = HardenedControl(
            control_id="HC-test1",
            source_threat="CVE-2024-TEST",
            check_type="DEPENDENCY",
            check_function="check_test",
            created_at="2024-01-01T00:00:00Z",
        )
        intel_db.save_control(hc)
        loaded = intel_db.get_control("HC-test1")
        assert loaded is not None
        assert loaded.control_id == "HC-test1"

    def test_list_controls(self, intel_db: ThreatIntelDB) -> None:
        for i in range(3):
            hc = HardenedControl(
                control_id=f"HC-{i}",
                source_threat=f"T-{i}",
                check_type="CONFIG",
                check_function=f"check_{i}",
                created_at=f"2024-01-0{i+1}T00:00:00Z",
            )
            intel_db.save_control(hc)
        controls = intel_db.list_controls()
        assert len(controls) == 3

    def test_cache_put_and_get(self, intel_db: ThreatIntelDB) -> None:
        intel_db.cache_put("key1", {"score": 9.8})
        result = intel_db.cache_get("key1")
        assert result == {"score": 9.8}

    def test_cache_ttl_expired(self, intel_db: ThreatIntelDB) -> None:
        intel_db.cache_put("old_key", {"data": True})
        intel_db._conn.execute(
            "UPDATE api_cache SET fetched_at = ? WHERE cache_key = ?",
            (time.time() - 90_000, "old_key"),
        )
        intel_db._conn.commit()
        result = intel_db.cache_get("old_key")
        assert result is None

    def test_busy_timeout_set(self, intel_db: ThreatIntelDB) -> None:
        row = intel_db._conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000

    def test_upsert_assessment(self, intel_db: ThreatIntelDB) -> None:
        ta1 = ThreatAssessment(
            threat_id="CVE-UPS",
            title="V1",
            severity="LOW",
            attack_vector="LOCAL",
        )
        intel_db.save_assessment(ta1)
        ta2 = ThreatAssessment(
            threat_id="CVE-UPS",
            title="V2",
            severity="HIGH",
            attack_vector="NETWORK",
        )
        intel_db.save_assessment(ta2)
        loaded = intel_db.get_assessment("CVE-UPS")
        assert loaded is not None
        assert loaded.title == "V2"
        assert loaded.severity == "HIGH"


class TestHelperFunctions:
    """Test standalone helper functions."""

    def test_classify_severity_critical(self) -> None:
        assert _classify_severity_from_cvss(9.8) == "CRITICAL"
        assert _classify_severity_from_cvss(9.0) == "CRITICAL"

    def test_classify_severity_high(self) -> None:
        assert _classify_severity_from_cvss(8.5) == "HIGH"
        assert _classify_severity_from_cvss(7.0) == "HIGH"

    def test_classify_severity_medium(self) -> None:
        assert _classify_severity_from_cvss(6.5) == "MEDIUM"
        assert _classify_severity_from_cvss(4.0) == "MEDIUM"

    def test_classify_severity_low(self) -> None:
        assert _classify_severity_from_cvss(3.9) == "LOW"
        assert _classify_severity_from_cvss(0.1) == "LOW"

    def test_classify_severity_info(self) -> None:
        assert _classify_severity_from_cvss(0.0) == "INFO"

    def test_compute_risk_score_exposed(self) -> None:
        score = _compute_risk_score("CRITICAL", "NETWORK", 2, 0.9)
        assert 0.0 <= score <= 10.0
        assert score > 5.0  # Should be high

    def test_compute_risk_score_not_exposed(self) -> None:
        score = _compute_risk_score("CRITICAL", "NETWORK", 0, 0.9)
        assert score == 0.0  # No exposure = 0 risk

    def test_compute_risk_score_low_confidence(self) -> None:
        high_conf = _compute_risk_score("HIGH", "NETWORK", 1, 0.9)
        low_conf = _compute_risk_score("HIGH", "NETWORK", 1, 0.3)
        assert high_conf > low_conf

    def test_compute_risk_score_attack_vector_scaling(self) -> None:
        network = _compute_risk_score("HIGH", "NETWORK", 1, 0.9)
        physical = _compute_risk_score("HIGH", "PHYSICAL", 1, 0.9)
        assert network > physical

    def test_determine_blast_radius(self) -> None:
        assert _determine_blast_radius("BLOCK", "x") == "HIGH"
        assert _determine_blast_radius("ISOLATE", "x") == "HIGH"
        assert _determine_blast_radius("ROTATE", "x") == "HIGH"
        assert _determine_blast_radius("PATCH", "x") == "MEDIUM"
        assert _determine_blast_radius("CONFIG", "x") == "MEDIUM"
        assert _determine_blast_radius("MONITOR", "x") == "LOW"

    def test_is_auto_safe(self) -> None:
        assert _is_auto_safe("MONITOR") is True
        assert _is_auto_safe("PATCH") is False
        assert _is_auto_safe("BLOCK") is False

    def test_requires_approval(self) -> None:
        assert _requires_approval("MONITOR") is False
        assert _requires_approval("PATCH") is True
        assert _requires_approval("ISOLATE") is True

    def test_classify_mitre_tactics_rce(self) -> None:
        text = "Remote code execution vulnerability allowing full system access"
        tactics = _classify_mitre_tactics(text)
        assert "Execution" in tactics

    def test_classify_mitre_tactics_credential(self) -> None:
        text = "Password leak in authentication module exposes credentials"
        tactics = _classify_mitre_tactics(text)
        assert "Credential Access" in tactics

    def test_classify_mitre_tactics_dos(self) -> None:
        text = "Denial of service via malformed request"
        tactics = _classify_mitre_tactics(text)
        assert "Impact" in tactics

    def test_classify_mitre_tactics_empty(self) -> None:
        text = "A benign update with no security implications"
        tactics = _classify_mitre_tactics(text)
        # May or may not match — should not crash
        assert isinstance(tactics, list)

    def test_extract_iocs_cve(self) -> None:
        text = "Affected by CVE-2024-12345 and CVE-2023-99999."
        iocs = _extract_iocs_from_text(text)
        assert "CVE-2024-12345" in iocs
        assert "CVE-2023-99999" in iocs

    def test_extract_iocs_ip(self) -> None:
        text = "Malicious traffic from 192.168.1.100 and 10.0.0.1."
        iocs = _extract_iocs_from_text(text)
        assert "192.168.1.100" in iocs
        assert "10.0.0.1" in iocs

    def test_extract_iocs_sha256(self) -> None:
        sha = "a" * 64
        text = f"Hash: {sha}"
        iocs = _extract_iocs_from_text(text)
        assert sha in iocs

    def test_extract_iocs_empty(self) -> None:
        text = "No indicators here."
        iocs = _extract_iocs_from_text(text)
        assert isinstance(iocs, list)

    def test_extract_affected_packages(self) -> None:
        text = "Affected packages: fastapi < 0.116.0 and pydantic >= 2.0"
        pkgs = _extract_affected_packages_from_text(text)
        assert "fastapi" in pkgs
        assert "pydantic" in pkgs

    def test_extract_affected_packages_empty(self) -> None:
        text = "No packages affected."
        pkgs = _extract_affected_packages_from_text(text)
        assert isinstance(pkgs, list)


class TestDetectInstalledStack:
    """Test stack auto-detection."""

    def test_returns_dict(self) -> None:
        stack = detect_installed_stack()
        assert isinstance(stack, dict)
        assert len(stack) > 0

    def test_includes_python(self) -> None:
        stack = detect_installed_stack()
        assert "python" in stack
        # Should be a version string
        assert "." in stack["python"]

    def test_includes_installed_packages(self) -> None:
        stack = detect_installed_stack()
        # pytest should be installed in test environment
        assert "pytest" in stack


class TestThreatIntelEngineIngestCVE:
    """Test CVE ingestion with mocked APIs."""

    def test_ingest_cve_full(
        self,
        tmp_intel_db: Path,
        mock_nvd_response: dict,
        mock_osv_vuln_response: dict,
    ) -> None:
        http_client = _make_mock_http_client({"nvd.nist.gov": mock_nvd_response, "osv.dev": mock_osv_vuln_response})

        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0", "pydantic": "2.10.0"},
            http_client=http_client,
        )
        assessment = engine.ingest_cve("CVE-2024-99999")

        assert assessment.threat_id == "CVE-2024-99999"
        assert assessment.severity == "CRITICAL"
        assert assessment.attack_vector == "NETWORK"
        assert "fastapi" in assessment.affected_components
        assert assessment.applies_to_us is True
        assert assessment.confidence == 0.9
        engine.close()

    def test_ingest_cve_not_in_our_stack(
        self,
        tmp_intel_db: Path,
        mock_nvd_response: dict,
        mock_osv_vuln_response: dict,
    ) -> None:
        http_client = _make_mock_http_client({"nvd.nist.gov": mock_nvd_response, "osv.dev": mock_osv_vuln_response})

        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"django": "4.0"},  # We don't use fastapi in this mock
            http_client=http_client,
        )
        assessment = engine.ingest_cve("CVE-2024-99999")

        assert assessment.applies_to_us is False
        assert assessment.confidence == 0.3
        engine.close()

    def test_ingest_cve_cached(
        self,
        tmp_intel_db: Path,
        mock_nvd_response: dict,
        mock_osv_vuln_response: dict,
    ) -> None:
        http_client = _make_mock_http_client({"nvd.nist.gov": mock_nvd_response, "osv.dev": mock_osv_vuln_response})

        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            http_client=http_client,
        )
        a1 = engine.ingest_cve("CVE-2024-99999")
        a2 = engine.ingest_cve("CVE-2024-99999")  # Should come from DB
        assert a1.threat_id == a2.threat_id
        assert a1.severity == a2.severity
        engine.close()

    def test_ingest_cve_network_failure(self, tmp_intel_db: Path) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get = MagicMock(side_effect=httpx.HTTPError("Timeout"))
        client.close = MagicMock()

        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            http_client=client,
        )
        assessment = engine.ingest_cve("CVE-2024-FAIL")
        # Should not crash; returns assessment with defaults
        assert assessment.threat_id == "CVE-2024-FAIL"
        assert assessment.severity == "MEDIUM"  # Default
        engine.close()


class TestThreatIntelEngineIngestAdvisory:
    """Test advisory text ingestion."""

    def test_ingest_advisory_with_cves(self, tmp_intel_db: Path) -> None:
        text = (
            "Critical remote code execution in fastapi < 0.116.0.\n"
            "CVE-2024-99999 allows unauthenticated RCE via crafted HTTP request.\n"
            "Affected: fastapi, uvicorn"
        )
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0", "uvicorn": "0.32.0"},
            offline=True,
        )
        assessment = engine.ingest_advisory(text)

        assert assessment.threat_id.startswith("ADVISORY-")
        assert assessment.severity == "CRITICAL"
        assert assessment.attack_vector == "NETWORK"
        assert "CVE-2024-99999" in assessment.iocs
        assert assessment.applies_to_us is True
        assert assessment.confidence > 0.5
        engine.close()

    def test_ingest_advisory_no_cves(self, tmp_intel_db: Path) -> None:
        text = "Medium severity cross-site scripting in web admin panel."
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            offline=True,
        )
        assessment = engine.ingest_advisory(text)

        assert assessment.severity == "MEDIUM"
        assert assessment.confidence == 0.5  # No CVEs, no stack match
        engine.close()

    def test_ingest_advisory_cached(self, tmp_intel_db: Path) -> None:
        text = "Test advisory for caching."
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        a1 = engine.ingest_advisory(text)
        a2 = engine.ingest_advisory(text)  # Same text = same ID = cached
        assert a1.threat_id == a2.threat_id
        engine.close()

    def test_ingest_advisory_local_vector(self, tmp_intel_db: Path) -> None:
        text = "Local file inclusion vulnerability in CLI tool."
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        assessment = engine.ingest_advisory(text)
        assert assessment.attack_vector == "LOCAL"
        engine.close()

    def test_ingest_advisory_extracts_iocs(self, tmp_intel_db: Path) -> None:
        text = (
            "CVE-2024-12345 exploitation observed from 192.168.1.100.\n"
            "Hash: " + "a" * 64
        )
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        assessment = engine.ingest_advisory(text)
        assert "CVE-2024-12345" in assessment.iocs
        assert "192.168.1.100" in assessment.iocs
        engine.close()


class TestThreatIntelEngineCheckExposure:
    """Test exposure checking."""

    def test_exposed(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0", "pydantic": "2.10.0"},
            offline=True,
        )
        threat = ThreatAssessment(
            threat_id="CVE-TEST",
            title="Test",
            severity="HIGH",
            attack_vector="NETWORK",
            affected_components=["fastapi"],
            applies_to_us=True,
            confidence=0.9,
        )
        exposure = engine.check_exposure(threat)

        assert exposure.exposed is True
        assert "fastapi" in exposure.exposed_components
        assert exposure.risk_score > 0.0
        assert len(exposure.recommended_actions) > 0
        engine.close()

    def test_not_exposed(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            offline=True,
        )
        threat = ThreatAssessment(
            threat_id="CVE-DJANGO",
            title="Django vuln",
            severity="CRITICAL",
            attack_vector="NETWORK",
            affected_components=["django"],
            applies_to_us=False,
            confidence=0.3,
        )
        exposure = engine.check_exposure(threat)

        assert exposure.exposed is False
        assert exposure.risk_score == 0.0
        assert any("No direct exposure" in a for a in exposure.recommended_actions)
        engine.close()

    def test_multiple_exposed_components(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0", "pydantic": "2.10.0", "uvicorn": "0.32.0"},
            offline=True,
        )
        threat = ThreatAssessment(
            threat_id="CVE-MULTI",
            title="Multi-pkg vuln",
            severity="CRITICAL",
            attack_vector="NETWORK",
            affected_components=["fastapi", "pydantic", "uvicorn"],
            applies_to_us=True,
            confidence=0.9,
        )
        exposure = engine.check_exposure(threat)

        assert exposure.exposed is True
        assert len(exposure.exposed_components) == 3
        assert exposure.risk_score > 5.0
        engine.close()


class TestThreatIntelEngineSuggestMitigations:
    """Test mitigation suggestion generation."""

    def test_mitigations_for_exposed(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            offline=True,
        )
        exposure = ExposureReport(
            threat_id="CVE-TEST",
            exposed=True,
            exposed_components=["fastapi"],
            risk_score=8.0,
            recommended_actions=["Patch now"],
        )
        mitigations = engine.suggest_mitigations(exposure)

        assert len(mitigations) >= 1
        actions = {m.action for m in mitigations}
        assert "PATCH" in actions
        # High risk should also get MONITOR
        assert "MONITOR" in actions

        # Check rollback plans exist
        for m in mitigations:
            assert m.rollback_plan != ""

        engine.close()

    def test_mitigations_for_not_exposed(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        exposure = ExposureReport(
            threat_id="CVE-SAFE",
            exposed=False,
            exposed_components=[],
            risk_score=0.0,
        )
        mitigations = engine.suggest_mitigations(exposure)

        assert len(mitigations) == 1
        assert mitigations[0].action == "MONITOR"
        assert mitigations[0].auto_safe is True
        assert mitigations[0].requires_approval is False
        engine.close()

    def test_mitigations_critical_risk(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            offline=True,
        )
        exposure = ExposureReport(
            threat_id="CVE-CRIT",
            exposed=True,
            exposed_components=["fastapi"],
            risk_score=9.5,
        )
        mitigations = engine.suggest_mitigations(exposure)

        actions = {m.action for m in mitigations}
        # Critical risk should include ISOLATE
        assert "ISOLATE" in actions
        # ISOLATE should require approval
        isolate_mit = [m for m in mitigations if m.action == "ISOLATE"]
        assert isolate_mit[0].requires_approval is True
        assert isolate_mit[0].blast_radius == "HIGH"
        engine.close()

    def test_mitigation_auto_safe_classification(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            offline=True,
        )
        exposure = ExposureReport(
            threat_id="CVE-MIX",
            exposed=True,
            exposed_components=["fastapi"],
            risk_score=7.5,
        )
        mitigations = engine.suggest_mitigations(exposure)

        auto_safe_mits = [m for m in mitigations if m.auto_safe]
        approval_mits = [m for m in mitigations if m.requires_approval]

        # MONITOR should be auto_safe, PATCH should not
        monitor_mits = [m for m in mitigations if m.action == "MONITOR"]
        patch_mits = [m for m in mitigations if m.action == "PATCH"]
        assert all(m.auto_safe for m in monitor_mits)
        assert all(not m.auto_safe for m in patch_mits)
        engine.close()


class TestThreatIntelEngineDistillControl:
    """Test hardened control distillation."""

    def test_distill_dependency_control(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db,
            stack={"fastapi": "0.115.0"},
            offline=True,
        )
        threat = ThreatAssessment(
            threat_id="CVE-2024-99999",
            title="FastAPI RCE",
            severity="CRITICAL",
            attack_vector="NETWORK",
            affected_components=["fastapi"],
            applies_to_us=True,
            confidence=0.9,
        )
        control = engine.distill_permanent_control(threat, "Upgraded to 0.116.0")

        assert control.control_id.startswith("HC-")
        assert control.source_threat == "CVE-2024-99999"
        assert control.check_type == "DEPENDENCY"
        assert control.check_function.startswith("check_")
        assert control.created_at != ""
        assert control.last_verified is not None
        engine.close()

    def test_distill_control_persisted(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        threat = ThreatAssessment(
            threat_id="CVE-PERSIST",
            title="Test persist",
            severity="LOW",
            attack_vector="LOCAL",
        )
        control = engine.distill_permanent_control(threat, "Fixed config")

        # Should be in DB
        loaded = engine._db.get_control(control.control_id)
        assert loaded is not None
        assert loaded.source_threat == "CVE-PERSIST"
        engine.close()

    def test_distill_header_control(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        threat = ThreatAssessment(
            threat_id="CVE-HEADER",
            title="Missing HSTS header allows MitM",
            severity="MEDIUM",
            attack_vector="NETWORK",
        )
        control = engine.distill_permanent_control(threat, "Added HSTS header")
        assert control.check_type == "HEADER"
        engine.close()

    def test_distill_rate_limit_control(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        threat = ThreatAssessment(
            threat_id="CVE-BRUTE",
            title="Brute force attack via rate limit bypass",
            severity="HIGH",
            attack_vector="NETWORK",
        )
        control = engine.distill_permanent_control(threat, "Added rate limiting")
        assert control.check_type == "RATE_LIMIT"
        engine.close()

    def test_distill_permission_control(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        threat = ThreatAssessment(
            threat_id="CVE-AUTH",
            title="Authentication bypass via permission flaw",
            severity="HIGH",
            attack_vector="NETWORK",
        )
        control = engine.distill_permanent_control(threat, "Fixed auth check")
        assert control.check_type == "PERMISSION"
        engine.close()


class TestThreatIntelEngineStack:
    """Test stack mapping functionality."""

    def test_get_stack(self, tmp_intel_db: Path) -> None:
        stack = {"fastapi": "0.115.0", "pydantic": "2.10.0"}
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack=stack, offline=True
        )
        result = engine.get_stack()
        assert result == stack
        # Modifying result should not change engine state
        result["new"] = "1.0"
        assert "new" not in engine.get_stack()
        engine.close()

    def test_update_stack_manual(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={"old": "1.0"}, offline=True
        )
        new_stack = {"fastapi": "0.116.0", "new_pkg": "2.0"}
        result = engine.update_stack(new_stack)
        assert result == new_stack
        assert engine.get_stack() == new_stack
        engine.close()

    def test_update_stack_auto_detect(self, tmp_intel_db: Path) -> None:
        engine = ThreatIntelEngine(
            db_path=tmp_intel_db, stack={}, offline=True
        )
        result = engine.update_stack()
        assert isinstance(result, dict)
        assert len(result) > 0
        assert "python" in result
        engine.close()


class TestNoForbiddenImports:
    """Ensure security modules do not import from brain or api."""

    def test_dependency_audit_no_brain_import(self) -> None:
        import inspect
        from isg_agent.security import dependency_audit

        source = inspect.getsource(dependency_audit)
        assert "from isg_agent.brain" not in source
        assert "import isg_agent.brain" not in source
        assert "from isg_agent.api" not in source
        assert "import isg_agent.api" not in source

    def test_threat_intel_no_brain_import(self) -> None:
        import inspect
        from isg_agent.security import threat_intel

        source = inspect.getsource(threat_intel)
        assert "from isg_agent.brain" not in source
        assert "import isg_agent.brain" not in source
        assert "from isg_agent.api" not in source
        assert "import isg_agent.api" not in source
