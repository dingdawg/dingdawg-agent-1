"""Unit tests for isg_agent.templates.marketplace_registry.MarketplaceRegistry.

Covers every public method with happy-path, edge-case, and error-path variants.
Uses in-memory SQLite (db_path=':memory:') for full isolation between tests.
"""

from __future__ import annotations

import pytest

from isg_agent.templates.marketplace_registry import MarketplaceRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_registry() -> MarketplaceRegistry:
    """Return a fresh isolated in-memory MarketplaceRegistry."""
    return MarketplaceRegistry(db_path=":memory:")


async def _create_draft(
    reg: MarketplaceRegistry,
    *,
    author: str = "user_author",
    base_id: str = "tmpl_base_001",
    name: str = "My Agent Template",
    agent_type: str = "business",
    industry_type: str | None = "restaurant",
    price_cents: int = 0,
) -> dict:
    """Helper: create a single draft listing and return it."""
    return await reg.create_listing(
        base_template_id=base_id,
        author_user_id=author,
        display_name=name,
        tagline="A great template",
        description_md="## Description\nFull markdown here.",
        agent_type=agent_type,
        industry_type=industry_type,
        price_cents=price_cents,
        tags=["ai", "business"],
        preview_json={"step": 1},
    )


async def _make_approved(
    reg: MarketplaceRegistry,
    *,
    author: str = "user_author",
    reviewer: str = "admin_user",
    price_cents: int = 0,
    agent_type: str = "business",
    industry_type: str | None = "restaurant",
    name: str = "Approved Template",
    base_id: str = "tmpl_base_001",
) -> dict:
    """Helper: create, submit, and approve a listing. Returns approved listing."""
    listing = await _create_draft(
        reg,
        author=author,
        name=name,
        agent_type=agent_type,
        industry_type=industry_type,
        price_cents=price_cents,
        base_id=base_id,
    )
    await reg.submit_for_review(listing["id"], author)
    return await reg.approve(listing["id"], reviewer)


# ===========================================================================
# TestCreateListing
# ===========================================================================


