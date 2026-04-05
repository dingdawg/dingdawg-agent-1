"""Marketplace registry: CRUD and workflow operations for community templates.

Provides persistent management of the marketplace ecosystem:
- Listing creation and lifecycle (draft → submitted → approved → published)
- Install recording with revenue-split accounting
- Rating and review management with running average recalculation
- Template forking (clone + create new draft)
- Creator earnings aggregation

All public methods are coroutines.  Uses the same async aiosqlite pattern
as TemplateRegistry and AgentRegistry: db_path constructor parameter,
in-memory keepalive for test isolation, lazy initialisation.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

__all__ = ["MarketplaceRegistry"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed status transitions
# ---------------------------------------------------------------------------

_EDITABLE_STATUSES = {"draft", "rejected"}
_SUBMIT_FROM = {"draft", "rejected"}
_APPROVE_FROM = {"submitted", "under_review"}
_REJECT_FROM = {"submitted", "under_review"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# MarketplaceRegistry
# ---------------------------------------------------------------------------


class MarketplaceRegistry:
    """Manages marketplace template listings backed by SQLite.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Use ``:memory:`` for tests.
    """

    def __init__(self, db_path: str = "data/agent.db") -> None:
        self._db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._initialized = False
        self._keepalive: Optional[aiosqlite.Connection] = None

        if self._is_memory:
            import secrets
            _rand = secrets.token_hex(8)
            self._connect_path = (
                f"file:marketplace_registry_{_rand}?mode=memory&cache=shared"
            )
            self._connect_uri = True
        else:
            self._connect_path = db_path
            self._connect_uri = False

    # -- Lifecycle -----------------------------------------------------------

    async def _ensure_initialized(self) -> None:
        """Ensure the marketplace tables exist on first use."""
        if self._initialized:
            return

        if not self._is_memory:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        if self._is_memory and self._keepalive is None:
            self._keepalive = await aiosqlite.connect(
                self._connect_path, uri=self._connect_uri
            )

        # Create tables for both in-memory and file-based DBs.  The
        # CREATE TABLE IF NOT EXISTS statements are idempotent so it is safe
        # to call this on every startup even when create_tables() has already
        # run from the Database engine.
        async with aiosqlite.connect(
            self._connect_path, uri=self._connect_uri
        ) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS marketplace_templates (
                    id                      TEXT    PRIMARY KEY,
                    base_template_id        TEXT    NOT NULL,
                    author_user_id          TEXT    NOT NULL,
                    forked_from_id          TEXT,
                    display_name            TEXT    NOT NULL,
                    tagline                 TEXT    NOT NULL DEFAULT '',
                    description_md          TEXT    NOT NULL DEFAULT '',
                    preview_json            TEXT    NOT NULL DEFAULT '{}',
                    tags                    TEXT    NOT NULL DEFAULT '[]',
                    agent_type              TEXT    NOT NULL,
                    industry_type           TEXT,
                    status                  TEXT    NOT NULL DEFAULT 'draft',
                    rejection_reason        TEXT,
                    reviewed_by             TEXT,
                    reviewed_at             TEXT,
                    submitted_at            TEXT,
                    published_at            TEXT,
                    price_cents             INTEGER NOT NULL DEFAULT 0,
                    stripe_price_id         TEXT,
                    revenue_share_pct       INTEGER NOT NULL DEFAULT 70,
                    install_count           INTEGER NOT NULL DEFAULT 0,
                    fork_count              INTEGER NOT NULL DEFAULT 0,
                    avg_rating              REAL    NOT NULL DEFAULT 0.0,
                    rating_count            INTEGER NOT NULL DEFAULT 0,
                    created_at              TEXT    NOT NULL,
                    updated_at              TEXT    NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS template_ratings (
                    id                      TEXT    PRIMARY KEY,
                    marketplace_template_id TEXT    NOT NULL,
                    user_id                 TEXT    NOT NULL,
                    stars                   INTEGER NOT NULL,
                    review_text             TEXT,
                    helpful_count           INTEGER NOT NULL DEFAULT 0,
                    created_at              TEXT    NOT NULL,
                    updated_at              TEXT    NOT NULL,
                    UNIQUE(marketplace_template_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS template_installs (
                    id                      TEXT    PRIMARY KEY,
                    marketplace_template_id TEXT    NOT NULL,
                    base_template_id        TEXT    NOT NULL,
                    installer_user_id       TEXT    NOT NULL,
                    agent_id                TEXT    NOT NULL,
                    payment_intent_id       TEXT,
                    amount_paid_cents       INTEGER NOT NULL DEFAULT 0,
                    platform_fee_cents      INTEGER NOT NULL DEFAULT 0,
                    creator_payout_cents    INTEGER NOT NULL DEFAULT 0,
                    payout_status           TEXT    NOT NULL DEFAULT 'not_applicable',
                    installed_at            TEXT    NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS creator_profiles (
                    user_id                 TEXT    PRIMARY KEY,
                    display_name            TEXT    NOT NULL DEFAULT '',
                    bio                     TEXT    NOT NULL DEFAULT '',
                    stripe_connect_id       TEXT,
                    connect_verified        INTEGER NOT NULL DEFAULT 0,
                    total_earned_cents      INTEGER NOT NULL DEFAULT 0,
                    template_count          INTEGER NOT NULL DEFAULT 0,
                    created_at              TEXT    NOT NULL,
                    updated_at              TEXT    NOT NULL
                )
            """)
            await db.commit()

        self._initialized = True

    def _connect(self) -> "aiosqlite.connect":  # type: ignore[name-defined]
        return aiosqlite.connect(self._connect_path, uri=self._connect_uri)

    async def close(self) -> None:
        """Release resources (keepalive connection for in-memory DBs)."""
        if self._keepalive is not None:
            await self._keepalive.close()
            self._keepalive = None

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
        """Convert an aiosqlite.Row to a plain dict."""
        return dict(row)

    async def _get_listing_raw(
        self, db: aiosqlite.Connection, listing_id: str
    ) -> Optional[dict[str, Any]]:
        """Fetch a single marketplace_templates row by id."""
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM marketplace_templates WHERE id = ?",
            (listing_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    # -- Public API ----------------------------------------------------------

    async def create_listing(
        self,
        base_template_id: str,
        author_user_id: str,
        display_name: str,
        tagline: str,
        description_md: str,
        agent_type: str,
        industry_type: Optional[str] = None,
        price_cents: int = 0,
        tags: Optional[list[str]] = None,
        preview_json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a new marketplace listing in draft status.

        Parameters
        ----------
        base_template_id:
            ID of the base agent_templates row this listing builds on.
        author_user_id:
            The creator's user ID.
        display_name:
            Public-facing name for the listing.
        tagline:
            Short one-liner shown in browse views.
        description_md:
            Full markdown description.
        agent_type:
            Agent type string (e.g. ``"business"``).
        industry_type:
            Optional industry slug (e.g. ``"restaurant"``).
        price_cents:
            Price in US cents (0 = free).
        tags:
            List of string tags for discoverability.
        preview_json:
            Optional preview configuration dict.

        Returns
        -------
        dict
            The created listing record.
        """
        await self._ensure_initialized()
        now = _now()
        listing_id = _uid()
        tags_str = json.dumps(tags or [])
        preview_str = json.dumps(preview_json or {})

        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO marketplace_templates (
                    id, base_template_id, author_user_id, display_name,
                    tagline, description_md, preview_json, tags,
                    agent_type, industry_type, status, price_cents,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    listing_id, base_template_id, author_user_id, display_name,
                    tagline, description_md, preview_str, tags_str,
                    agent_type, industry_type, "draft", price_cents,
                    now, now,
                ),
            )
            await db.commit()

            # Upsert creator profile (ensure row exists)
            await db.execute(
                """
                INSERT INTO creator_profiles (user_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    template_count = template_count + 1,
                    updated_at = excluded.updated_at
                """,
                (author_user_id, now, now),
            )
            await db.commit()

            row = await self._get_listing_raw(db, listing_id)

        logger.info(
            "marketplace: listing created id=%s author=%s name=%r",
            listing_id, author_user_id, display_name,
        )
        return row  # type: ignore[return-value]

    async def list_listings(
        self,
        status: Optional[str] = None,
        agent_type: Optional[str] = None,
        industry_type: Optional[str] = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Return a paginated list of marketplace listings.

        Parameters
        ----------
        status:
            Filter by listing status (defaults to ``"approved"`` when None).
        agent_type:
            Optional agent_type filter.
        industry_type:
            Optional industry_type filter.
        sort:
            Sort order: ``"newest"``, ``"oldest"``, ``"top_rated"``,
            ``"most_installed"``.
        page:
            1-based page number.
        page_size:
            Results per page (max 100).

        Returns
        -------
        dict
            ``{items: list, total: int, page: int, page_size: int}``
        """
        await self._ensure_initialized()

        # Default public browse shows only approved listings
        effective_status = status if status is not None else "approved"

        page_size = min(page_size, 100)
        offset = (max(page, 1) - 1) * page_size

        # Build WHERE clause
        conditions: list[str] = ["status = ?"]
        params: list[Any] = [effective_status]

        if agent_type is not None:
            conditions.append("agent_type = ?")
            params.append(agent_type)

        if industry_type is not None:
            conditions.append("industry_type = ?")
            params.append(industry_type)

        where = " AND ".join(conditions)

        # Sort order
        order_map = {
            "newest": "created_at DESC",
            "oldest": "created_at ASC",
            "top_rated": "avg_rating DESC, rating_count DESC",
            "most_installed": "install_count DESC",
        }
        order = order_map.get(sort, "created_at DESC")

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row

            count_cursor = await db.execute(
                f"SELECT COUNT(*) FROM marketplace_templates WHERE {where}",
                params,
            )
            total_row = await count_cursor.fetchone()
            total = total_row[0] if total_row else 0

            rows_cursor = await db.execute(
                f"""
                SELECT * FROM marketplace_templates
                WHERE {where}
                ORDER BY {order}
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            )
            rows = await rows_cursor.fetchall()
            items = [self._row_to_dict(r) for r in rows]

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_listing(self, listing_id: str) -> Optional[dict[str, Any]]:
        """Return a single listing with embedded ratings summary.

        Returns None if no listing with the given ID exists.
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                return None

            # Attach recent ratings (up to 5)
            cursor = await db.execute(
                """
                SELECT id, user_id, stars, review_text, helpful_count,
                       created_at
                FROM template_ratings
                WHERE marketplace_template_id = ?
                ORDER BY helpful_count DESC, created_at DESC
                LIMIT 5
                """,
                (listing_id,),
            )
            rows = await cursor.fetchall()
            listing["recent_ratings"] = [self._row_to_dict(r) for r in rows]

        return listing

    async def update_listing(
        self,
        listing_id: str,
        author_user_id: str,
        **updates: Any,
    ) -> dict[str, Any]:
        """Update mutable fields on a draft or rejected listing.

        Only the author can update, and only when status is draft or rejected.

        Parameters
        ----------
        listing_id:
            ID of the listing to update.
        author_user_id:
            Must match the listing's author_user_id.
        **updates:
            Accepted keys: display_name, tagline, description_md, tags,
            preview_json, price_cents, industry_type, agent_type.

        Raises
        ------
        ValueError
            If listing not found, ownership mismatch, or invalid status.
        """
        await self._ensure_initialized()

        _allowed = {
            "display_name", "tagline", "description_md", "tags",
            "preview_json", "price_cents", "industry_type", "agent_type",
        }
        bad_keys = set(updates) - _allowed
        if bad_keys:
            raise ValueError(f"Unknown update fields: {bad_keys}")

        if not updates:
            raise ValueError("No updatable fields provided.")

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                raise ValueError(f"Listing not found: {listing_id}")
            if listing["author_user_id"] != author_user_id:
                raise PermissionError("Only the author can update this listing.")
            if listing["status"] not in _EDITABLE_STATUSES:
                raise ValueError(
                    f"Cannot edit a listing with status '{listing['status']}'. "
                    "Only draft or rejected listings can be edited."
                )

            # Serialize complex fields
            if "tags" in updates and isinstance(updates["tags"], list):
                updates["tags"] = json.dumps(updates["tags"])
            if "preview_json" in updates and isinstance(updates["preview_json"], dict):
                updates["preview_json"] = json.dumps(updates["preview_json"])

            set_clauses = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values())
            now = _now()
            await db.execute(
                f"UPDATE marketplace_templates SET {set_clauses}, updated_at = ? WHERE id = ?",
                [*values, now, listing_id],
            )
            await db.commit()

            updated = await self._get_listing_raw(db, listing_id)

        return updated  # type: ignore[return-value]

    async def submit_for_review(
        self, listing_id: str, author_user_id: str
    ) -> dict[str, Any]:
        """Transition a listing from draft/rejected to submitted.

        Parameters
        ----------
        listing_id:
            ID of the listing.
        author_user_id:
            Must match the listing's author_user_id.

        Raises
        ------
        ValueError
            If listing not found, ownership mismatch, or invalid current status.
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                raise ValueError(f"Listing not found: {listing_id}")
            if listing["author_user_id"] != author_user_id:
                raise PermissionError("Only the author can submit this listing.")
            if listing["status"] not in _SUBMIT_FROM:
                raise ValueError(
                    f"Cannot submit a listing with status '{listing['status']}'."
                )

            now = _now()
            await db.execute(
                """
                UPDATE marketplace_templates
                SET status = 'submitted', submitted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, listing_id),
            )
            await db.commit()

            updated = await self._get_listing_raw(db, listing_id)

        logger.info("marketplace: listing submitted id=%s author=%s", listing_id, author_user_id)
        return updated  # type: ignore[return-value]

    async def approve(self, listing_id: str, reviewer_id: str) -> dict[str, Any]:
        """Transition a listing to approved status.

        Parameters
        ----------
        listing_id:
            ID of the listing.
        reviewer_id:
            ID of the admin/reviewer performing the action.

        Raises
        ------
        ValueError
            If listing not found or cannot be approved from its current status.
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                raise ValueError(f"Listing not found: {listing_id}")
            if listing["status"] not in _APPROVE_FROM:
                raise ValueError(
                    f"Cannot approve a listing with status '{listing['status']}'."
                )

            now = _now()
            await db.execute(
                """
                UPDATE marketplace_templates
                SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
                    published_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (reviewer_id, now, now, now, listing_id),
            )
            await db.commit()

            updated = await self._get_listing_raw(db, listing_id)

        logger.info("marketplace: listing approved id=%s reviewer=%s", listing_id, reviewer_id)
        return updated  # type: ignore[return-value]

    async def reject(
        self, listing_id: str, reviewer_id: str, reason: str
    ) -> dict[str, Any]:
        """Transition a listing to rejected status with a reason.

        Parameters
        ----------
        listing_id:
            ID of the listing.
        reviewer_id:
            ID of the admin/reviewer performing the action.
        reason:
            Human-readable explanation shown to the author.

        Raises
        ------
        ValueError
            If listing not found or cannot be rejected from its current status.
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                raise ValueError(f"Listing not found: {listing_id}")
            if listing["status"] not in _REJECT_FROM:
                raise ValueError(
                    f"Cannot reject a listing with status '{listing['status']}'."
                )

            now = _now()
            await db.execute(
                """
                UPDATE marketplace_templates
                SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,
                    rejection_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (reviewer_id, now, reason, now, listing_id),
            )
            await db.commit()

            updated = await self._get_listing_raw(db, listing_id)

        logger.info(
            "marketplace: listing rejected id=%s reviewer=%s reason=%r",
            listing_id, reviewer_id, reason,
        )
        return updated  # type: ignore[return-value]

    async def install_template(
        self,
        listing_id: str,
        installer_user_id: str,
        agent_id: str,
        payment_intent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a template installation and update counters.

        Calculates revenue split: platform keeps (100 - revenue_share_pct)%,
        creator receives revenue_share_pct% of the amount paid.

        Parameters
        ----------
        listing_id:
            ID of the marketplace listing being installed.
        installer_user_id:
            The installing user's ID.
        agent_id:
            The target agent that will use this template.
        payment_intent_id:
            Optional Stripe PaymentIntent ID (for paid templates).

        Returns
        -------
        dict
            The newly created install record.

        Raises
        ------
        ValueError
            If the listing is not found or not in approved status.
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                raise ValueError(f"Listing not found: {listing_id}")
            if listing["status"] != "approved":
                raise ValueError(
                    f"Cannot install a listing with status '{listing['status']}'."
                )

            price = listing["price_cents"]
            revenue_share = listing["revenue_share_pct"]
            creator_payout = int(price * revenue_share / 100)
            platform_fee = price - creator_payout
            payout_status = "pending" if price > 0 else "not_applicable"

            now = _now()
            install_id = _uid()
            await db.execute(
                """
                INSERT INTO template_installs (
                    id, marketplace_template_id, base_template_id,
                    installer_user_id, agent_id, payment_intent_id,
                    amount_paid_cents, platform_fee_cents, creator_payout_cents,
                    payout_status, installed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    install_id, listing_id, listing["base_template_id"],
                    installer_user_id, agent_id, payment_intent_id,
                    price, platform_fee, creator_payout,
                    payout_status, now,
                ),
            )

            # Increment install_count on the listing
            await db.execute(
                "UPDATE marketplace_templates SET install_count = install_count + 1, updated_at = ? WHERE id = ?",
                (now, listing_id),
            )

            # Update creator earnings
            if creator_payout > 0:
                await db.execute(
                    """
                    UPDATE creator_profiles
                    SET total_earned_cents = total_earned_cents + ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (creator_payout, now, listing["author_user_id"]),
                )

            await db.commit()

            # Fetch the install record
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM template_installs WHERE id = ?",
                (install_id,),
            )
            row = await cursor.fetchone()
            result = self._row_to_dict(row) if row else {}

        logger.info(
            "marketplace: template installed listing=%s installer=%s agent=%s",
            listing_id, installer_user_id, agent_id,
        )
        return result

    async def rate_template(
        self,
        listing_id: str,
        user_id: str,
        stars: int,
        review_text: Optional[str] = None,
    ) -> dict[str, Any]:
        """Add or update a rating for a marketplace listing.

        Recalculates avg_rating on the listing after upsert.

        Parameters
        ----------
        listing_id:
            ID of the marketplace listing being rated.
        user_id:
            The rating user's ID.
        stars:
            Integer 1-5.
        review_text:
            Optional written review.

        Returns
        -------
        dict
            The upserted rating record.

        Raises
        ------
        ValueError
            If stars is out of range or listing not found.
        """
        if not 1 <= stars <= 5:
            raise ValueError("stars must be between 1 and 5")

        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            listing = await self._get_listing_raw(db, listing_id)
            if listing is None:
                raise ValueError(f"Listing not found: {listing_id}")

            now = _now()
            rating_id = _uid()

            # Upsert the rating
            await db.execute(
                """
                INSERT INTO template_ratings (
                    id, marketplace_template_id, user_id, stars,
                    review_text, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(marketplace_template_id, user_id) DO UPDATE SET
                    stars = excluded.stars,
                    review_text = excluded.review_text,
                    updated_at = excluded.updated_at
                """,
                (rating_id, listing_id, user_id, stars, review_text, now, now),
            )

            # Recalculate avg_rating from all ratings for this listing
            agg_cursor = await db.execute(
                "SELECT AVG(stars) as avg_s, COUNT(*) as cnt FROM template_ratings WHERE marketplace_template_id = ?",
                (listing_id,),
            )
            agg_row = await agg_cursor.fetchone()
            new_avg = round(agg_row[0] or 0.0, 2)
            new_count = agg_row[1] or 0

            await db.execute(
                "UPDATE marketplace_templates SET avg_rating = ?, rating_count = ?, updated_at = ? WHERE id = ?",
                (new_avg, new_count, now, listing_id),
            )
            await db.commit()

            # Return the upserted rating
            cursor = await db.execute(
                "SELECT * FROM template_ratings WHERE marketplace_template_id = ? AND user_id = ?",
                (listing_id, user_id),
            )
            row = await cursor.fetchone()
            result = self._row_to_dict(row) if row else {}

        logger.info(
            "marketplace: rating upserted listing=%s user=%s stars=%d",
            listing_id, user_id, stars,
        )
        return result

    async def fork_template(
        self,
        listing_id: str,
        forker_user_id: str,
        display_name: str,
    ) -> dict[str, Any]:
        """Clone an approved listing into a new draft owned by the forker.

        Copies the source listing's configuration (base_template_id,
        tagline, description_md, preview_json, tags, agent_type,
        industry_type, price_cents) and increments the source's fork_count.

        Parameters
        ----------
        listing_id:
            ID of the source listing to fork.
        forker_user_id:
            ID of the user creating the fork.
        display_name:
            New display name for the forked listing.

        Returns
        -------
        dict
            The newly created draft listing.

        Raises
        ------
        ValueError
            If the source listing is not found or not approved.
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            source = await self._get_listing_raw(db, listing_id)
            if source is None:
                raise ValueError(f"Listing not found: {listing_id}")
            if source["status"] != "approved":
                raise ValueError(
                    f"Cannot fork a listing with status '{source['status']}'."
                )

            now = _now()
            fork_id = _uid()
            await db.execute(
                """
                INSERT INTO marketplace_templates (
                    id, base_template_id, author_user_id, forked_from_id,
                    display_name, tagline, description_md, preview_json, tags,
                    agent_type, industry_type, status, price_cents,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fork_id,
                    source["base_template_id"],
                    forker_user_id,
                    listing_id,
                    display_name,
                    source["tagline"],
                    source["description_md"],
                    source["preview_json"],
                    source["tags"],
                    source["agent_type"],
                    source["industry_type"],
                    "draft",
                    source["price_cents"],
                    now, now,
                ),
            )

            # Increment fork_count on source
            await db.execute(
                "UPDATE marketplace_templates SET fork_count = fork_count + 1, updated_at = ? WHERE id = ?",
                (now, listing_id),
            )

            # Upsert creator profile for forker
            await db.execute(
                """
                INSERT INTO creator_profiles (user_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    template_count = template_count + 1,
                    updated_at = excluded.updated_at
                """,
                (forker_user_id, now, now),
            )
            await db.commit()

            fork = await self._get_listing_raw(db, fork_id)

        logger.info(
            "marketplace: listing forked source=%s fork=%s forker=%s",
            listing_id, fork_id, forker_user_id,
        )
        return fork  # type: ignore[return-value]

    async def get_creator_earnings(self, user_id: str) -> dict[str, Any]:
        """Return aggregated earnings and template stats for a creator.

        Parameters
        ----------
        user_id:
            The creator's user ID.

        Returns
        -------
        dict
            ``{user_id, total_earned_cents, template_count, install_count,
               pending_payout_cents, connect_verified, display_name}``
        """
        await self._ensure_initialized()

        async with self._connect() as db:
            db.row_factory = aiosqlite.Row

            # Fetch creator profile
            cursor = await db.execute(
                "SELECT * FROM creator_profiles WHERE user_id = ?",
                (user_id,),
            )
            profile_row = await cursor.fetchone()
            profile = self._row_to_dict(profile_row) if profile_row else {}

            # Aggregate installs earned by this creator
            cursor = await db.execute(
                """
                SELECT COALESCE(SUM(ti.creator_payout_cents), 0) as total,
                       COALESCE(SUM(CASE WHEN ti.payout_status = 'pending' THEN ti.creator_payout_cents ELSE 0 END), 0) as pending,
                       COUNT(*) as total_installs
                FROM template_installs ti
                JOIN marketplace_templates mt ON ti.marketplace_template_id = mt.id
                WHERE mt.author_user_id = ?
                """,
                (user_id,),
            )
            agg_row = await cursor.fetchone()
            agg = self._row_to_dict(agg_row) if agg_row else {}

        return {
            "user_id": user_id,
            "display_name": profile.get("display_name", ""),
            "total_earned_cents": agg.get("total", 0),
            "pending_payout_cents": agg.get("pending", 0),
            "total_installs": agg.get("total_installs", 0),
            "template_count": profile.get("template_count", 0),
            "connect_verified": bool(profile.get("connect_verified", 0)),
            "stripe_connect_id": profile.get("stripe_connect_id"),
        }
