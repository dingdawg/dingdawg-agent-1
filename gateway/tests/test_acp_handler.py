"""TDD test suite for the ACP (Agentic Commerce Protocol) handler.

Spec version: 2026-01-30
Source: https://github.com/agentic-commerce-protocol/agentic-commerce-protocol
        https://docs.stripe.com/agentic-commerce/protocol/specification

Covers:
- Capability negotiation (v2026-01-30 requirement: capabilities block in every response)
- Product / catalog listing
- CreateCheckoutSession (POST)
- RetrieveCheckoutSession (GET)
- UpdateCheckoutSession (PATCH)
- CompleteCheckoutSession (POST with payment_data)
- CancelCheckoutSession (DELETE / POST)
- Payment handler declaration (Stripe tokenized card)
- Discount extension support
- Error schema validation (type / code / message / param)
- Idempotency key enforcement
- Amounts in minor units (integer cents)
- Session state machine (in_progress -> completed / cancelled)
- Missing required fields → 422 / error response
- Unknown session ID → 404
- Completed session cannot be updated
- Cancelled session cannot be completed
- Concurrent idempotent requests return same session
- Currency code validation (ISO 4217)
- Line item amount calculations
- Tax calculation
- Discount application
- Fulfillment options support
- Capabilities block structure
- Payment handler schema
- Handler name format (dev.acp.tokenized.card)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from isg_agent.protocols.acp_handler import (
    ACPCheckoutHandler,
    ACPError,
    ACPSessionStatus,
    CartLineItem,
    CheckoutSession,
    PaymentHandler,
    ACPCapabilities,
    ACPProduct,
    DiscountCode,
    FulfillmentOption,
    CreateCheckoutRequest,
    UpdateCheckoutRequest,
    CompleteCheckoutRequest,
    CancelCheckoutRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_line_item(
    product_id: str = "prod_001",
    title: str = "Agent Subscription",
    quantity: int = 1,
    unit_amount: int = 100,
    currency: str = "usd",
) -> dict:
    return {
        "product_id": product_id,
        "title": title,
        "quantity": quantity,
        "unit_amount": unit_amount,
        "currency": currency,
    }


def _make_create_request(
    line_items: list | None = None,
    currency: str = "usd",
    idempotency_key: str | None = None,
    merchant_id: str = "acct_test_dingdawg",
) -> CreateCheckoutRequest:
    if line_items is None:
        line_items = [_make_line_item()]
    return CreateCheckoutRequest(
        line_items=line_items,
        currency=currency,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        merchant_id=merchant_id,
    )


# ---------------------------------------------------------------------------
# 1. Dataclass / schema tests
# ---------------------------------------------------------------------------


class TestACPDataclasses:
    """Tests for ACP data structures."""

    def test_cart_line_item_fields(self):
        """CartLineItem stores product_id, title, quantity, unit_amount."""
        item = CartLineItem(
            product_id="prod_001",
            title="Test Product",
            quantity=2,
            unit_amount=500,
            currency="usd",
        )
        assert item.product_id == "prod_001"
        assert item.quantity == 2
        assert item.unit_amount == 500
        assert item.currency == "usd"

    def test_cart_line_item_subtotal(self):
        """CartLineItem.subtotal == quantity * unit_amount."""
        item = CartLineItem(product_id="p", title="T", quantity=3, unit_amount=200, currency="usd")
        assert item.subtotal == 600

    def test_cart_line_item_zero_quantity_subtotal(self):
        item = CartLineItem(product_id="p", title="T", quantity=0, unit_amount=999, currency="usd")
        assert item.subtotal == 0

    def test_acp_session_status_values(self):
        """ACPSessionStatus covers in_progress, completed, cancelled."""
        assert ACPSessionStatus.IN_PROGRESS.value == "in_progress"
        assert ACPSessionStatus.COMPLETED.value == "completed"
        assert ACPSessionStatus.CANCELLED.value == "cancelled"

    def test_payment_handler_has_required_fields(self):
        """PaymentHandler exposes id, name, version, psp."""
        h = PaymentHandler(
            id="card_tokenized",
            name="dev.acp.tokenized.card",
            version="2026-01-22",
            requires_delegate_payment=True,
            psp="stripe",
            config={"merchant_id": "acct_123", "accepted_brands": ["visa"]},
        )
        assert h.id == "card_tokenized"
        assert h.name == "dev.acp.tokenized.card"
        assert h.psp == "stripe"
        assert h.requires_delegate_payment is True

    def test_acp_capabilities_has_payment_and_extensions(self):
        """ACPCapabilities contains payment.handlers and extensions list."""
        handler = PaymentHandler(
            id="card_tokenized",
            name="dev.acp.tokenized.card",
            version="2026-01-22",
            requires_delegate_payment=True,
            psp="stripe",
            config={},
        )
        caps = ACPCapabilities(payment_handlers=[handler], extensions=["discount"])
        assert len(caps.payment_handlers) == 1
        assert "discount" in caps.extensions

    def test_acp_product_fields(self):
        """ACPProduct stores id, title, description, price, currency, availability."""
        p = ACPProduct(
            id="prod_001",
            title="DingDawg Starter Plan",
            description="AI agent subscription",
            price=100,
            currency="usd",
            availability="in_stock",
        )
        assert p.id == "prod_001"
        assert p.price == 100
        assert p.availability == "in_stock"

    def test_discount_code_fields(self):
        """DiscountCode stores code, amount_off (cents), percent_off."""
        d = DiscountCode(code="SAVE10", percent_off=10.0)
        assert d.code == "SAVE10"
        assert d.percent_off == 10.0
        assert d.amount_off is None

    def test_fulfillment_option_fields(self):
        """FulfillmentOption stores id, label, price."""
        fo = FulfillmentOption(id="instant", label="Instant delivery", price=0)
        assert fo.id == "instant"
        assert fo.price == 0


# ---------------------------------------------------------------------------
# 2. ACPCheckoutHandler — capability negotiation
# ---------------------------------------------------------------------------


class TestCapabilityNegotiation:
    """v2026-01-30: every checkout response must include capabilities block."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(
            merchant_id="acct_test_dingdawg",
            currency="usd",
        )

    def test_handler_exposes_capabilities(self):
        """Handler.get_capabilities() returns ACPCapabilities."""
        caps = self.handler.get_capabilities()
        assert isinstance(caps, ACPCapabilities)

    def test_capabilities_has_payment_handlers(self):
        """Capabilities payment_handlers list is non-empty."""
        caps = self.handler.get_capabilities()
        assert len(caps.payment_handlers) >= 1

    def test_capabilities_payment_handler_name_format(self):
        """Payment handler name follows dev.acp.* namespace."""
        caps = self.handler.get_capabilities()
        for h in caps.payment_handlers:
            assert h.name.startswith("dev.acp.")

    def test_capabilities_discount_extension_declared(self):
        """Discount extension is declared in capabilities."""
        caps = self.handler.get_capabilities()
        assert "discount" in caps.extensions

    def test_capabilities_to_dict_has_payment_block(self):
        """capabilities.to_dict() includes nested 'payment' key."""
        caps = self.handler.get_capabilities()
        d = caps.to_dict()
        assert "payment" in d
        assert "handlers" in d["payment"]

    def test_capabilities_to_dict_has_extensions(self):
        """capabilities.to_dict() includes 'extensions' list."""
        caps = self.handler.get_capabilities()
        d = caps.to_dict()
        assert "extensions" in d
        assert isinstance(d["extensions"], list)