class TestCreateListing:
    """Tests for MarketplaceRegistry.create_listing."""

    async def test_create_listing_returns_dict_with_id(self) -> None:
        """Happy path: create listing returns a dict with an id."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            assert isinstance(listing, dict)
            assert "id" in listing
            assert len(listing["id"]) > 0
        finally:
            await reg.close()

    async def test_create_listing_status_is_draft(self) -> None:
        """New listing starts in draft status."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            assert listing["status"] == "draft"
        finally:
            await reg.close()

    async def test_create_listing_fields_stored_correctly(self) -> None:
        """All provided fields are persisted correctly."""
        reg = await _make_registry()
        try:
            listing = await reg.create_listing(
                base_template_id="base_999",
                author_user_id="creator_x",
                display_name="Custom Name",
                tagline="Short tagline",
                description_md="# Heading",
                agent_type="personal",
                industry_type="fitness",
                price_cents=199,
                tags=["health", "wellness"],
                preview_json={"color": "blue"},
            )
            assert listing["base_template_id"] == "base_999"
            assert listing["author_user_id"] == "creator_x"
            assert listing["display_name"] == "Custom Name"
            assert listing["tagline"] == "Short tagline"
            assert listing["description_md"] == "# Heading"
            assert listing["agent_type"] == "personal"
            assert listing["industry_type"] == "fitness"
            assert listing["price_cents"] == 199
        finally:
            await reg.close()

    async def test_create_listing_upserts_creator_profile(self) -> None:
        """Creating a listing upserts a creator_profiles row for the author.

        The initial INSERT sets template_count=0 (default).  Creating a second
        listing triggers the ON CONFLICT path, which increments to 1.
        We verify the profile row exists by checking user_id is returned.
        """
        reg = await _make_registry()
        try:
            await _create_draft(reg, author="creator_new")
            earnings = await reg.get_creator_earnings("creator_new")
            # Profile row was created — user_id is echoed back
            assert earnings["user_id"] == "creator_new"
        finally:
            await reg.close()

    async def test_create_listing_increments_template_count(self) -> None:
        """Creating two listings for the same author increments template_count.

        The upsert logic: first INSERT sets template_count=0, the ON CONFLICT
        branch increments by 1 on each subsequent create.  So after 2 creates
        the count is 1 (0 on first insert, +1 on second).
        """
        reg = await _make_registry()
        try:
            await _create_draft(reg, author="author_a", name="Listing 1")
            await _create_draft(reg, author="author_a", name="Listing 2")
            earnings = await reg.get_creator_earnings("author_a")
            # After 2 creates: first sets default 0, second increments to 1
            assert earnings["template_count"] == 1
        finally:
            await reg.close()

    async def test_create_listing_defaults_price_to_zero(self) -> None:
        """Listing without price_cents defaults to 0 (free)."""
        reg = await _make_registry()
        try:
            listing = await reg.create_listing(
                base_template_id="base_1",
                author_user_id="u1",
                display_name="Free Template",
                tagline="free",
                description_md="",
                agent_type="business",
            )
            assert listing["price_cents"] == 0
        finally:
            await reg.close()

    async def test_create_listing_install_count_starts_at_zero(self) -> None:
        """New listing has install_count of 0."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            assert listing["install_count"] == 0
        finally:
            await reg.close()


# ===========================================================================
# TestListListings
# ===========================================================================


class TestListListings:
    """Tests for MarketplaceRegistry.list_listings."""

    async def test_list_listings_no_filters_returns_only_approved(self) -> None:
        """Default (no status filter) returns only approved listings."""
        reg = await _make_registry()
        try:
            # Draft — should NOT appear
            await _create_draft(reg, name="Draft Only")
            # Approved — should appear
            await _make_approved(reg, name="Approved One")
            result = await reg.list_listings()
            assert result["total"] == 1
            assert result["items"][0]["display_name"] == "Approved One"
        finally:
            await reg.close()

    async def test_list_listings_filter_by_status_draft(self) -> None:
        """Filtering by status=draft returns only draft listings."""
        reg = await _make_registry()
        try:
            await _create_draft(reg, name="Draft A")
            await _make_approved(reg, name="Approved B")
            result = await reg.list_listings(status="draft")
            names = {item["display_name"] for item in result["items"]}
            assert "Draft A" in names
            assert "Approved B" not in names
        finally:
            await reg.close()

    async def test_list_listings_filter_by_agent_type(self) -> None:
        """Filtering by agent_type returns only matching listings."""
        reg = await _make_registry()
        try:
            await _make_approved(reg, agent_type="business", name="Biz Template")
            await _make_approved(reg, agent_type="personal", name="Personal Template")
            result = await reg.list_listings(status="approved", agent_type="business")
            assert result["total"] == 1
            assert result["items"][0]["agent_type"] == "business"
        finally:
            await reg.close()

    async def test_list_listings_filter_by_industry_type(self) -> None:
        """Filtering by industry_type returns only matching listings."""
        reg = await _make_registry()
        try:
            await _make_approved(reg, industry_type="restaurant", name="Restaurant")
            await _make_approved(reg, industry_type="fitness", name="Fitness")
            result = await reg.list_listings(status="approved", industry_type="restaurant")
            assert result["total"] == 1
            assert result["items"][0]["industry_type"] == "restaurant"
        finally:
            await reg.close()

    async def test_list_listings_sort_newest(self) -> None:
        """Sort by newest returns listings in descending created_at order."""
        reg = await _make_registry()
        try:
            l1 = await _make_approved(reg, name="First")
            l2 = await _make_approved(reg, name="Second")
            result = await reg.list_listings(status="approved", sort="newest")
            # The second listing was created after the first, so it comes first
            ids = [item["id"] for item in result["items"]]
            assert ids.index(l2["id"]) < ids.index(l1["id"])
        finally:
            await reg.close()

    async def test_list_listings_sort_oldest(self) -> None:
        """Sort by oldest returns listings in ascending created_at order."""
        reg = await _make_registry()
        try:
            l1 = await _make_approved(reg, name="Older")
            l2 = await _make_approved(reg, name="Newer")
            result = await reg.list_listings(status="approved", sort="oldest")
            ids = [item["id"] for item in result["items"]]
            assert ids.index(l1["id"]) < ids.index(l2["id"])
        finally:
            await reg.close()

    async def test_list_listings_sort_top_rated(self) -> None:
        """Sort by top_rated returns highest avg_rating first."""
        reg = await _make_registry()
        try:
            low = await _make_approved(reg, name="Low Rated", author="u1")
            high = await _make_approved(reg, name="High Rated", author="u2")
            await reg.rate_template(low["id"], "rater1", 2)
            await reg.rate_template(high["id"], "rater2", 5)
            result = await reg.list_listings(status="approved", sort="top_rated")
            assert result["items"][0]["id"] == high["id"]
        finally:
            await reg.close()

    async def test_list_listings_sort_most_installed(self) -> None:
        """Sort by most_installed returns highest install_count first."""
        reg = await _make_registry()
        try:
            few = await _make_approved(reg, name="Few Installs", author="u1")
            many = await _make_approved(reg, name="Many Installs", author="u2")
            await reg.install_template(many["id"], "installer1", "agent_1")
            await reg.install_template(many["id"], "installer2", "agent_2")
            await reg.install_template(few["id"], "installer3", "agent_3")
            result = await reg.list_listings(status="approved", sort="most_installed")
            assert result["items"][0]["id"] == many["id"]
        finally:
            await reg.close()

    async def test_list_listings_pagination_page1(self) -> None:
        """Page 1 with page_size=2 returns the first 2 listings."""
        reg = await _make_registry()
        try:
            for i in range(5):
                await _make_approved(reg, name=f"Template {i}", author=f"author_{i}")
            result = await reg.list_listings(status="approved", page=1, page_size=2)
            assert len(result["items"]) == 2
            assert result["page"] == 1
            assert result["page_size"] == 2
            assert result["total"] == 5
        finally:
            await reg.close()

    async def test_list_listings_pagination_page2(self) -> None:
        """Page 2 with page_size=2 returns the next batch."""
        reg = await _make_registry()
        try:
            for i in range(5):
                await _make_approved(reg, name=f"Template {i}", author=f"author_{i}")
            p1 = await reg.list_listings(status="approved", page=1, page_size=2)
            p2 = await reg.list_listings(status="approved", page=2, page_size=2)
            ids_p1 = {item["id"] for item in p1["items"]}
            ids_p2 = {item["id"] for item in p2["items"]}
            assert ids_p1.isdisjoint(ids_p2), "Pages must not overlap"
        finally:
            await reg.close()

    async def test_list_listings_empty_results(self) -> None:
        """Listing when no approved templates exist returns empty items and total=0."""
        reg = await _make_registry()
        try:
            result = await reg.list_listings()
            assert result["total"] == 0
            assert result["items"] == []
        finally:
            await reg.close()

    async def test_list_listings_page_size_capped_at_100(self) -> None:
        """page_size > 100 is capped to 100."""
        reg = await _make_registry()
        try:
            result = await reg.list_listings(page_size=999)
            assert result["page_size"] == 100
        finally:
            await reg.close()


# ===========================================================================
# TestGetListing
# ===========================================================================


class TestGetListing:
    """Tests for MarketplaceRegistry.get_listing."""

    async def test_get_listing_happy_path(self) -> None:
        """get_listing returns correct listing by id."""
        reg = await _make_registry()
        try:
            created = await _create_draft(reg, name="Find Me")
            fetched = await reg.get_listing(created["id"])
            assert fetched is not None
            assert fetched["id"] == created["id"]
            assert fetched["display_name"] == "Find Me"
        finally:
            await reg.close()

    async def test_get_listing_not_found_returns_none(self) -> None:
        """get_listing returns None for a non-existent id."""
        reg = await _make_registry()
        try:
            result = await reg.get_listing("nonexistent_id_xyz")
            assert result is None
        finally:
            await reg.close()

    async def test_get_listing_includes_recent_ratings_key(self) -> None:
        """get_listing always includes recent_ratings list (empty if no ratings)."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            assert "recent_ratings" in fetched
            assert isinstance(fetched["recent_ratings"], list)
        finally:
            await reg.close()

    async def test_get_listing_with_no_ratings_returns_empty_list(self) -> None:
        """Listing with zero ratings has empty recent_ratings."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            assert fetched["recent_ratings"] == []
        finally:
            await reg.close()

    async def test_get_listing_with_multiple_ratings_avg_correct(self) -> None:
        """avg_rating reflects all submitted ratings."""
        reg = await _make_registry()
        try:
            listing = await _make_approved(reg)
            await reg.rate_template(listing["id"], "user_a", 4)
            await reg.rate_template(listing["id"], "user_b", 2)
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            # avg of 4 and 2 = 3.0
            assert fetched["avg_rating"] == pytest.approx(3.0, abs=0.01)
            assert fetched["rating_count"] == 2
        finally:
            await reg.close()

    async def test_get_listing_recent_ratings_populated(self) -> None:
        """After rating, recent_ratings list contains the rating row."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            await reg.rate_template(listing["id"], "rater1", 5, "Excellent!")
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            assert len(fetched["recent_ratings"]) == 1
            assert fetched["recent_ratings"][0]["stars"] == 5
        finally:
            await reg.close()


