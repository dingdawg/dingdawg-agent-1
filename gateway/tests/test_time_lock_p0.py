"""P0 tests for time_lock.py — unknown risk tier fail-closed fix.

Verifies that passing an unknown risk tier to TimeLockManager.schedule() raises
ValueError instead of silently defaulting to zero delay.
"""

import pytest

from isg_agent.core.time_lock import TimeLockManager


class TestUnknownRiskTierFailsClosed:
    """Tests that unknown risk tiers raise ValueError (fail-closed)."""

    @pytest.mark.asyncio
    async def test_unknown_tier_raises_value_error(self) -> None:
        """An unrecognized risk tier string must raise ValueError."""
        manager = TimeLockManager()
        with pytest.raises(ValueError, match="Unknown risk tier"):
            await manager.schedule("dangerous action", "SUPER_SECRET")

    @pytest.mark.asyncio
    async def test_unknown_tier_garbage_raises_value_error(self) -> None:
        """Completely garbage tier strings must raise ValueError."""
        manager = TimeLockManager()
        with pytest.raises(ValueError, match="Unknown risk tier"):
            await manager.schedule("some action", "NOT_A_REAL_TIER")

    @pytest.mark.asyncio
    async def test_empty_tier_raises_value_error(self) -> None:
        """An empty string risk tier must raise ValueError."""
        manager = TimeLockManager()
        with pytest.raises(ValueError, match="Unknown risk tier"):
            await manager.schedule("some action", "")


class TestKnownTiersStillWork:
    """Tests that all four known tiers still function correctly."""

    @pytest.mark.asyncio
    async def test_low_tier_works(self) -> None:
        """LOW tier should succeed with immediate execution (0 delay)."""
        manager = TimeLockManager()
        entry = await manager.schedule("read a file", "LOW")
        assert entry.risk_tier == "LOW"
        assert entry.status == "executed"  # 0 delay -> immediate execution

    @pytest.mark.asyncio
    async def test_medium_tier_works(self) -> None:
        """MEDIUM tier should succeed with immediate execution (0 delay by default)."""
        manager = TimeLockManager()
        entry = await manager.schedule("update config", "MEDIUM")
        assert entry.risk_tier == "MEDIUM"
        assert entry.status == "executed"  # 0 delay -> immediate execution

    @pytest.mark.asyncio
    async def test_high_tier_works(self) -> None:
        """HIGH tier should succeed with 30-second cooling period."""
        manager = TimeLockManager()
        entry = await manager.schedule("delete backup", "HIGH")
        assert entry.risk_tier == "HIGH"
        assert entry.status == "pending"  # 30s delay -> pending

    @pytest.mark.asyncio
    async def test_critical_tier_works(self) -> None:
        """CRITICAL tier should succeed with 60-second cooling period."""
        manager = TimeLockManager()
        entry = await manager.schedule("drop production table", "CRITICAL")
        assert entry.risk_tier == "CRITICAL"
        assert entry.status == "pending"  # 60s delay -> pending

    @pytest.mark.asyncio
    async def test_case_insensitive_tier(self) -> None:
        """Tier matching should be case-insensitive (lowered input accepted)."""
        manager = TimeLockManager()
        entry = await manager.schedule("read a file", "low")
        assert entry.risk_tier == "LOW"
        assert entry.status == "executed"
