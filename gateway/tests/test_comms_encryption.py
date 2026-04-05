"""Tests for isg_agent.comms.encryption.

Verifies key generation, encrypt/decrypt round-trips, wrong-key rejection,
edge cases (empty string, unicode), and the deterministic compute_hash helper.
"""

from __future__ import annotations

import pytest

from isg_agent.comms.encryption import (
    compute_hash,
    decrypt_message,
    encrypt_message,
    generate_key,
)


class TestGenerateKey:
    """Tests for generate_key()."""

    def test_generate_key_returns_string(self) -> None:
        key = generate_key()
        assert isinstance(key, str)

    def test_generate_key_nonempty(self) -> None:
        key = generate_key()
        assert len(key) > 0

    def test_generate_key_unique(self) -> None:
        """Two calls should return different keys (probabilistically)."""
        k1 = generate_key()
        k2 = generate_key()
        assert k1 != k2


class TestEncryptDecrypt:
    """Tests for encrypt_message / decrypt_message round-trips."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        key = generate_key()
        plaintext = "Hello, agent!"
        ciphertext = encrypt_message(plaintext, key)
        recovered = decrypt_message(ciphertext, key)
        assert recovered == plaintext

    def test_encrypt_returns_string(self) -> None:
        key = generate_key()
        result = encrypt_message("test", key)
        assert isinstance(result, str)

    def test_ciphertext_differs_from_plaintext(self) -> None:
        key = generate_key()
        plaintext = "secret payload"
        ciphertext = encrypt_message(plaintext, key)
        assert ciphertext != plaintext

    def test_encrypt_empty_string(self) -> None:
        key = generate_key()
        ciphertext = encrypt_message("", key)
        recovered = decrypt_message(ciphertext, key)
        assert recovered == ""

    def test_encrypt_unicode(self) -> None:
        key = generate_key()
        plaintext = "Unicode: 你好世界 🍕 Ñ ü"
        ciphertext = encrypt_message(plaintext, key)
        recovered = decrypt_message(ciphertext, key)
        assert recovered == plaintext

    def test_encrypt_long_payload(self) -> None:
        key = generate_key()
        plaintext = "x" * 10_000
        ciphertext = encrypt_message(plaintext, key)
        recovered = decrypt_message(ciphertext, key)
        assert recovered == plaintext

    def test_decrypt_wrong_key_fails(self) -> None:
        key1 = generate_key()
        key2 = generate_key()
        ciphertext = encrypt_message("secret", key1)
        with pytest.raises((ValueError, Exception)):
            decrypt_message(ciphertext, key2)

    def test_decrypt_tampered_ciphertext_fails(self) -> None:
        key = generate_key()
        ciphertext = encrypt_message("original", key)
        # Flip the last few characters to tamper with the ciphertext
        tampered = ciphertext[:-4] + "XXXX"
        with pytest.raises((ValueError, Exception)):
            decrypt_message(tampered, key)


class TestComputeHash:
    """Tests for compute_hash()."""

    def test_compute_hash_returns_string(self) -> None:
        result = compute_hash("data")
        assert isinstance(result, str)

    def test_compute_hash_deterministic(self) -> None:
        h1 = compute_hash("same input")
        h2 = compute_hash("same input")
        assert h1 == h2

    def test_compute_hash_different_inputs(self) -> None:
        h1 = compute_hash("input A")
        h2 = compute_hash("input B")
        assert h1 != h2

    def test_compute_hash_length(self) -> None:
        """SHA-256 hex digest is always 64 characters."""
        result = compute_hash("anything")
        assert len(result) == 64

    def test_compute_hash_empty_string(self) -> None:
        """SHA-256 of empty string is well-defined."""
        result = compute_hash("")
        assert len(result) == 64