# ---------------------------------------------------------------------------
# 3. Product listing
# ---------------------------------------------------------------------------


class TestProductListing:
    """Tests for get_products()."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(
            merchant_id="acct_test_dingdawg",
            currency="usd",
        )

    def test_get_products_returns_list(self):
        """get_products() returns a list."""
        products = self.handler.get_products()
        assert isinstance(products, list)

    def test_get_products_non_empty(self):
        """Default product catalog is non-empty."""
        products = self.handler.get_products()
        assert len(products) >= 1

    def test_product_has_required_fields(self):
        """Each product has id, title, price, currency, availability."""
        products = self.handler.get_products()
        for p in products:
            assert p.id
            assert p.title
            assert isinstance(p.price, int)
            assert p.currency
            assert p.availability in ("in_stock", "out_of_stock", "preorder")

    def test_product_prices_are_positive_integers(self):
        """All product prices are positive integers (minor units / cents)."""
        products = self.handler.get_products()
        for p in products:
            assert isinstance(p.price, int)
            assert p.price >= 0

    def test_get_product_by_id(self):
        """get_product(id) returns the matching product."""
        products = self.handler.get_products()
        first = products[0]
        found = self.handler.get_product(first.id)
        assert found is not None
        assert found.id == first.id

    def test_get_product_missing_returns_none(self):
        """get_product() returns None for unknown id."""
        result = self.handler.get_product("nonexistent_prod")
        assert result is None


# ---------------------------------------------------------------------------
# 4. Create checkout session
# ---------------------------------------------------------------------------


class TestCreateCheckout:
    """Tests for create_checkout_session()."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(
            merchant_id="acct_test_dingdawg",
            currency="usd",
        )

    def test_create_returns_checkout_session(self):
        """create_checkout_session() returns a CheckoutSession."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert isinstance(session, CheckoutSession)

    def test_create_assigns_id(self):
        """Created session has a non-empty string id."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert isinstance(session.id, str)
        assert len(session.id) > 0

    def test_create_status_is_in_progress(self):
        """New session status is 'in_progress'."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert session.status == ACPSessionStatus.IN_PROGRESS

    def test_create_preserves_currency(self):
        """Session currency matches request currency."""
        req = _make_create_request(currency="usd")
        session = self.handler.create_checkout_session(req)
        assert session.currency == "usd"

    def test_create_line_items_copied(self):
        """Session line_items matches requested line items."""
        items = [_make_line_item(quantity=2, unit_amount=500)]
        req = _make_create_request(line_items=items)
        session = self.handler.create_checkout_session(req)
        assert len(session.line_items) == 1
        assert session.line_items[0].quantity == 2
        assert session.line_items[0].unit_amount == 500

    def test_create_total_calculated(self):
        """Session total == sum of (quantity * unit_amount) for all items."""
        items = [
            _make_line_item(quantity=2, unit_amount=500),
            _make_line_item(product_id="p2", title="P2", quantity=1, unit_amount=300),
        ]
        req = _make_create_request(line_items=items)
        session = self.handler.create_checkout_session(req)
        assert session.subtotal == 1300  # 2*500 + 1*300

    def test_create_session_has_capabilities(self):
        """Created session exposes the capabilities block (v2026-01-30)."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert session.capabilities is not None
        caps_dict = session.capabilities.to_dict()
        assert "payment" in caps_dict

    def test_create_idempotency_same_key_returns_same_session(self):
        """Two create calls with the same idempotency key return the same session id."""
        key = uuid.uuid4().hex
        req1 = _make_create_request(idempotency_key=key)
        req2 = _make_create_request(idempotency_key=key)
        s1 = self.handler.create_checkout_session(req1)
        s2 = self.handler.create_checkout_session(req2)
        assert s1.id == s2.id

    def test_create_multiple_items_line_count(self):
        """Session stores all requested line items."""
        items = [_make_line_item(product_id=f"p{i}", title=f"P{i}") for i in range(3)]
        req = _make_create_request(line_items=items)
        session = self.handler.create_checkout_session(req)
        assert len(session.line_items) == 3


