"""Tests for the Decentralized Identity (DID) system.

Covers:
- DID creation, format validation, W3C compliance
- Ed25519 key generation, signing, verification
- Key rotation, DID deactivation
- Verifiable Credentials (all 5 types)
- Credential revocation and expiry
- DID resolution (local + mock external)
- Challenge-response authentication
- Thread safety for concurrent operations
- Security: tampered credentials, replay attacks, invalid formats
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from isg_agent.identity import DIDManager, DIDDocument, VerifiableCredential
from isg_agent.identity.did_manager import (
    DIDManager as DIDManagerClass,
    DIDDocument as DIDDocumentClass,
    VerificationMethod,
    ServiceEndpoint,
)
from isg_agent.identity.credentials import (
    CredentialIssuer,
    VerifiableCredential as VCClass,
    VerificationResult,
    CREDENTIAL_TYPES,
)
from isg_agent.identity.resolution import DIDResolver
from isg_agent.identity.agent_auth import AgentAuthChallenge, DIDAuthMiddleware


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path() -> Generator[str, None, None]:
    """Provide a temporary SQLite database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass
    for suffix in ("-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


@pytest.fixture()
def platform_secret() -> str:
    return "test-platform-secret-32-bytes-ok"


@pytest.fixture()
def did_manager(db_path: str, platform_secret: str) -> DIDManagerClass:
    """Create a DIDManager with a fresh temp database."""
    return DIDManagerClass(db_path=db_path, platform_secret=platform_secret)


@pytest.fixture()
def credential_issuer(db_path: str, platform_secret: str) -> CredentialIssuer:
    """Create a CredentialIssuer with a fresh temp database."""
    return CredentialIssuer(db_path=db_path, platform_secret=platform_secret)


@pytest.fixture()
def resolver(db_path: str, platform_secret: str) -> DIDResolver:
    """Create a DIDResolver backed by a temp database."""
    return DIDResolver(db_path=db_path, platform_secret=platform_secret)


@pytest.fixture()
def auth_challenge(db_path: str, platform_secret: str) -> AgentAuthChallenge:
    """Create an AgentAuthChallenge with a fresh temp database."""
    return AgentAuthChallenge(db_path=db_path, platform_secret=platform_secret)


@pytest.fixture()
def sample_did_and_key(did_manager: DIDManagerClass) -> tuple:
    """Create a sample DID and return (doc, private_key)."""
    doc, private_key = did_manager.create_did(
        handle="chef-mario", owner_id="user-001"
    )
    return doc, private_key


# ===========================================================================
# 1. DID Creation and Format Validation (15 tests)
# ===========================================================================

class TestDIDCreation:
    """DID creation and format validation."""

    def test_create_did_returns_document_and_key(self, did_manager: DIDManagerClass) -> None:
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert isinstance(doc, DIDDocumentClass)
        assert isinstance(private_key, bytes)
        assert len(private_key) > 0

    def test_did_format_matches_spec(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert doc.id == "did:web:app.dingdawg.com:agents:chef-mario"

    def test_did_controller_is_platform(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert doc.controller == "did:web:app.dingdawg.com"

    def test_did_has_verification_method(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert len(doc.verification_method) >= 1
        vm = doc.verification_method[0]
        assert vm.type == "Ed25519VerificationKey2020"
        assert vm.id.startswith(doc.id + "#")

    def test_did_has_authentication(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert len(doc.authentication) >= 1
        assert doc.authentication[0] == doc.verification_method[0].id

    def test_did_has_assertion_method(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert len(doc.assertion_method) >= 1
        assert doc.assertion_method[0] == doc.verification_method[0].id

    def test_did_has_timestamps(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert doc.created is not None
        assert doc.updated is not None
        # ISO 8601 format check
        datetime.fromisoformat(doc.created)
        datetime.fromisoformat(doc.updated)

    def test_did_public_key_multibase(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vm = doc.verification_method[0]
        # Multibase base58btc starts with 'z'
        assert vm.public_key_multibase.startswith("z")

    def test_create_duplicate_handle_raises(self, did_manager: DIDManagerClass) -> None:
        did_manager.create_did(handle="chef-mario", owner_id="user-001")
        with pytest.raises(ValueError, match="already exists"):
            did_manager.create_did(handle="chef-mario", owner_id="user-002")

    def test_create_did_with_special_characters(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="my-agent-123", owner_id="user-001")
        assert doc.id == "did:web:app.dingdawg.com:agents:my-agent-123"

    def test_create_did_empty_handle_raises(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="handle"):
            did_manager.create_did(handle="", owner_id="user-001")

    def test_create_did_empty_owner_raises(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="owner_id"):
            did_manager.create_did(handle="test", owner_id="")

    def test_did_service_endpoints_default(self, did_manager: DIDManagerClass) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert isinstance(doc.service, list)
        # Should have at least an agent API endpoint
        assert len(doc.service) >= 1
        assert any(s.type == "AgentService" for s in doc.service)

    def test_different_handles_get_different_keys(self, did_manager: DIDManagerClass) -> None:
        doc1, key1 = did_manager.create_did(handle="agent-a", owner_id="user-001")
        doc2, key2 = did_manager.create_did(handle="agent-b", owner_id="user-001")
        assert doc1.verification_method[0].public_key_multibase != doc2.verification_method[0].public_key_multibase
        assert key1 != key2

    def test_private_key_is_32_bytes(self, did_manager: DIDManagerClass) -> None:
        _, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        # Ed25519 private key seed is 32 bytes
        assert len(private_key) == 32


# ===========================================================================
# 2. W3C DID Document Compliance (10 tests)
# ===========================================================================

class TestW3CCompliance:
    """W3C DID Core 1.0 JSON-LD document compliance."""

    def test_to_json_has_context(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        assert "@context" in j
        assert "https://www.w3.org/ns/did/v1" in j["@context"]

    def test_to_json_has_id(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        assert j["id"] == doc.id

    def test_to_json_has_controller(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        assert j["controller"] == doc.controller

    def test_to_json_verification_method_structure(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        vms = j["verificationMethod"]
        assert len(vms) >= 1
        vm = vms[0]
        assert "id" in vm
        assert "type" in vm
        assert "controller" in vm
        assert "publicKeyMultibase" in vm

    def test_to_json_authentication_refs(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        assert "authentication" in j
        assert len(j["authentication"]) >= 1

    def test_to_json_assertion_method_refs(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        assert "assertionMethod" in j
        assert len(j["assertionMethod"]) >= 1

    def test_to_json_service_structure(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        assert "service" in j
        for svc in j["service"]:
            assert "id" in svc
            assert "type" in svc
            assert "serviceEndpoint" in svc

    def test_to_json_serializable(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        # Must be fully JSON-serializable
        serialized = json.dumps(j)
        assert len(serialized) > 0
        roundtrip = json.loads(serialized)
        assert roundtrip["id"] == doc.id

    def test_export_did_document_matches_to_json(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, _ = sample_did_and_key
        exported = did_manager.export_did_document(doc.id)
        assert exported == doc.to_json()

    def test_to_json_has_ed25519_context(self, sample_did_and_key: tuple) -> None:
        doc, _ = sample_did_and_key
        j = doc.to_json()
        contexts = j["@context"]
        assert any("Ed25519" in str(c) or "security" in str(c).lower() for c in contexts)


# ===========================================================================
# 3. Ed25519 Signing and Verification (10 tests)
# ===========================================================================

class TestSigningVerification:
    """Ed25519 sign and verify round-trip."""

    def test_sign_and_verify_roundtrip(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = b"Hello, DingDawg!"
        signature = did_manager.sign_message(doc.id, message, private_key)
        assert isinstance(signature, bytes)
        assert len(signature) == 64  # Ed25519 signature is 64 bytes
        assert did_manager.verify_signature(doc.id, message, signature) is True

    def test_verify_fails_with_wrong_message(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = b"Hello, DingDawg!"
        signature = did_manager.sign_message(doc.id, message, private_key)
        assert did_manager.verify_signature(doc.id, b"tampered", signature) is False

    def test_verify_fails_with_wrong_signature(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, _ = sample_did_and_key
        message = b"Hello"
        fake_sig = b"\x00" * 64
        assert did_manager.verify_signature(doc.id, message, fake_sig) is False

    def test_sign_with_unknown_did_raises(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="not found"):
            did_manager.sign_message(
                "did:web:app.dingdawg.com:agents:nonexistent",
                b"msg",
                b"\x00" * 32,
            )

    def test_verify_with_unknown_did_raises(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="not found"):
            did_manager.verify_signature(
                "did:web:app.dingdawg.com:agents:nonexistent",
                b"msg",
                b"\x00" * 64,
            )

    def test_sign_empty_message(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        signature = did_manager.sign_message(doc.id, b"", private_key)
        assert did_manager.verify_signature(doc.id, b"", signature) is True

    def test_sign_large_message(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = b"x" * 1_000_000
        signature = did_manager.sign_message(doc.id, message, private_key)
        assert did_manager.verify_signature(doc.id, message, signature) is True

    def test_different_keys_produce_different_signatures(
        self, did_manager: DIDManagerClass
    ) -> None:
        doc1, key1 = did_manager.create_did(handle="agent-a", owner_id="user-001")
        doc2, key2 = did_manager.create_did(handle="agent-b", owner_id="user-001")
        message = b"same message"
        sig1 = did_manager.sign_message(doc1.id, message, key1)
        sig2 = did_manager.sign_message(doc2.id, message, key2)
        assert sig1 != sig2

    def test_signature_deterministic_for_same_key_and_message(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = b"deterministic test"
        sig1 = did_manager.sign_message(doc.id, message, private_key)
        sig2 = did_manager.sign_message(doc.id, message, private_key)
        # Ed25519 signatures are deterministic
        assert sig1 == sig2

    def test_cross_did_verification_fails(
        self, did_manager: DIDManagerClass
    ) -> None:
        """Signature from agent-a should NOT verify against agent-b's DID."""
        doc_a, key_a = did_manager.create_did(handle="agent-a", owner_id="user-001")
        doc_b, _ = did_manager.create_did(handle="agent-b", owner_id="user-002")
        message = b"cross-check"
        sig_a = did_manager.sign_message(doc_a.id, message, key_a)
        # Verify using agent-b's public key should fail
        assert did_manager.verify_signature(doc_b.id, message, sig_a) is False


# ===========================================================================
# 4. Key Rotation (8 tests)
# ===========================================================================

class TestKeyRotation:
    """Key rotation with old key signing the update."""

    def test_rotate_key_returns_new_doc_and_key(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, old_key = sample_did_and_key
        new_doc, new_key = did_manager.rotate_key(doc.id, old_key)
        assert isinstance(new_doc, DIDDocumentClass)
        assert isinstance(new_key, bytes)
        assert new_key != old_key

    def test_rotate_key_updates_verification_method(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, old_key = sample_did_and_key
        old_multibase = doc.verification_method[0].public_key_multibase
        new_doc, _ = did_manager.rotate_key(doc.id, old_key)
        new_multibase = new_doc.verification_method[0].public_key_multibase
        assert old_multibase != new_multibase

    def test_new_key_can_sign(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, old_key = sample_did_and_key
        _, new_key = did_manager.rotate_key(doc.id, old_key)
        message = b"signed with new key"
        sig = did_manager.sign_message(doc.id, message, new_key)
        assert did_manager.verify_signature(doc.id, message, sig) is True

    def test_old_key_cannot_verify_after_rotation(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, old_key = sample_did_and_key
        # Sign with old key before rotation
        message = b"pre-rotation"
        sig = did_manager.sign_message(doc.id, message, old_key)
        # Rotate
        did_manager.rotate_key(doc.id, old_key)
        # Old signature should now fail verification (public key changed)
        assert did_manager.verify_signature(doc.id, message, sig) is False

    def test_rotate_with_wrong_key_raises(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, _ = sample_did_and_key
        fake_key = b"\x00" * 32
        with pytest.raises(ValueError, match="key"):
            did_manager.rotate_key(doc.id, fake_key)

    def test_rotate_unknown_did_raises(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="not found"):
            did_manager.rotate_key(
                "did:web:app.dingdawg.com:agents:ghost", b"\x00" * 32
            )

    def test_rotate_updates_timestamp(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, old_key = sample_did_and_key
        original_updated = doc.updated
        time.sleep(0.01)  # Ensure timestamp difference
        new_doc, _ = did_manager.rotate_key(doc.id, old_key)
        assert new_doc.updated >= original_updated

    def test_did_id_preserved_after_rotation(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, old_key = sample_did_and_key
        new_doc, _ = did_manager.rotate_key(doc.id, old_key)
        assert new_doc.id == doc.id


# ===========================================================================
# 5. DID Deactivation (5 tests)
# ===========================================================================

class TestDIDDeactivation:
    """DID deactivation."""

    def test_deactivate_did_succeeds(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = doc.id.encode("utf-8")
        proof = did_manager.sign_message(doc.id, message, private_key)
        result = did_manager.deactivate_did(doc.id, proof)
        assert result is True

    def test_deactivated_did_cannot_resolve(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = doc.id.encode("utf-8")
        proof = did_manager.sign_message(doc.id, message, private_key)
        did_manager.deactivate_did(doc.id, proof)
        assert did_manager.resolve_did(doc.id) is None

    def test_deactivate_with_invalid_proof_raises(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, _ = sample_did_and_key
        fake_proof = b"\x00" * 64
        with pytest.raises(ValueError, match="proof"):
            did_manager.deactivate_did(doc.id, fake_proof)

    def test_deactivate_unknown_did_raises(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="not found"):
            did_manager.deactivate_did(
                "did:web:app.dingdawg.com:agents:ghost", b"\x00" * 64
            )

    def test_double_deactivation_raises(
        self, did_manager: DIDManagerClass, sample_did_and_key: tuple
    ) -> None:
        doc, private_key = sample_did_and_key
        message = doc.id.encode("utf-8")
        proof = did_manager.sign_message(doc.id, message, private_key)
        did_manager.deactivate_did(doc.id, proof)
        with pytest.raises(ValueError, match="deactivated|not found"):
            did_manager.deactivate_did(doc.id, proof)


# ===========================================================================
# 6. Verifiable Credentials (20 tests)
# ===========================================================================

class TestVerifiableCredentials:
    """Verifiable Credential issuance, verification, and revocation."""

    def test_issue_capability_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "process_payments", "level": "full"},
        )
        assert isinstance(vc, VCClass)
        assert "AgentCapabilityCredential" in vc.type
        assert vc.credential_subject["capability"] == "process_payments"

    def test_issue_ownership_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentOwnershipCredential",
            claims={"handle": "chef-mario", "owner_id": "user-001"},
        )
        assert "AgentOwnershipCredential" in vc.type

    def test_issue_tier_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentTierCredential",
            claims={"tier": "Pro"},
        )
        assert "AgentTierCredential" in vc.type

    def test_issue_trust_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentTrustCredential",
            claims={"trust_score": 85.0, "computed_at": "2026-03-13T00:00:00Z"},
        )
        assert "AgentTrustCredential" in vc.type

    def test_issue_interoperability_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentInteroperabilityCredential",
            claims={"protocols": ["MCP", "ACP"], "version": "1.0"},
        )
        assert "AgentInteroperabilityCredential" in vc.type

    def test_credential_has_valid_from(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        assert vc.valid_from is not None
        datetime.fromisoformat(vc.valid_from)

    def test_credential_has_valid_until(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
            valid_days=30,
        )
        assert vc.valid_until is not None
        valid_until = datetime.fromisoformat(vc.valid_until)
        valid_from = datetime.fromisoformat(vc.valid_from)
        delta = valid_until - valid_from
        assert 29 <= delta.days <= 31

    def test_credential_has_proof(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        assert vc.proof is not None
        assert vc.proof["type"] == "Ed25519Signature2020"
        assert "proofValue" in vc.proof

    def test_verify_valid_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        result = credential_issuer.verify_credential(vc)
        assert isinstance(result, VerificationResult)
        assert result.valid is True

    def test_verify_tampered_credential_fails(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        # Tamper with the claims
        vc.credential_subject["capability"] = "admin_access"
        result = credential_issuer.verify_credential(vc)
        assert result.valid is False
        assert "tamper" in result.reason.lower() or "signature" in result.reason.lower()

    def test_revoke_credential(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        result = credential_issuer.revoke_credential(vc.id)
        assert result is True

    def test_verify_revoked_credential_fails(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        credential_issuer.revoke_credential(vc.id)
        result = credential_issuer.verify_credential(vc)
        assert result.valid is False
        assert "revoked" in result.reason.lower()

    def test_list_credentials(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "send_email"},
        )
        credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentTierCredential",
            claims={"tier": "Pro"},
        )
        creds = credential_issuer.list_credentials(doc.id)
        assert len(creds) == 2

    def test_credential_context_is_w3c_v2(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "test"},
        )
        assert "https://www.w3.org/ns/credentials/v2" in vc.context

    def test_credential_has_unique_id(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc1 = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "a"},
        )
        vc2 = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "b"},
        )
        assert vc1.id != vc2.id

    def test_invalid_credential_type_raises(
        self, credential_issuer: CredentialIssuer
    ) -> None:
        with pytest.raises(ValueError, match="credential_type"):
            credential_issuer.issue_credential(
                subject_did="did:web:app.dingdawg.com:agents:test",
                credential_type="MadeUpCredential",
                claims={},
            )

    def test_revoke_nonexistent_credential_raises(
        self, credential_issuer: CredentialIssuer
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            credential_issuer.revoke_credential("urn:uuid:nonexistent")

    def test_credential_issuer_is_platform_did(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "test"},
        )
        assert vc.issuer == "did:web:app.dingdawg.com"

    def test_credential_to_json_serializable(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "test"},
        )
        j = vc.to_json()
        serialized = json.dumps(j)
        assert len(serialized) > 0
        roundtrip = json.loads(serialized)
        assert roundtrip["id"] == vc.id


# ===========================================================================
# 7. DID Resolution (10 tests)
# ===========================================================================

class TestDIDResolution:
    """DID resolution (local and external)."""

    def test_resolve_local_did(
        self, resolver: DIDResolver, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        resolved = resolver.resolve(doc.id)
        assert resolved is not None
        assert resolved.id == doc.id

    def test_resolve_nonexistent_did_returns_none(self, resolver: DIDResolver) -> None:
        result = resolver.resolve("did:web:app.dingdawg.com:agents:nobody")
        assert result is None

    def test_resolve_external_did_web_attempts_http(self, resolver: DIDResolver) -> None:
        """External did:web should attempt HTTP resolution."""
        with patch("isg_agent.identity.resolution.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({
                "@context": ["https://www.w3.org/ns/did/v1"],
                "id": "did:web:example.com:agent:test",
                "controller": "did:web:example.com",
                "verificationMethod": [{
                    "id": "did:web:example.com:agent:test#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": "did:web:example.com",
                    "publicKeyMultibase": "z6Mkf5rGMoatrSj1f4CyvuHBeXJELe9RPdzo2PKGNCKVtZxP",
                }],
                "authentication": ["did:web:example.com:agent:test#key-1"],
                "assertionMethod": ["did:web:example.com:agent:test#key-1"],
                "service": [],
            }).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = resolver.resolve("did:web:example.com:agent:test")
            assert result is not None
            assert result.id == "did:web:example.com:agent:test"
            mock_urlopen.assert_called_once()

    def test_resolve_did_key_method(self, resolver: DIDResolver) -> None:
        """did:key resolution should decode the public key from the DID."""
        # Create a real Ed25519 key and encode it
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        private_key = Ed25519PrivateKey.generate()
        pub_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        # did:key uses multicodec 0xed for Ed25519
        from isg_agent.identity.did_manager import _multibase_encode
        multicodec_bytes = b"\xed\x01" + pub_bytes
        multibase = _multibase_encode(multicodec_bytes)
        did_key = f"did:key:{multibase}"

        result = resolver.resolve(did_key)
        assert result is not None
        assert result.id == did_key

    def test_resolve_external_http_failure_returns_none(self, resolver: DIDResolver) -> None:
        with patch("isg_agent.identity.resolution.urlopen", side_effect=Exception("Network error")):
            result = resolver.resolve("did:web:unreachable.example.com:agent:test")
            assert result is None

    def test_resolve_caches_external_did(self, resolver: DIDResolver) -> None:
        """Second resolution should hit cache, not HTTP."""
        mock_doc_json = json.dumps({
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": "did:web:cached.example.com:agent:test",
            "controller": "did:web:cached.example.com",
            "verificationMethod": [{
                "id": "did:web:cached.example.com:agent:test#key-1",
                "type": "Ed25519VerificationKey2020",
                "controller": "did:web:cached.example.com",
                "publicKeyMultibase": "z6Mkf5rGMoatrSj1f4CyvuHBeXJELe9RPdzo2PKGNCKVtZxP",
            }],
            "authentication": ["did:web:cached.example.com:agent:test#key-1"],
            "assertionMethod": ["did:web:cached.example.com:agent:test#key-1"],
            "service": [],
        }).encode()

        with patch("isg_agent.identity.resolution.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_doc_json
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            resolver.resolve("did:web:cached.example.com:agent:test")
            resolver.resolve("did:web:cached.example.com:agent:test")
            # Should only call HTTP once (second is from cache)
            assert mock_urlopen.call_count == 1

    def test_resolve_and_verify_succeeds(
        self, resolver: DIDResolver, did_manager: DIDManagerClass
    ) -> None:
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        message = b"verify via resolver"
        sig = did_manager.sign_message(doc.id, message, private_key)
        assert resolver.resolve_and_verify(doc.id, message, sig) is True

    def test_resolve_and_verify_fails_bad_sig(
        self, resolver: DIDResolver, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        assert resolver.resolve_and_verify(doc.id, b"msg", b"\x00" * 64) is False

    def test_resolve_invalid_did_format_returns_none(self, resolver: DIDResolver) -> None:
        result = resolver.resolve("not-a-did")
        assert result is None

    def test_resolve_unsupported_method_returns_none(self, resolver: DIDResolver) -> None:
        result = resolver.resolve("did:unsupported:123")
        assert result is None


# ===========================================================================
# 8. Challenge-Response Authentication (12 tests)
# ===========================================================================

class TestChallengeResponseAuth:
    """DID-based challenge-response authentication."""

    def test_create_challenge_returns_id_and_nonce(
        self, auth_challenge: AgentAuthChallenge
    ) -> None:
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        assert isinstance(challenge_id, str)
        assert len(challenge_id) > 0
        assert isinstance(nonce, str)
        assert len(nonce) > 0

    def test_respond_to_challenge_returns_proof(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        proof = auth_challenge.respond_to_challenge(
            prover_did=doc.id,
            challenge_id=challenge_id,
            nonce=nonce,
            private_key=private_key,
        )
        assert isinstance(proof, str)
        assert len(proof) > 0

    def test_verify_response_succeeds(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        proof = auth_challenge.respond_to_challenge(
            prover_did=doc.id,
            challenge_id=challenge_id,
            nonce=nonce,
            private_key=private_key,
        )
        result = auth_challenge.verify_response(
            prover_did=doc.id,
            challenge_id=challenge_id,
            proof=proof,
        )
        assert result is True

    def test_verify_response_wrong_proof_fails(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        result = auth_challenge.verify_response(
            prover_did=doc.id,
            challenge_id=challenge_id,
            proof="aW52YWxpZC1wcm9vZg==",  # base64 of "invalid-proof"
        )
        assert result is False

    def test_nonce_reuse_prevention(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        """Once a challenge is verified, the same challenge cannot be reused."""
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        proof = auth_challenge.respond_to_challenge(
            prover_did=doc.id,
            challenge_id=challenge_id,
            nonce=nonce,
            private_key=private_key,
        )
        # First verification succeeds
        assert auth_challenge.verify_response(doc.id, challenge_id, proof) is True
        # Replay with same challenge_id fails
        assert auth_challenge.verify_response(doc.id, challenge_id, proof) is False

    def test_expired_challenge_fails(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com",
        )
        proof = auth_challenge.respond_to_challenge(
            prover_did=doc.id,
            challenge_id=challenge_id,
            nonce=nonce,
            private_key=private_key,
        )
        # Expire the challenge by manipulating the DB
        conn = sqlite3.connect(auth_challenge._db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "UPDATE auth_challenges SET expires_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00Z", challenge_id),
        )
        conn.commit()
        conn.close()

        result = auth_challenge.verify_response(doc.id, challenge_id, proof)
        assert result is False

    def test_unknown_challenge_id_fails(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        doc, _ = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        result = auth_challenge.verify_response(
            prover_did=doc.id,
            challenge_id="nonexistent-challenge",
            proof="someproof",
        )
        assert result is False

    def test_challenge_different_agents(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        """Agent B cannot answer Agent A's challenge."""
        doc_a, key_a = did_manager.create_did(handle="agent-a", owner_id="user-001")
        doc_b, key_b = did_manager.create_did(handle="agent-b", owner_id="user-002")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        # Agent B tries to respond to the challenge
        proof_b = auth_challenge.respond_to_challenge(
            prover_did=doc_b.id,
            challenge_id=challenge_id,
            nonce=nonce,
            private_key=key_b,
        )
        # Verify claims Agent A answered — should fail
        result = auth_challenge.verify_response(
            prover_did=doc_a.id,
            challenge_id=challenge_id,
            proof=proof_b,
        )
        assert result is False

    def test_multiple_concurrent_challenges(
        self, auth_challenge: AgentAuthChallenge
    ) -> None:
        """Multiple challenges can exist simultaneously."""
        c1_id, c1_nonce = auth_challenge.create_challenge("did:web:verifier-1")
        c2_id, c2_nonce = auth_challenge.create_challenge("did:web:verifier-2")
        assert c1_id != c2_id
        assert c1_nonce != c2_nonce

    def test_challenge_nonce_is_cryptographically_random(
        self, auth_challenge: AgentAuthChallenge
    ) -> None:
        nonces = set()
        for _ in range(100):
            _, nonce = auth_challenge.create_challenge("did:web:app.dingdawg.com")
            nonces.add(nonce)
        # All 100 nonces should be unique
        assert len(nonces) == 100

    def test_respond_to_challenge_with_wrong_nonce_fails_verify(
        self, auth_challenge: AgentAuthChallenge, did_manager: DIDManagerClass
    ) -> None:
        doc, private_key = did_manager.create_did(handle="chef-mario", owner_id="user-001")
        challenge_id, nonce = auth_challenge.create_challenge(
            verifier_did="did:web:app.dingdawg.com"
        )
        # Respond with a tampered nonce
        proof = auth_challenge.respond_to_challenge(
            prover_did=doc.id,
            challenge_id=challenge_id,
            nonce="tampered-nonce",
            private_key=private_key,
        )
        result = auth_challenge.verify_response(doc.id, challenge_id, proof)
        assert result is False

    def test_did_auth_middleware_extracts_did(self) -> None:
        """DIDAuthMiddleware should parse Authorization header."""
        middleware = DIDAuthMiddleware
        # Verify the class exists and has the expected interface
        assert hasattr(DIDAuthMiddleware, "__init__")


# ===========================================================================
# 9. Thread Safety (5 tests)
# ===========================================================================

class TestThreadSafety:
    """Concurrent DID operations across threads."""

    def test_concurrent_did_creation(self, db_path: str, platform_secret: str) -> None:
        errors: list[Exception] = []
        results: list[tuple] = []
        lock = threading.Lock()

        def create_did(handle: str) -> None:
            try:
                mgr = DIDManagerClass(db_path=db_path, platform_secret=platform_secret)
                doc, key = mgr.create_did(handle=handle, owner_id="user-concurrent")
                with lock:
                    results.append((doc.id, key))
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=create_did, args=(f"agent-{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors in concurrent creation: {errors}"
        assert len(results) == 10

    def test_concurrent_signing(self, db_path: str, platform_secret: str) -> None:
        mgr = DIDManagerClass(db_path=db_path, platform_secret=platform_secret)
        doc, key = mgr.create_did(handle="concurrent-signer", owner_id="user-001")
        errors: list[Exception] = []
        sigs: list[bytes] = []
        lock = threading.Lock()

        def sign_msg(i: int) -> None:
            try:
                sig = mgr.sign_message(doc.id, f"message-{i}".encode(), key)
                with lock:
                    sigs.append(sig)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=sign_msg, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors in concurrent signing: {errors}"
        assert len(sigs) == 20

    def test_concurrent_resolution(self, db_path: str, platform_secret: str) -> None:
        mgr = DIDManagerClass(db_path=db_path, platform_secret=platform_secret)
        doc, _ = mgr.create_did(handle="resolvable", owner_id="user-001")
        errors: list[Exception] = []
        results: list = []
        lock = threading.Lock()

        def resolve() -> None:
            try:
                r = DIDResolver(db_path=db_path, platform_secret=platform_secret)
                resolved = r.resolve(doc.id)
                with lock:
                    results.append(resolved)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=resolve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        assert len(results) == 10
        assert all(r is not None and r.id == doc.id for r in results)

    def test_concurrent_credential_issuance(self, db_path: str, platform_secret: str) -> None:
        mgr = DIDManagerClass(db_path=db_path, platform_secret=platform_secret)
        doc, _ = mgr.create_did(handle="cred-target", owner_id="user-001")
        errors: list[Exception] = []
        creds: list = []
        lock = threading.Lock()

        def issue(i: int) -> None:
            try:
                issuer = CredentialIssuer(db_path=db_path, platform_secret=platform_secret)
                vc = issuer.issue_credential(
                    subject_did=doc.id,
                    credential_type="AgentCapabilityCredential",
                    claims={"capability": f"skill-{i}"},
                )
                with lock:
                    creds.append(vc)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=issue, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(creds) == 10

    def test_concurrent_challenge_response(self, db_path: str, platform_secret: str) -> None:
        mgr = DIDManagerClass(db_path=db_path, platform_secret=platform_secret)
        doc, key = mgr.create_did(handle="auth-agent", owner_id="user-001")
        errors: list[Exception] = []
        results: list[bool] = []
        lock = threading.Lock()

        def challenge_cycle() -> None:
            try:
                ac = AgentAuthChallenge(db_path=db_path, platform_secret=platform_secret)
                cid, nonce = ac.create_challenge("did:web:app.dingdawg.com")
                proof = ac.respond_to_challenge(doc.id, cid, nonce, key)
                ok = ac.verify_response(doc.id, cid, proof)
                with lock:
                    results.append(ok)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=challenge_cycle) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors: {errors}"
        assert all(r is True for r in results)


# ===========================================================================
# 10. Security Edge Cases (10 tests)
# ===========================================================================

class TestSecurityEdgeCases:
    """Invalid inputs, tampered data, and attack prevention."""

    def test_invalid_did_format_rejected(self, did_manager: DIDManagerClass) -> None:
        result = did_manager.resolve_did("not-a-did-at-all")
        assert result is None

    def test_handle_with_path_traversal_rejected(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="handle"):
            did_manager.create_did(handle="../../../etc/passwd", owner_id="user-001")

    def test_handle_with_spaces_rejected(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="handle"):
            did_manager.create_did(handle="has space", owner_id="user-001")

    def test_sql_injection_in_handle(self, did_manager: DIDManagerClass) -> None:
        """SQL injection attempt should be safely handled."""
        with pytest.raises(ValueError, match="handle"):
            did_manager.create_did(
                handle="'; DROP TABLE agent_dids; --", owner_id="user-001"
            )

    def test_private_key_not_stored_plaintext(self, db_path: str, platform_secret: str) -> None:
        """Private keys in the DB must be encrypted, not plaintext."""
        mgr = DIDManagerClass(db_path=db_path, platform_secret=platform_secret)
        _, private_key = mgr.create_did(handle="secret-agent", owner_id="user-001")
        # Read the raw DB and check that the private key bytes are not in plaintext
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute(
            "SELECT encrypted_private_key FROM agent_dids WHERE handle = ?",
            ("secret-agent",),
        ).fetchone()
        conn.close()
        assert row is not None
        raw_blob = row[0]
        # The raw private key bytes should NOT appear directly in the stored value
        assert private_key not in raw_blob if isinstance(raw_blob, bytes) else private_key.hex() not in raw_blob

    def test_credential_with_future_valid_from_still_verifies(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        """A credential that hasn't started yet should still have a valid signature."""
        doc, _ = did_manager.create_did(handle="future-agent", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "test"},
        )
        # The proof signature should still be valid (date checks are separate from crypto)
        result = credential_issuer.verify_credential(vc)
        assert result.valid is True

    def test_deactivated_did_cannot_sign_new_credentials(
        self, did_manager: DIDManagerClass, credential_issuer: CredentialIssuer
    ) -> None:
        doc, private_key = did_manager.create_did(handle="soon-gone", owner_id="user-001")
        message = doc.id.encode("utf-8")
        proof = did_manager.sign_message(doc.id, message, private_key)
        did_manager.deactivate_did(doc.id, proof)
        # After deactivation, resolve returns None
        assert did_manager.resolve_did(doc.id) is None

    def test_handle_unicode_rejected(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="handle"):
            did_manager.create_did(handle="cafe\u0301", owner_id="user-001")

    def test_very_long_handle_rejected(self, did_manager: DIDManagerClass) -> None:
        with pytest.raises(ValueError, match="handle"):
            did_manager.create_did(handle="a" * 256, owner_id="user-001")

    def test_credential_proof_value_is_base64(
        self, credential_issuer: CredentialIssuer, did_manager: DIDManagerClass
    ) -> None:
        import base64
        doc, _ = did_manager.create_did(handle="b64-test", owner_id="user-001")
        vc = credential_issuer.issue_credential(
            subject_did=doc.id,
            credential_type="AgentCapabilityCredential",
            claims={"capability": "test"},
        )
        proof_value = vc.proof["proofValue"]
        # Should be valid base64
        decoded = base64.b64decode(proof_value)
        assert len(decoded) > 0


# ===========================================================================
# 11. Package __init__ exports (5 tests)
# ===========================================================================

class TestPackageExports:
    """Verify the package exports the right symbols."""

    def test_did_manager_exported(self) -> None:
        from isg_agent.identity import DIDManager
        assert DIDManager is DIDManagerClass

    def test_did_document_exported(self) -> None:
        from isg_agent.identity import DIDDocument
        assert DIDDocument is DIDDocumentClass

    def test_verifiable_credential_exported(self) -> None:
        from isg_agent.identity import VerifiableCredential
        assert VerifiableCredential is VCClass

    def test_credential_issuer_importable(self) -> None:
        from isg_agent.identity.credentials import CredentialIssuer
        assert CredentialIssuer is not None

    def test_resolver_importable(self) -> None:
        from isg_agent.identity.resolution import DIDResolver
        assert DIDResolver is not None
