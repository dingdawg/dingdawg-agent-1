"""Tests for isg_agent.agents.handle_service."""

from __future__ import annotations

import pytest

from isg_agent.agents.handle_service import HandleService


class TestValidateHandle:
    """Tests for HandleService.validate_handle."""

    def test_validate_handle_valid(self) -> None:
        valid, reason = HandleService.validate_handle("joes-pizza")
        assert valid is True
        assert reason == ""

    def test_validate_handle_too_short(self) -> None:
        valid, reason = HandleService.validate_handle("ab")
        assert valid is False
        assert "at least" in reason

    def test_validate_handle_too_long(self) -> None:
        valid, reason = HandleService.validate_handle("a" * 31)
        assert valid is False
        assert "at most" in reason

    def test_validate_handle_invalid_chars(self) -> None:
        valid, reason = HandleService.validate_handle("Hello_World")
        assert valid is False

    def test_validate_handle_reserved(self) -> None:
        valid, reason = HandleService.validate_handle("admin")
        assert valid is False
        assert "reserved" in reason

    def test_validate_handle_starts_with_number(self) -> None:
        valid, _ = HandleService.validate_handle("1abc")
        assert valid is False

    def test_validate_handle_ends_with_hyphen(self) -> None:
        valid, _ = HandleService.validate_handle("abc-")
        assert valid is False

    def test_validate_handle_consecutive_hyphens(self) -> None:
        valid, _ = HandleService.validate_handle("abc--def")
        assert valid is False

class TestHandleLifecycle:
    """Tests for handle reservation, claiming, and release."""

    async def test_is_available(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            assert await svc.is_available("fresh-handle") is True
        finally:
            await svc.close()

    async def test_reserve_and_claim(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            ok = await svc.reserve_handle("my-handle")
            assert ok is True
            assert await svc.is_available("my-handle") is False
            claimed = await svc.claim_handle("my-handle", "agent-123")
            assert claimed is True
            info = await svc.get_handle_info("my-handle")
            assert info is not None
            assert info["agent_id"] == "agent-123"
        finally:
            await svc.close()

    async def test_release_handle(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            await svc.reserve_handle("temp-handle")
            released = await svc.release_handle("temp-handle")
            assert released is True
            assert await svc.is_available("temp-handle") is True
        finally:
            await svc.close()

    async def test_claim_taken_handle_fails(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            await svc.claim_handle("owned-handle", "agent-a")
            fail = await svc.claim_handle("owned-handle", "agent-b")
            assert fail is False
        finally:
            await svc.close()

    async def test_claim_without_reserve(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            ok = await svc.claim_handle("direct-claim", "agent-x")
            assert ok is True
            info = await svc.get_handle_info("direct-claim")
            assert info is not None
            assert info["agent_id"] == "agent-x"
        finally:
            await svc.close()

    async def test_reserve_invalid_handle_returns_false(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            assert await svc.reserve_handle("ab") is False
        finally:
            await svc.close()

    async def test_release_nonexistent_returns_false(self) -> None:
        svc = HandleService(db_path=":memory:")
        try:
            assert await svc.release_handle("ghost-handle") is False
        finally:
            await svc.close()