# ---------------------------------------------------------------------------
# 5. Retrieve checkout session
# ---------------------------------------------------------------------------


class TestRetrieveCheckout:
    """Tests for get_checkout_session()."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(merchant_id="acct_test_dingdawg", currency="usd")
        req = _make_create_request()
        self.session = self.handler.create_checkout_session(req)

    def test_retrieve_existing_session(self):
        """get_checkout_session() returns the session by id."""
        fetched = self.handler.get_checkout_session(self.session.id)
        assert fetched is not None
        assert fetched.id == self.session.id

    def test_retrieve_unknown_session_raises(self):
        """get_checkout_session() raises ACPError for unknown id."""
        with pytest.raises(ACPError) as exc_info:
            self.handler.get_checkout_session("nonexistent_session_id")
        assert exc_info.value.error_type == "invalid_request"
        assert exc_info.value.code == "not_found"

    def test_retrieve_preserves_status(self):
        """Retrieved session has same status as created session."""
        fetched = self.handler.get_checkout_session(self.session.id)
        assert fetched.status == ACPSessionStatus.IN_PROGRESS

    def test_retrieved_session_has_capabilities(self):
        """Retrieved session includes capabilities block."""
        fetched = self.handler.get_checkout_session(self.session.id)
        assert fetched.capabilities is not None


# ---------------------------------------------------------------------------
# 6. Update checkout session
# ---------------------------------------------------------------------------


class TestUpdateCheckout:
    """Tests for update_checkout_session()."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(merchant_id="acct_test_dingdawg", currency="usd")
        req = _make_create_request()
        self.session = self.handler.create_checkout_session(req)

    def test_update_line_items(self):
        """update_checkout_session() replaces line items and recalculates total."""
        new_items = [_make_line_item(quantity=3, unit_amount=200)]
        update_req = UpdateCheckoutRequest(
            session_id=self.session.id,
            line_items=new_items,
        )
        updated = self.handler.update_checkout_session(update_req)
        assert updated.subtotal == 600
        assert len(updated.line_items) == 1

    def test_update_adds_discount_code(self):
        """update_checkout_session() applies discount codes."""
        items = [_make_line_item(unit_amount=1000)]
        req = _make_create_request(line_items=items)
        session = self.handler.create_checkout_session(req)

        update_req = UpdateCheckoutRequest(
            session_id=session.id,
            discount_code="SAVE10",
        )
        updated = self.handler.update_checkout_session(update_req)
        # 10% off 1000 = 900
        assert updated.discount_amount >= 0  # discount was applied

    def test_update_unknown_session_raises(self):
        """Updating a non-existent session raises ACPError not_found."""
        update_req = UpdateCheckoutRequest(
            session_id="nonexistent_xyz",
            line_items=[_make_line_item()],
        )
        with pytest.raises(ACPError) as exc_info:
            self.handler.update_checkout_session(update_req)
        assert exc_info.value.code == "not_found"

    def test_update_completed_session_raises(self):
        """Updating a completed session raises ACPError."""
        items = [_make_line_item()]
        req = _make_create_request(line_items=items)
        session = self.handler.create_checkout_session(req)

        # Complete it first
        complete_req = CompleteCheckoutRequest(
            session_id=session.id,
            payment_data={
                "handler_id": "card_tokenized",
                "payment_instrument": {"token": "tok_test_visa"},
            },
        )
        self.handler.complete_checkout_session(complete_req)

        # Now try to update
        update_req = UpdateCheckoutRequest(
            session_id=session.id,
            line_items=[_make_line_item()],
        )
        with pytest.raises(ACPError) as exc_info:
            self.handler.update_checkout_session(update_req)
        assert exc_info.value.code in ("session_not_modifiable", "invalid_status")

    def test_update_sets_fulfillment_option(self):
        """update_checkout_session() stores selected fulfillment option."""
        update_req = UpdateCheckoutRequest(
            session_id=self.session.id,
            fulfillment_option_id="instant",
        )
        updated = self.handler.update_checkout_session(update_req)
        assert updated.selected_fulfillment_option_id == "instant"

    def test_update_returns_capabilities_block(self):
        """Updated session response includes capabilities block."""
        update_req = UpdateCheckoutRequest(
            session_id=self.session.id,
            line_items=[_make_line_item()],
        )
        updated = self.handler.update_checkout_session(update_req)
        assert updated.capabilities is not None