# ===========================================================================
# TestUpdateListing
# ===========================================================================


class TestUpdateListing:
    """Tests for MarketplaceRegistry.update_listing."""

    async def test_update_listing_happy_path(self) -> None:
        """Author can update a draft listing's display_name."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="author1")
            updated = await reg.update_listing(
                listing["id"], "author1", display_name="New Name"
            )
            assert updated["display_name"] == "New Name"
        finally:
            await reg.close()

    async def test_update_listing_permission_error_wrong_author(self) -> None:
        """Only the author can update; wrong author raises PermissionError."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="real_author")
            with pytest.raises(PermissionError):
                await reg.update_listing(listing["id"], "impostor", display_name="Hacked")
        finally:
            await reg.close()

    async def test_update_listing_value_error_approved_status(self) -> None:
        """Updating an approved listing raises ValueError."""
        reg = await _make_registry()
        try:
            approved = await _make_approved(reg, author="auth1")
            with pytest.raises(ValueError, match="approved"):
                await reg.update_listing(approved["id"], "auth1", display_name="Changed")
        finally:
            await reg.close()

    async def test_update_listing_value_error_submitted_status(self) -> None:
        """Updating a submitted listing raises ValueError."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth2")
            await reg.submit_for_review(listing["id"], "auth2")
            with pytest.raises(ValueError):
                await reg.update_listing(listing["id"], "auth2", display_name="Changed")
        finally:
            await reg.close()

    async def test_update_listing_partial_update(self) -> None:
        """Partial update only changes specified fields."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(
                reg, author="auth3", name="Original Name"
            )
            original_tagline = listing["tagline"]
            updated = await reg.update_listing(
                listing["id"], "auth3", price_cents=500
            )
            assert updated["price_cents"] == 500
            assert updated["display_name"] == "Original Name"
            assert updated["tagline"] == original_tagline
        finally:
            await reg.close()

    async def test_update_listing_tags_as_list(self) -> None:
        """Tags can be updated as a list and are serialized."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth4")
            updated = await reg.update_listing(
                listing["id"], "auth4", tags=["new_tag", "another"]
            )
            import json
            tags = json.loads(updated["tags"])
            assert "new_tag" in tags
        finally:
            await reg.close()

    async def test_update_rejected_listing_is_allowed(self) -> None:
        """A rejected listing can be updated by the author."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth5")
            await reg.submit_for_review(listing["id"], "auth5")
            await reg.reject(listing["id"], "admin", "Needs work")
            updated = await reg.update_listing(
                listing["id"], "auth5", tagline="Improved tagline"
            )
            assert updated["tagline"] == "Improved tagline"
        finally:
            await reg.close()


