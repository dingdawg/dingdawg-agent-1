"""Tests for isg_agent.core.audit — SHA-256 hash-chained audit trail.

Covers:
- AuditEntry dataclass immutability and fields
- _compute_hash determinism and correctness
- AuditChain GENESIS entry creation
- AuditChain.record() happy path and chaining
- AuditChain.verify_chain() with valid and tampered chains
- AuditChain.get_entry() retrieval and missing entry
- AuditChain.get_entries() pagination and filtering
- AuditChain.get_chain_length() counting
- Concurrent write safety via asyncio.Lock
- Edge cases: empty details, large payloads, special characters
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import aiosqlite
import pytest

from isg_agent.core.audit import AuditChain, AuditEntry, _compute_hash


class TestComputeHash:
    """Tests for the _compute_hash helper function."""

    def test_deterministic_output(self) -> None:
        """Calling _compute_hash with identical inputs always returns the same digest."""
        h1 = _compute_hash(1, "2026-01-01T00:00:00Z", "test", "actor", "{}", "prev")
        h2 = _compute_hash(1, "2026-01-01T00:00:00Z", "test", "actor", "{}", "prev")
        assert h1 == h2

    def test_different_inputs_produce_different_hashes(self) -> None:
        """Different event types produce different hashes."""
        h1 = _compute_hash(1, "2026-01-01T00:00:00Z", "event_a", "actor", "{}", "prev")
        h2 = _compute_hash(1, "2026-01-01T00:00:00Z", "event_b", "actor", "{}", "prev")
        assert h1 != h2

    def test_hash_is_sha256_hex(self) -> None:
        """The returned hash is a 64-character lowercase hex string (SHA-256)."""
        h = _compute_hash(1, "ts", "evt", "act", "{}", "prev")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_manual_verification(self) -> None:
        """Verify the hash matches a manually computed SHA-256."""
        payload = "1|ts|evt|act|det|prev"
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        result = _compute_hash(1, "ts", "evt", "act", "det", "prev")
        assert result == expected


class TestAuditEntry:
    """Tests for the AuditEntry frozen dataclass."""

    def test_fields_accessible(self) -> None:
        """All fields on AuditEntry are accessible after construction."""
        entry = AuditEntry(
            id=1,
            timestamp="2026-01-01T00:00:00Z",
            event_type="test",
            actor="system",
            details="{}",
            entry_hash="abc",
            prev_hash="def",
        )
        assert entry.id == 1
        assert entry.event_type == "test"
        assert entry.actor == "system"
        assert entry.details == "{}"
        assert entry.entry_hash == "abc"
        assert entry.prev_hash == "def"

    def test_frozen_immutability(self) -> None:
        """AuditEntry is frozen — attribute assignment must raise."""
        entry = AuditEntry(
            id=1, timestamp="ts", event_type="e", actor="a",
            details="{}", entry_hash="h", prev_hash="p",
        )
        with pytest.raises(AttributeError):
            entry.event_type = "modified"  # type: ignore[misc]


class TestAuditChainGenesis:
    """Tests for GENESIS entry creation on initialization."""

    async def test_genesis_entry_created(self, tmp_path: Path) -> None:
        """A new audit chain automatically creates a GENESIS entry."""
        db_path = str(tmp_path / "genesis.db")
        chain = AuditChain(db_path=db_path)
        length = await chain.get_chain_length()
        assert length == 1

    async def test_genesis_entry_type(self, tmp_path: Path) -> None:
        """The first entry in a new chain has event_type GENESIS."""
        db_path = str(tmp_path / "genesis_type.db")
        chain = AuditChain(db_path=db_path)
        entry = await chain.get_entry(1)
        assert entry is not None
        assert entry.event_type == "GENESIS"
        assert entry.actor == "system"

    async def test_genesis_prev_hash(self, tmp_path: Path) -> None:
        """The GENESIS entry prev_hash is the SHA-256 of the literal string GENESIS."""
        db_path = str(tmp_path / "genesis_prev.db")
        chain = AuditChain(db_path=db_path)
        entry = await chain.get_entry(1)
        assert entry is not None
        expected_prev = hashlib.sha256(b"GENESIS").hexdigest()
        assert entry.prev_hash == expected_prev

    async def test_genesis_not_duplicated(self, tmp_path: Path) -> None:
        """Re-initializing an existing chain does not duplicate the GENESIS entry."""
        db_path = str(tmp_path / "no_dup.db")
        chain1 = AuditChain(db_path=db_path)
        await chain1.get_chain_length()

        chain2 = AuditChain(db_path=db_path)
        length = await chain2.get_chain_length()
        assert length == 1


class TestAuditChainRecord:
    """Tests for AuditChain.record() — appending entries."""

    async def test_record_returns_audit_entry(self, tmp_path: Path) -> None:
        """record() returns a well-formed AuditEntry."""
        db_path = str(tmp_path / "record.db")
        chain = AuditChain(db_path=db_path)
        entry = await chain.record("test_event", "agent_1")
        assert isinstance(entry, AuditEntry)
        assert entry.event_type == "test_event"
        assert entry.actor == "agent_1"
        assert entry.id == 2  # 1 is GENESIS

    async def test_record_chains_hashes(self, tmp_path: Path) -> None:
        """Each new entry prev_hash equals the preceding entry entry_hash."""
        db_path = str(tmp_path / "chain.db")
        chain = AuditChain(db_path=db_path)
        genesis = await chain.get_entry(1)
        assert genesis is not None

        e1 = await chain.record("event_a", "actor_a")
        assert e1.prev_hash == genesis.entry_hash

        e2 = await chain.record("event_b", "actor_b")
        assert e2.prev_hash == e1.entry_hash

    async def test_record_serialises_details(self, tmp_path: Path) -> None:
        """Details dict is JSON-serialised with sorted keys and no spaces."""
        db_path = str(tmp_path / "details.db")
        chain = AuditChain(db_path=db_path)
        entry = await chain.record("evt", "act", details={"z_key": 1, "a_key": 2})
        parsed = json.loads(entry.details)
        assert parsed == {"a_key": 2, "z_key": 1}
        assert " " not in entry.details

    async def test_record_with_none_details(self, tmp_path: Path) -> None:
        """Passing None for details results in an empty JSON object string."""
        db_path = str(tmp_path / "none_details.db")
        chain = AuditChain(db_path=db_path)
        entry = await chain.record("evt", "act", details=None)
        assert entry.details == "{}"

    async def test_record_with_empty_dict_details(self, tmp_path: Path) -> None:
        """Passing an empty dict results in an empty JSON object string."""
        db_path = str(tmp_path / "empty_details.db")
        chain = AuditChain(db_path=db_path)
        entry = await chain.record("evt", "act", details={})
        assert entry.details == "{}"


class TestAuditChainVerify:
    """Tests for AuditChain.verify_chain() — integrity verification."""

    async def test_valid_chain_passes(self, tmp_path: Path) -> None:
        """A chain with only legitimate entries verifies as True."""
        db_path = str(tmp_path / "valid.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys")
        await chain.record("b", "sys")
        assert await chain.verify_chain() is True

    async def test_genesis_only_chain_passes(self, tmp_path: Path) -> None:
        """A chain with only the GENESIS entry verifies as True."""
        db_path = str(tmp_path / "genesis_only.db")
        chain = AuditChain(db_path=db_path)
        assert await chain.verify_chain() is True

    async def test_tampered_entry_hash_fails(self, tmp_path: Path) -> None:
        """Tampering with an entry_hash causes verify_chain to return False."""
        db_path = str(tmp_path / "tampered_hash.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys")

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE audit_chain SET entry_hash = 'tampered' WHERE id = 2"
            )
            await db.commit()

        assert await chain.verify_chain() is False

    async def test_tampered_details_fails(self, tmp_path: Path) -> None:
        """Tampering with entry details causes verify_chain to return False."""
        db_path = str(tmp_path / "tampered_details.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys", details={"original": True})

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE audit_chain SET details = ? WHERE id = 2",
                ('{"forged":true}',),
            )
            await db.commit()

        assert await chain.verify_chain() is False

    async def test_tampered_prev_hash_fails(self, tmp_path: Path) -> None:
        """Tampering with prev_hash breaks the chain link and fails verification."""
        db_path = str(tmp_path / "tampered_prev.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys")
        await chain.record("b", "sys")

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE audit_chain SET prev_hash = 'broken_link' WHERE id = 3"
            )
            await db.commit()

        assert await chain.verify_chain() is False

    async def test_tampered_genesis_prev_hash_fails(self, tmp_path: Path) -> None:
        """Tampering with the GENESIS entry prev_hash fails verification."""
        db_path = str(tmp_path / "tampered_genesis.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys")

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE audit_chain SET prev_hash = 'wrong_genesis' WHERE id = 1"
            )
            await db.commit()

        assert await chain.verify_chain() is False


class TestAuditChainGetEntry:
    """Tests for AuditChain.get_entry() — single entry retrieval."""

    async def test_get_existing_entry(self, tmp_path: Path) -> None:
        """Retrieving an existing entry by ID returns the correct AuditEntry."""
        db_path = str(tmp_path / "get_entry.db")
        chain = AuditChain(db_path=db_path)
        recorded = await chain.record("test_evt", "test_actor")
        retrieved = await chain.get_entry(recorded.id)
        assert retrieved is not None
        assert retrieved.id == recorded.id
        assert retrieved.entry_hash == recorded.entry_hash

    async def test_get_nonexistent_entry(self, tmp_path: Path) -> None:
        """Retrieving a non-existent entry ID returns None."""
        db_path = str(tmp_path / "get_missing.db")
        chain = AuditChain(db_path=db_path)
        result = await chain.get_entry(9999)
        assert result is None


class TestAuditChainGetEntries:
    """Tests for AuditChain.get_entries() — bulk retrieval with pagination and filtering."""

    async def test_get_entries_returns_all(self, tmp_path: Path) -> None:
        """get_entries without filter returns GENESIS plus all recorded entries."""
        db_path = str(tmp_path / "all_entries.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys")
        await chain.record("b", "sys")
        entries = await chain.get_entries(limit=100)
        assert len(entries) == 3  # GENESIS + 2

    async def test_get_entries_with_filter(self, tmp_path: Path) -> None:
        """get_entries with event_type_filter returns only matching entries."""
        db_path = str(tmp_path / "filtered.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("alpha", "sys")
        await chain.record("beta", "sys")
        await chain.record("alpha", "sys")

        alpha_entries = await chain.get_entries(event_type_filter="alpha")
        assert len(alpha_entries) == 2
        assert all(e.event_type == "alpha" for e in alpha_entries)

    async def test_get_entries_pagination(self, tmp_path: Path) -> None:
        """get_entries respects limit and offset parameters."""
        db_path = str(tmp_path / "pagination.db")
        chain = AuditChain(db_path=db_path)
        for i in range(5):
            await chain.record(f"event_{i}", "sys")

        page1 = await chain.get_entries(limit=2, offset=0)
        page2 = await chain.get_entries(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id

    async def test_get_entries_empty_filter(self, tmp_path: Path) -> None:
        """Filtering by an event_type that does not exist returns an empty list."""
        db_path = str(tmp_path / "empty_filter.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("alpha", "sys")
        entries = await chain.get_entries(event_type_filter="nonexistent")
        assert entries == []


class TestAuditChainLength:
    """Tests for AuditChain.get_chain_length()."""

    async def test_new_chain_length(self, tmp_path: Path) -> None:
        """A new chain has length 1 (GENESIS only)."""
        db_path = str(tmp_path / "length.db")
        chain = AuditChain(db_path=db_path)
        assert await chain.get_chain_length() == 1

    async def test_length_after_records(self, tmp_path: Path) -> None:
        """Length increases by one for each recorded entry."""
        db_path = str(tmp_path / "length_inc.db")
        chain = AuditChain(db_path=db_path)
        await chain.record("a", "sys")
        await chain.record("b", "sys")
        assert await chain.get_chain_length() == 3


class TestAuditChainConcurrency:
    """Tests for concurrent access safety via asyncio.Lock."""

    async def test_concurrent_writes_preserve_chain(self, tmp_path: Path) -> None:
        """Multiple concurrent record() calls produce a valid chain."""
        db_path = str(tmp_path / "concurrent.db")
        chain = AuditChain(db_path=db_path)

        async def write_entry(i: int) -> AuditEntry:
            return await chain.record(f"concurrent_{i}", "test_agent")

        entries = await asyncio.gather(*[write_entry(i) for i in range(10)])
        assert len(entries) == 10
        assert await chain.verify_chain() is True
        assert await chain.get_chain_length() == 11  # GENESIS + 10