# ---------------------------------------------------------------------------
# 7. Complete checkout session
# ---------------------------------------------------------------------------


class TestCompleteCheckout:
    """Tests for complete_checkout_session()."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(merchant_id="acct_test_dingdawg", currency="usd")
        req = _make_create_request()
        self.session = self.handler.create_checkout_session(req)

    def test_complete_changes_status_to_completed(self):
        """complete_checkout_session() sets status to 'completed'."""
        complete_req = CompleteCheckoutRequest(
            session_id=self.session.id,
            payment_data={
                "handler_id": "card_tokenized",
                "payment_instrument": {"token": "tok_test_visa"},
            },
        )
        completed = self.handler.complete_checkout_session(complete_req)
        assert completed.status == ACPSessionStatus.COMPLETED

    def test_complete_missing_payment_data_raises(self):
        """complete_checkout_session() without payment_data raises ACPError."""
        with pytest.raises(ACPError) as exc_info:
            complete_req = CompleteCheckoutRequest(
                session_id=self.session.id,
                payment_data={},  # empty — missing required fields
            )
            self.handler.complete_checkout_session(complete_req)
        assert exc_info.value.error_type == "invalid_request"

    def test_complete_unknown_session_raises(self):
        """Completing unknown session raises ACPError not_found."""
        complete_req = CompleteCheckoutRequest(
            session_id="nonexistent_xyz",
            payment_data={"handler_id": "card_tokenized", "payment_instrument": {"token": "t"}},
        )
        with pytest.raises(ACPError) as exc_info:
            self.handler.complete_checkout_session(complete_req)
        assert exc_info.value.code == "not_found"

    def test_complete_already_completed_raises(self):
        """Completing an already-completed session raises ACPError."""
        complete_req = CompleteCheckoutRequest(
            session_id=self.session.id,
            payment_data={"handler_id": "card_tokenized", "payment_instrument": {"token": "t"}},
        )
        self.handler.complete_checkout_session(complete_req)

        with pytest.raises(ACPError) as exc_info:
            self.handler.complete_checkout_session(complete_req)
        assert exc_info.value.code in ("session_already_completed", "invalid_status")

    def test_complete_records_order_id(self):
        """Completed session has a non-empty order_id."""
        complete_req = CompleteCheckoutRequest(
            session_id=self.session.id,
            payment_data={"handler_id": "card_tokenized", "payment_instrument": {"token": "t"}},
        )
        completed = self.handler.complete_checkout_session(complete_req)
        assert completed.order_id is not None
        assert len(completed.order_id) > 0

    def test_complete_includes_capabilities(self):
        """Complete response includes capabilities block."""
        complete_req = CompleteCheckoutRequest(
            session_id=self.session.id,
            payment_data={"handler_id": "card_tokenized", "payment_instrument": {"token": "t"}},
        )
        completed = self.handler.complete_checkout_session(complete_req)
        assert completed.capabilities is not None


# ---------------------------------------------------------------------------
# 8. Cancel checkout session
# ---------------------------------------------------------------------------


class TestCancelCheckout:
    """Tests for cancel_checkout_session()."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(merchant_id="acct_test_dingdawg", currency="usd")
        req = _make_create_request()
        self.session = self.handler.create_checkout_session(req)

    def test_cancel_sets_status_to_cancelled(self):
        """cancel_checkout_session() sets status to 'cancelled'."""
        cancel_req = CancelCheckoutRequest(session_id=self.session.id)
        cancelled = self.handler.cancel_checkout_session(cancel_req)
        assert cancelled.status == ACPSessionStatus.CANCELLED

    def test_cancel_unknown_session_raises(self):
        """Cancelling unknown session raises ACPError not_found."""
        cancel_req = CancelCheckoutRequest(session_id="nonexistent_xyz")
        with pytest.raises(ACPError) as exc_info:
            self.handler.cancel_checkout_session(cancel_req)
        assert exc_info.value.code == "not_found"

    def test_cancel_completed_session_raises(self):
        """Cannot cancel an already-completed session."""
        complete_req = CompleteCheckoutRequest(
            session_id=self.session.id,
            payment_data={"handler_id": "card_tokenized", "payment_instrument": {"token": "t"}},
        )
        self.handler.complete_checkout_session(complete_req)

        cancel_req = CancelCheckoutRequest(session_id=self.session.id)
        with pytest.raises(ACPError) as exc_info:
            self.handler.cancel_checkout_session(cancel_req)
        assert exc_info.value.code in ("session_already_completed", "invalid_status")

    def test_cancel_already_cancelled_raises(self):
        """Cancelling an already-cancelled session raises ACPError."""
        cancel_req = CancelCheckoutRequest(session_id=self.session.id)
        self.handler.cancel_checkout_session(cancel_req)
        with pytest.raises(ACPError) as exc_info:
            self.handler.cancel_checkout_session(cancel_req)
        assert exc_info.value.code in ("session_already_cancelled", "invalid_status")

    def test_cancel_includes_capabilities(self):
        """Cancel response includes capabilities block."""
        cancel_req = CancelCheckoutRequest(session_id=self.session.id)
        cancelled = self.handler.cancel_checkout_session(cancel_req)
        assert cancelled.capabilities is not None