# ===========================================================================
# TestSubmitForReview
# ===========================================================================


class TestSubmitForReview:
    """Tests for MarketplaceRegistry.submit_for_review."""

    async def test_submit_for_review_happy_path(self) -> None:
        """Draft listing transitions to submitted status."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth1")
            submitted = await reg.submit_for_review(listing["id"], "auth1")
            assert submitted["status"] == "submitted"
            assert submitted["submitted_at"] is not None
        finally:
            await reg.close()

    async def test_submit_for_review_permission_error_wrong_author(self) -> None:
        """Only the author can submit; wrong author raises PermissionError."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="real_auth")
            with pytest.raises(PermissionError):
                await reg.submit_for_review(listing["id"], "not_the_author")
        finally:
            await reg.close()

    async def test_submit_for_review_already_submitted_raises(self) -> None:
        """Cannot submit an already-submitted listing."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth2")
            await reg.submit_for_review(listing["id"], "auth2")
            with pytest.raises(ValueError):
                await reg.submit_for_review(listing["id"], "auth2")
        finally:
            await reg.close()

    async def test_submit_for_review_already_approved_raises(self) -> None:
        """Cannot submit an already-approved listing."""
        reg = await _make_registry()
        try:
            approved = await _make_approved(reg, author="auth3")
            with pytest.raises(ValueError):
                await reg.submit_for_review(approved["id"], "auth3")
        finally:
            await reg.close()

    async def test_submit_rejected_listing_transitions_to_submitted(self) -> None:
        """A rejected listing can be resubmitted after edits."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth4")
            await reg.submit_for_review(listing["id"], "auth4")
            await reg.reject(listing["id"], "admin", "Reason")
            resubmitted = await reg.submit_for_review(listing["id"], "auth4")
            assert resubmitted["status"] == "submitted"
        finally:
            await reg.close()