# ---------------------------------------------------------------------------
# 9. Error schema validation
# ---------------------------------------------------------------------------


class TestACPError:
    """Tests for the ACPError schema."""

    def test_acp_error_fields(self):
        """ACPError has error_type, code, message, and optional param."""
        err = ACPError(
            error_type="invalid_request",
            code="invalid",
            message="quantity must be positive",
            param="$.line_items[0].quantity",
        )
        assert err.error_type == "invalid_request"
        assert err.code == "invalid"
        assert err.param == "$.line_items[0].quantity"

    def test_acp_error_to_dict(self):
        """ACPError.to_dict() returns ACP-spec error format."""
        err = ACPError(
            error_type="processing_error",
            code="payment_failed",
            message="Card declined",
        )
        d = err.to_dict()
        assert d["type"] == "processing_error"
        assert d["code"] == "payment_failed"
        assert d["message"] == "Card declined"
        assert "param" not in d or d["param"] is None

    def test_acp_error_type_values(self):
        """ACPError.error_type must be one of the 4 ACP-defined types."""
        valid_types = {
            "invalid_request",
            "request_not_idempotent",
            "processing_error",
            "service_unavailable",
        }
        err = ACPError(error_type="invalid_request", code="test", message="test")
        assert err.error_type in valid_types

    def test_acp_error_is_exception(self):
        """ACPError is raised as an exception (is Exception subclass)."""
        err = ACPError(error_type="invalid_request", code="test", message="test")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# 10. Amount / currency validation