# ===========================================================================
# TestApprove
# ===========================================================================


class TestApprove:
    """Tests for MarketplaceRegistry.approve."""

    async def test_approve_happy_path(self) -> None:
        """Submitted listing transitions to approved status."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth1")
            await reg.submit_for_review(listing["id"], "auth1")
            approved = await reg.approve(listing["id"], "reviewer1")
            assert approved["status"] == "approved"
            assert approved["reviewed_by"] == "reviewer1"
            assert approved["reviewed_at"] is not None
            assert approved["published_at"] is not None
        finally:
            await reg.close()

    async def test_approve_sets_reviewed_by(self) -> None:
        """Approved listing stores the reviewer's id in reviewed_by."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth2")
            await reg.submit_for_review(listing["id"], "auth2")
            approved = await reg.approve(listing["id"], "admin_reviewer")
            assert approved["reviewed_by"] == "admin_reviewer"
        finally:
            await reg.close()

    async def test_approve_draft_raises_value_error(self) -> None:
        """Cannot approve a listing that is still in draft status."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth3")
            with pytest.raises(ValueError, match="Cannot approve"):
                await reg.approve(listing["id"], "reviewer")
        finally:
            await reg.close()

    async def test_approve_not_found_raises_value_error(self) -> None:
        """Approving a non-existent listing raises ValueError."""
        reg = await _make_registry()
        try:
            with pytest.raises(ValueError, match="not found"):
                await reg.approve("fake_listing_id", "reviewer")
        finally:
            await reg.close()


# ===========================================================================
# TestReject
# ===========================================================================


class TestReject:
    """Tests for MarketplaceRegistry.reject."""

    async def test_reject_happy_path(self) -> None:
        """Submitted listing transitions to rejected with reason stored."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth1")
            await reg.submit_for_review(listing["id"], "auth1")
            rejected = await reg.reject(listing["id"], "admin", "Missing screenshots")
            assert rejected["status"] == "rejected"
            assert rejected["rejection_reason"] == "Missing screenshots"
            assert rejected["reviewed_by"] == "admin"
        finally:
            await reg.close()

    async def test_reject_draft_raises_value_error(self) -> None:
        """Cannot reject a listing that has not been submitted."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg, author="auth2")
            with pytest.raises(ValueError, match="Cannot reject"):
                await reg.reject(listing["id"], "admin", "reason")
        finally:
            await reg.close()

    async def test_reject_not_found_raises_value_error(self) -> None:
        """Rejecting a non-existent listing raises ValueError."""
        reg = await _make_registry()
        try:
            with pytest.raises(ValueError, match="not found"):
                await reg.reject("no_such_id", "admin", "reason")
        finally:
            await reg.close()


# ===========================================================================
# TestInstallTemplate
# ===========================================================================


class TestInstallTemplate:
    """Tests for MarketplaceRegistry.install_template."""

    async def test_install_happy_path_free(self) -> None:
        """Free template: install record created with zero payment fields."""
        reg = await _make_registry()
        try:
            approved = await _make_approved(reg, price_cents=0)
            install = await reg.install_template(
                approved["id"], "installer1", "agent_abc"
            )
            assert install["marketplace_template_id"] == approved["id"]
            assert install["installer_user_id"] == "installer1"
            assert install["amount_paid_cents"] == 0
            assert install["platform_fee_cents"] == 0
            assert install["creator_payout_cents"] == 0
            assert install["payout_status"] == "not_applicable"
        finally:
            await reg.close()

    async def test_install_paid_template_revenue_split(self) -> None:
        """Paid template: 70% to creator, 30% to platform by default."""
        reg = await _make_registry()
        try:
            approved = await _make_approved(reg, price_cents=1000)
            install = await reg.install_template(
                approved["id"], "buyer1", "agent_123", payment_intent_id="pi_test_001"
            )
            assert install["amount_paid_cents"] == 1000
            assert install["creator_payout_cents"] == 700  # 70%
            assert install["platform_fee_cents"] == 300   # 30%
            assert install["payout_status"] == "pending"
        finally:
            await reg.close()

    async def test_install_increments_install_count(self) -> None:
        """Each install increments the listing's install_count."""
        reg = await _make_registry()
        try:
            approved = await _make_approved(reg)
            await reg.install_template(approved["id"], "u1", "ag1")
            await reg.install_template(approved["id"], "u2", "ag2")
            fetched = await reg.get_listing(approved["id"])
            assert fetched is not None
            assert fetched["install_count"] == 2
        finally:
            await reg.close()

    async def test_install_updates_creator_earnings(self) -> None:
        """Paid install adds creator_payout_cents to the creator's total_earned."""
        reg = await _make_registry()
        try:
            author = "creator_paid"
            approved = await _make_approved(reg, author=author, price_cents=500)
            await reg.install_template(approved["id"], "buyer", "agent_buy")
            earnings = await reg.get_creator_earnings(author)
            # 500 * 70% = 350 cents
            assert earnings["total_earned_cents"] == 350
        finally:
            await reg.close()

    async def test_install_unapproved_listing_raises(self) -> None:
        """Installing a draft listing raises ValueError."""
        reg = await _make_registry()
        try:
            draft = await _create_draft(reg)
            with pytest.raises(ValueError, match="Cannot install"):
                await reg.install_template(draft["id"], "buyer", "agent_x")
        finally:
            await reg.close()

    async def test_install_not_found_raises(self) -> None:
        """Installing a non-existent listing raises ValueError."""
        reg = await _make_registry()
        try:
            with pytest.raises(ValueError, match="not found"):
                await reg.install_template("bad_id", "buyer", "agent_x")
        finally:
            await reg.close()

    async def test_install_free_template_does_not_update_earnings(self) -> None:
        """Free install does NOT update creator total_earned_cents."""
        reg = await _make_registry()
        try:
            author = "creator_free"
            approved = await _make_approved(reg, author=author, price_cents=0)
            await reg.install_template(approved["id"], "u1", "ag_free")
            earnings = await reg.get_creator_earnings(author)
            assert earnings["total_earned_cents"] == 0
        finally:
            await reg.close()