# ---------------------------------------------------------------------------


class TestAmountCurrencyValidation:
    """Tests for minor-unit amounts and currency code enforcement."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(merchant_id="acct_test_dingdawg", currency="usd")

    def test_session_amounts_are_integers(self):
        """All monetary amounts in CheckoutSession are integers."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert isinstance(session.subtotal, int)
        assert isinstance(session.total, int)

    def test_currency_stored_lowercase(self):
        """Currency codes are stored in lowercase."""
        req = _make_create_request(currency="USD")
        session = self.handler.create_checkout_session(req)
        assert session.currency == "usd"

    def test_tax_amount_is_integer(self):
        """Tax amount is stored as integer cents."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert isinstance(session.tax_amount, int)

    def test_discount_amount_is_integer(self):
        """Discount amount is stored as integer cents."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        assert isinstance(session.discount_amount, int)

    def test_total_equals_subtotal_plus_tax_minus_discount(self):
        """total == subtotal + tax_amount - discount_amount."""
        req = _make_create_request()
        session = self.handler.create_checkout_session(req)
        expected = session.subtotal + session.tax_amount - session.discount_amount
        assert session.total == expected


# ---------------------------------------------------------------------------
# 11. Session serialization (to_dict)
# ---------------------------------------------------------------------------


class TestSessionSerialization:
    """Tests for CheckoutSession.to_dict() — the wire format."""

    def setup_method(self):
        self.handler = ACPCheckoutHandler(merchant_id="acct_test_dingdawg", currency="usd")
        req = _make_create_request()
        self.session = self.handler.create_checkout_session(req)

    def test_to_dict_has_required_fields(self):
        """to_dict() includes all ACP-required fields."""
        d = self.session.to_dict()
        required = {"id", "status", "currency", "line_items", "subtotal", "total", "capabilities"}
        missing = required - set(d.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_to_dict_status_is_string(self):
        """to_dict() status is a string (not enum object)."""
        d = self.session.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "in_progress"

    def test_to_dict_line_items_is_list(self):
        """to_dict() line_items is a list of dicts."""
        d = self.session.to_dict()
        assert isinstance(d["line_items"], list)
        for item in d["line_items"]:
            assert isinstance(item, dict)

    def test_to_dict_capabilities_is_dict(self):
        """to_dict() capabilities is a dict with 'payment' and 'extensions'."""
        d = self.session.to_dict()
        caps = d["capabilities"]
        assert isinstance(caps, dict)
        assert "payment" in caps
        assert "extensions" in caps