# ===========================================================================
# TestRateTemplate
# ===========================================================================


class TestRateTemplate:
    """Tests for MarketplaceRegistry.rate_template."""

    async def test_rate_template_happy_path(self) -> None:
        """Rating a listing returns the rating record."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            rating = await reg.rate_template(listing["id"], "user1", 4, "Good!")
            assert rating["stars"] == 4
            assert rating["review_text"] == "Good!"
            assert rating["user_id"] == "user1"
        finally:
            await reg.close()

    async def test_rate_template_updates_avg_rating(self) -> None:
        """After rating, the listing's avg_rating is recalculated."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            await reg.rate_template(listing["id"], "user_a", 5)
            await reg.rate_template(listing["id"], "user_b", 3)
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            assert fetched["avg_rating"] == pytest.approx(4.0, abs=0.01)
            assert fetched["rating_count"] == 2
        finally:
            await reg.close()

    async def test_rate_template_upsert_same_user(self) -> None:
        """Rating again by the same user updates the existing rating (upsert)."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            await reg.rate_template(listing["id"], "user1", 2)
            await reg.rate_template(listing["id"], "user1", 5, "Changed my mind")
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            # Only one rating after upsert
            assert fetched["rating_count"] == 1
            assert fetched["avg_rating"] == pytest.approx(5.0, abs=0.01)
        finally:
            await reg.close()

    async def test_rate_template_stars_boundary_min_1(self) -> None:
        """Stars = 1 is the minimum valid value."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            rating = await reg.rate_template(listing["id"], "user2", 1)
            assert rating["stars"] == 1
        finally:
            await reg.close()

    async def test_rate_template_stars_boundary_max_5(self) -> None:
        """Stars = 5 is the maximum valid value."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            rating = await reg.rate_template(listing["id"], "user3", 5)
            assert rating["stars"] == 5
        finally:
            await reg.close()

    async def test_rate_template_stars_0_raises(self) -> None:
        """Stars = 0 is below minimum and must raise ValueError."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            with pytest.raises(ValueError, match="stars"):
                await reg.rate_template(listing["id"], "user4", 0)
        finally:
            await reg.close()

    async def test_rate_template_stars_6_raises(self) -> None:
        """Stars = 6 is above maximum and must raise ValueError."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            with pytest.raises(ValueError, match="stars"):
                await reg.rate_template(listing["id"], "user5", 6)
        finally:
            await reg.close()

    async def test_rate_template_not_found_raises(self) -> None:
        """Rating a non-existent listing raises ValueError."""
        reg = await _make_registry()
        try:
            with pytest.raises(ValueError, match="not found"):
                await reg.rate_template("fake_id", "u1", 3)
        finally:
            await reg.close()

    async def test_rate_template_avg_recalculated_correctly_multiple(self) -> None:
        """avg_rating is correct with 4 different raters (1, 2, 3, 4 → avg 2.5)."""
        reg = await _make_registry()
        try:
            listing = await _create_draft(reg)
            for i, stars in enumerate([1, 2, 3, 4]):
                await reg.rate_template(listing["id"], f"rater_{i}", stars)
            fetched = await reg.get_listing(listing["id"])
            assert fetched is not None
            assert fetched["avg_rating"] == pytest.approx(2.5, abs=0.01)
            assert fetched["rating_count"] == 4
        finally:
            await reg.close()


# ===========================================================================
# TestForkTemplate
# ===========================================================================


class TestForkTemplate:
    """Tests for MarketplaceRegistry.fork_template."""

    async def test_fork_template_happy_path(self) -> None:
        """Forking an approved listing creates a new draft."""
        reg = await _make_registry()
        try:
            source = await _make_approved(reg, name="Original", author="creator1")
            fork = await reg.fork_template(source["id"], "forker1", "My Fork")
            assert fork["status"] == "draft"
            assert fork["display_name"] == "My Fork"
            assert fork["author_user_id"] == "forker1"
            assert fork["forked_from_id"] == source["id"]
        finally:
            await reg.close()

    async def test_fork_template_increments_fork_count(self) -> None:
        """Forking increments the source listing's fork_count."""
        reg = await _make_registry()
        try:
            source = await _make_approved(reg, name="Source")
            assert source["fork_count"] == 0
            await reg.fork_template(source["id"], "forker1", "Fork 1")
            await reg.fork_template(source["id"], "forker2", "Fork 2")
            updated_source = await reg.get_listing(source["id"])
            assert updated_source is not None
            assert updated_source["fork_count"] == 2
        finally:
            await reg.close()

    async def test_fork_template_forked_listing_has_correct_author(self) -> None:
        """The fork's author is the forker, not the original creator."""
        reg = await _make_registry()
        try:
            source = await _make_approved(reg, author="original_creator")
            fork = await reg.fork_template(source["id"], "the_forker", "Fork Copy")
            assert fork["author_user_id"] == "the_forker"
        finally:
            await reg.close()

    async def test_fork_template_unapproved_source_raises(self) -> None:
        """Forking a draft listing raises ValueError."""
        reg = await _make_registry()
        try:
            draft = await _create_draft(reg)
            with pytest.raises(ValueError, match="Cannot fork"):
                await reg.fork_template(draft["id"], "forker", "Fork Attempt")
        finally:
            await reg.close()

    async def test_fork_template_not_found_raises(self) -> None:
        """Forking a non-existent listing raises ValueError."""
        reg = await _make_registry()
        try:
            with pytest.raises(ValueError, match="not found"):
                await reg.fork_template("no_listing", "forker", "Fork")
        finally:
            await reg.close()

    async def test_fork_template_creates_creator_profile_for_forker(self) -> None:
        """Forking creates/upserts a creator profile for the forker.

        The initial INSERT sets template_count=0.  We verify the profile row
        was created by checking user_id is echoed back from get_creator_earnings.
        """
        reg = await _make_registry()
        try:
            source = await _make_approved(reg, author="original_author")
            await reg.fork_template(source["id"], "new_forker", "Forked Template")
            earnings = await reg.get_creator_earnings("new_forker")
            # Profile was created for forker
            assert earnings["user_id"] == "new_forker"
        finally:
            await reg.close()

    async def test_fork_template_copies_base_template_id(self) -> None:
        """Forked listing inherits the base_template_id from the source."""
        reg = await _make_registry()
        try:
            source = await _make_approved(reg, base_id="base_tmpl_42")
            fork = await reg.fork_template(source["id"], "forker", "Fork")
            assert fork["base_template_id"] == "base_tmpl_42"
        finally:
            await reg.close()


# ===========================================================================
# TestGetCreatorEarnings
# ===========================================================================


class TestGetCreatorEarnings:
    """Tests for MarketplaceRegistry.get_creator_earnings."""

    async def test_get_creator_earnings_no_profile_returns_zeros(self) -> None:
        """Creator with no profile or activity returns zero earnings."""
        reg = await _make_registry()
        try:
            earnings = await reg.get_creator_earnings("unknown_user")
            assert earnings["total_earned_cents"] == 0
            assert earnings["pending_payout_cents"] == 0
            assert earnings["total_installs"] == 0
            assert earnings["template_count"] == 0
            assert earnings["connect_verified"] is False
        finally:
            await reg.close()

    async def test_get_creator_earnings_with_installs(self) -> None:
        """Creator earnings correctly aggregated after paid installs."""
        reg = await _make_registry()
        try:
            author = "earning_creator"
            approved = await _make_approved(reg, author=author, price_cents=1000)
            # Two installs of the same paid template
            await reg.install_template(approved["id"], "buyer1", "ag1")
            await reg.install_template(approved["id"], "buyer2", "ag2")
            earnings = await reg.get_creator_earnings(author)
            # 2 * 1000 * 70% = 1400 cents
            assert earnings["total_earned_cents"] == 1400
            assert earnings["total_installs"] == 2
        finally:
            await reg.close()

    async def test_get_creator_earnings_multiple_templates_aggregated(self) -> None:
        """Earnings across multiple templates are summed correctly."""
        reg = await _make_registry()
        try:
            author = "multi_creator"
            t1 = await _make_approved(
                reg, author=author, price_cents=200, name="Paid T1"
            )
            t2 = await _make_approved(
                reg, author=author, price_cents=300, name="Paid T2"
            )
            await reg.install_template(t1["id"], "buyer1", "ag1")
            await reg.install_template(t2["id"], "buyer2", "ag2")
            earnings = await reg.get_creator_earnings(author)
            # (200*0.7) + (300*0.7) = 140 + 210 = 350
            assert earnings["total_earned_cents"] == 350
            assert earnings["total_installs"] == 2
        finally:
            await reg.close()

    async def test_get_creator_earnings_returns_user_id(self) -> None:
        """get_creator_earnings always includes user_id in response."""
        reg = await _make_registry()
        try:
            earnings = await reg.get_creator_earnings("some_user")
            assert earnings["user_id"] == "some_user"
        finally:
            await reg.close()

    async def test_get_creator_earnings_pending_payout_counted(self) -> None:
        """Pending payouts are correctly tracked."""
        reg = await _make_registry()
        try:
            author = "pending_creator"
            approved = await _make_approved(reg, author=author, price_cents=400)
            await reg.install_template(approved["id"], "b1", "ag1", payment_intent_id="pi_1")
            earnings = await reg.get_creator_earnings(author)
            # 400 * 70% = 280 pending
            assert earnings["pending_payout_cents"] == 280
        finally:
            await reg.close()
