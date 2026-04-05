"""Tests for built-in business skills: invoicing, inventory, expense_tracker.

Covers all actions for each skill with parameterized agent_id isolation,
error handling, edge cases, and cross-action workflows.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from isg_agent.skills.builtin.invoicing import InvoicingSkill, init_tables as inv_init
from isg_agent.skills.builtin.inventory import InventorySkill, init_tables as stock_init
from isg_agent.skills.builtin.expense_tracker import ExpenseTrackerSkill, init_tables as exp_init


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        p = Path(f.name)
    yield p
    p.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)


@pytest.fixture()
async def invoicing(tmp_db):
    await inv_init(str(tmp_db))
    return InvoicingSkill(str(tmp_db))


@pytest.fixture()
async def inventory(tmp_db):
    await stock_init(str(tmp_db))
    return InventorySkill(str(tmp_db))


@pytest.fixture()
async def expenses(tmp_db):
    await exp_init(str(tmp_db))
    return ExpenseTrackerSkill(str(tmp_db))


def _p(result: str) -> dict:
    return json.loads(result)


# ===========================================================================
# InvoicingSkill Tests
# ===========================================================================


class TestInvoicingCreate:
    async def test_create_basic(self, invoicing):
        r = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1",
            "client_name": "Acme Corp",
            "line_items": [{"description": "Widget", "quantity": 2, "unit_price_cents": 1000}],
        }))
        assert r["status"] == "draft"
        assert r["total_cents"] == 2000
        assert r["invoice_number"].startswith("INV-")

    async def test_create_with_tax(self, invoicing):
        r = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1",
            "client_name": "Bob", "tax_rate": 0.1,
            "line_items": [{"description": "Svc", "quantity": 1, "unit_price_cents": 10000}],
        }))
        assert r["total_cents"] == 11000

    async def test_create_missing_client(self, invoicing):
        r = _p(await invoicing.handle({"action": "create", "line_items": []}))
        assert "error" in r

    async def test_create_missing_items(self, invoicing):
        r = _p(await invoicing.handle({"action": "create", "client_name": "X"}))
        assert "error" in r

    async def test_create_sequential_numbers(self, invoicing):
        base = {"action": "create", "agent_id": "a1", "client_name": "C",
                "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}]}
        r1 = _p(await invoicing.handle(base))
        r2 = _p(await invoicing.handle(base))
        n1 = int(r1["invoice_number"].split("-")[-1])
        n2 = int(r2["invoice_number"].split("-")[-1])
        assert n2 == n1 + 1


class TestInvoicingSend:
    async def test_send_draft(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 500}],
        }))
        r = _p(await invoicing.handle({"action": "send", "id": cr["id"]}))
        assert r["status"] == "sent"

    async def test_send_already_sent(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 500}],
        }))
        await invoicing.handle({"action": "send", "id": cr["id"]})
        r = _p(await invoicing.handle({"action": "send", "id": cr["id"]}))
        assert "error" in r

    async def test_send_missing_id(self, invoicing):
        r = _p(await invoicing.handle({"action": "send"}))
        assert "error" in r


class TestInvoicingMarkPaid:
    async def test_mark_paid(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 500}],
        }))
        await invoicing.handle({"action": "send", "id": cr["id"]})
        r = _p(await invoicing.handle({
            "action": "mark_paid", "id": cr["id"],
            "amount_cents": 500, "payment_method": "credit_card",
        }))
        assert r["status"] == "paid"

    async def test_mark_paid_draft_fails(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 500}],
        }))
        r = _p(await invoicing.handle({"action": "mark_paid", "id": cr["id"]}))
        assert "error" in r


class TestInvoicingGet:
    async def test_get_invoice(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 500}],
        }))
        r = _p(await invoicing.handle({"action": "get", "id": cr["id"]}))
        assert r["client_name"] == "C"
        assert isinstance(r["line_items"], list)

    async def test_get_not_found(self, invoicing):
        r = _p(await invoicing.handle({"action": "get", "id": "fake"}))
        assert "error" in r

    async def test_get_missing_id(self, invoicing):
        r = _p(await invoicing.handle({"action": "get"}))
        assert "error" in r


class TestInvoicingList:
    async def test_list_all(self, invoicing):
        await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}],
        })
        r = _p(await invoicing.handle({"action": "list", "agent_id": "a1"}))
        assert len(r["invoices"]) == 1

    async def test_list_filter_status(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}],
        }))
        await invoicing.handle({"action": "send", "id": cr["id"]})
        r = _p(await invoicing.handle({"action": "list", "agent_id": "a1", "status": "draft"}))
        assert len(r["invoices"]) == 0


class TestInvoicingOverdue:
    async def test_get_overdue(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}],
            "due_date": "2020-01-01T00:00:00+00:00",
        }))
        await invoicing.handle({"action": "send", "id": cr["id"]})
        r = _p(await invoicing.handle({"action": "get_overdue", "agent_id": "a1"}))
        assert len(r["overdue"]) == 1


class TestInvoicingReminder:
    async def test_send_reminder(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "client_email": "c@test.com",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}],
            "due_date": "2020-01-01",
        }))
        r = _p(await invoicing.handle({"action": "send_reminder", "id": cr["id"]}))
        assert "reminder_message" in r
        assert "c@test.com" == r["client_email"]

    async def test_reminder_not_found(self, invoicing):
        r = _p(await invoicing.handle({"action": "send_reminder", "id": "fake"}))
        assert "error" in r


class TestInvoicingSummary:
    async def test_get_summary(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 5000}],
        }))
        await invoicing.handle({"action": "send", "id": cr["id"]})
        await invoicing.handle({"action": "mark_paid", "id": cr["id"], "amount_cents": 5000})
        r = _p(await invoicing.handle({"action": "get_summary", "agent_id": "a1"}))
        assert r["total_invoiced_cents"] == 5000
        assert r["total_paid_cents"] == 5000


class TestInvoicingVoid:
    async def test_void_draft(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}],
        }))
        r = _p(await invoicing.handle({"action": "void", "id": cr["id"]}))
        assert r["status"] == "cancelled"

    async def test_void_paid_fails(self, invoicing):
        cr = _p(await invoicing.handle({
            "action": "create", "agent_id": "a1", "client_name": "C",
            "line_items": [{"description": "x", "quantity": 1, "unit_price_cents": 100}],
        }))
        await invoicing.handle({"action": "send", "id": cr["id"]})
        await invoicing.handle({"action": "mark_paid", "id": cr["id"]})
        r = _p(await invoicing.handle({"action": "void", "id": cr["id"]}))
        assert "error" in r

    async def test_void_missing_id(self, invoicing):
        r = _p(await invoicing.handle({"action": "void"}))
        assert "error" in r


class TestInvoicingUnknown:
    async def test_unknown_action(self, invoicing):
        r = _p(await invoicing.handle({"action": "explode"}))
        assert "error" in r


# ===========================================================================
# InventorySkill Tests
# ===========================================================================


class TestInventoryAddItem:
    async def test_add_item(self, inventory):
        r = _p(await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Flour",
            "quantity": 100, "unit": "lbs", "category": "baking",
            "cost_per_unit_cents": 50, "supplier_name": "SupplyHouse",
        }))
        assert r["status"] == "created"

    async def test_add_duplicate_name(self, inventory):
        base = {"action": "add_item", "agent_id": "a1", "item_name": "Flour"}
        await inventory.handle(base)
        r = _p(await inventory.handle(base))
        assert "error" in r

    async def test_add_missing_name(self, inventory):
        r = _p(await inventory.handle({"action": "add_item"}))
        assert "error" in r


class TestInventoryUpdateStock:
    async def test_restock(self, inventory):
        cr = _p(await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Flour", "quantity": 10,
        }))
        r = _p(await inventory.handle({
            "action": "update_stock", "agent_id": "a1",
            "item_id": cr["id"], "quantity_change": 50, "change_type": "restock",
        }))
        assert r["quantity_after"] == 60

    async def test_use_stock(self, inventory):
        cr = _p(await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Sugar", "quantity": 100,
        }))
        r = _p(await inventory.handle({
            "action": "update_stock", "agent_id": "a1",
            "item_id": cr["id"], "quantity_change": -20, "change_type": "use",
        }))
        assert r["quantity_after"] == 80

    async def test_update_by_name(self, inventory):
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Eggs", "quantity": 50,
        })
        r = _p(await inventory.handle({
            "action": "update_stock", "agent_id": "a1",
            "item_name": "Eggs", "quantity_change": -10, "change_type": "use",
        }))
        assert r["quantity_after"] == 40

    async def test_update_not_found(self, inventory):
        r = _p(await inventory.handle({
            "action": "update_stock", "agent_id": "a1", "item_id": "fake",
        }))
        assert "error" in r


class TestInventoryLowStock:
    async def test_check_low_stock(self, inventory):
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Flour",
            "quantity": 5, "reorder_point": 10,
        })
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Sugar",
            "quantity": 100, "reorder_point": 10,
        })
        r = _p(await inventory.handle({"action": "check_low_stock", "agent_id": "a1"}))
        assert len(r["low_stock_items"]) == 1
        assert r["low_stock_items"][0]["item_name"] == "Flour"


class TestInventoryGetItem:
    async def test_get_item(self, inventory):
        cr = _p(await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Butter",
        }))
        r = _p(await inventory.handle({"action": "get_item", "id": cr["id"]}))
        assert r["item_name"] == "Butter"

    async def test_get_not_found(self, inventory):
        r = _p(await inventory.handle({"action": "get_item", "id": "nope"}))
        assert "error" in r

    async def test_get_missing_id(self, inventory):
        r = _p(await inventory.handle({"action": "get_item"}))
        assert "error" in r


class TestInventoryList:
    async def test_list(self, inventory):
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "A", "category": "cat1",
        })
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "B", "category": "cat2",
        })
        r = _p(await inventory.handle({"action": "list", "agent_id": "a1"}))
        assert len(r["items"]) == 2

    async def test_list_by_category(self, inventory):
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "A", "category": "cat1",
        })
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "B", "category": "cat2",
        })
        r = _p(await inventory.handle({"action": "list", "agent_id": "a1", "category": "cat1"}))
        assert len(r["items"]) == 1


class TestInventorySearch:
    async def test_search(self, inventory):
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Organic Flour",
        })
        r = _p(await inventory.handle({"action": "search", "agent_id": "a1", "query": "flour"}))
        assert len(r["items"]) == 1

    async def test_search_missing_query(self, inventory):
        r = _p(await inventory.handle({"action": "search"}))
        assert "error" in r


class TestInventoryGenerateOrder:
    async def test_generate_order(self, inventory):
        await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Flour",
            "quantity": 5, "reorder_point": 10, "reorder_quantity": 50,
            "cost_per_unit_cents": 100, "supplier_name": "Mill Co",
        })
        r = _p(await inventory.handle({"action": "generate_order", "agent_id": "a1"}))
        assert r["item_count"] == 1
        assert r["total_estimated_cents"] == 5000
        assert r["purchase_order"][0]["supplier"] == "Mill Co"


class TestInventoryUsageReport:
    async def test_usage_report_empty(self, inventory):
        r = _p(await inventory.handle({"action": "get_usage_report", "agent_id": "a1"}))
        assert r["usage_report"] == []


class TestInventoryWaste:
    async def test_waste_log(self, inventory):
        cr = _p(await inventory.handle({
            "action": "add_item", "agent_id": "a1", "item_name": "Milk", "quantity": 50,
        }))
        r = _p(await inventory.handle({
            "action": "waste_log", "agent_id": "a1",
            "item_id": cr["id"], "quantity": 5,
        }))
        assert r["quantity_after"] == 45

    async def test_waste_zero(self, inventory):
        r = _p(await inventory.handle({
            "action": "waste_log", "agent_id": "a1", "item_id": "x", "quantity": 0,
        }))
        assert "error" in r


class TestInventoryUnknown:
    async def test_unknown_action(self, inventory):
        r = _p(await inventory.handle({"action": "destroy"}))
        assert "error" in r


# ===========================================================================
# ExpenseTrackerSkill Tests
# ===========================================================================


class TestExpenseRecord:
    async def test_record(self, expenses):
        r = _p(await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Office supplies", "amount_cents": 4500,
            "category": "supplies", "vendor": "Staples",
            "expense_date": "2026-02-01",
        }))
        assert r["status"] == "recorded"

    async def test_record_missing_description(self, expenses):
        r = _p(await expenses.handle({
            "action": "record", "amount_cents": 100, "expense_date": "2026-02-01",
        }))
        assert "error" in r

    async def test_record_missing_amount(self, expenses):
        r = _p(await expenses.handle({
            "action": "record", "description": "X", "expense_date": "2026-02-01",
        }))
        assert "error" in r

    async def test_record_missing_date(self, expenses):
        r = _p(await expenses.handle({
            "action": "record", "description": "X", "amount_cents": 100,
        }))
        assert "error" in r


class TestExpenseGet:
    async def test_get(self, expenses):
        cr = _p(await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Paper", "amount_cents": 1000,
            "expense_date": "2026-02-01",
        }))
        r = _p(await expenses.handle({"action": "get", "id": cr["id"]}))
        assert r["description"] == "Paper"

    async def test_get_not_found(self, expenses):
        r = _p(await expenses.handle({"action": "get", "id": "fake"}))
        assert "error" in r

    async def test_get_missing_id(self, expenses):
        r = _p(await expenses.handle({"action": "get"}))
        assert "error" in r


class TestExpenseList:
    async def test_list(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "A", "amount_cents": 100, "expense_date": "2026-02-01",
        })
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "B", "amount_cents": 200, "expense_date": "2026-02-02",
        })
        r = _p(await expenses.handle({"action": "list", "agent_id": "a1"}))
        assert len(r["expenses"]) == 2

    async def test_list_filter_category(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "A", "amount_cents": 100,
            "category": "supplies", "expense_date": "2026-02-01",
        })
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "B", "amount_cents": 200,
            "category": "rent", "expense_date": "2026-02-01",
        })
        r = _p(await expenses.handle({"action": "list", "agent_id": "a1", "category": "rent"}))
        assert len(r["expenses"]) == 1


class TestExpenseByCategory:
    async def test_by_category(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "A", "amount_cents": 100,
            "category": "supplies", "expense_date": "2026-02-01",
        })
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "B", "amount_cents": 300,
            "category": "supplies", "expense_date": "2026-02-01",
        })
        r = _p(await expenses.handle({"action": "get_by_category", "agent_id": "a1"}))
        assert r["by_category"]["supplies"] == 400


class TestExpenseMonthlyReport:
    async def test_monthly_report(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Rent", "amount_cents": 200000,
            "category": "rent", "vendor": "Landlord",
            "expense_date": "2026-02-15",
        })
        r = _p(await expenses.handle({
            "action": "get_monthly_report", "agent_id": "a1", "month": "2026-02",
        }))
        assert r["total_cents"] == 200000
        assert "rent" in r["by_category"]
        assert "Landlord" in r["top_vendors"]


class TestExpenseRecurring:
    async def test_get_recurring(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Insurance", "amount_cents": 50000,
            "is_recurring": 1, "recurrence_period": "monthly",
            "expense_date": "2026-02-01",
        })
        r = _p(await expenses.handle({"action": "get_recurring", "agent_id": "a1"}))
        assert len(r["recurring_expenses"]) == 1
        assert r["recurring_expenses"][0]["annual_projection_cents"] == 600000

    async def test_recurring_annual(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "License", "amount_cents": 120000,
            "is_recurring": 1, "recurrence_period": "annual",
            "expense_date": "2026-01-01",
        })
        r = _p(await expenses.handle({"action": "get_recurring", "agent_id": "a1"}))
        assert r["recurring_expenses"][0]["annual_projection_cents"] == 120000


class TestExpenseSearch:
    async def test_search(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Office cleaning service", "amount_cents": 15000,
            "expense_date": "2026-02-01",
        })
        r = _p(await expenses.handle({"action": "search", "agent_id": "a1", "query": "cleaning"}))
        assert len(r["expenses"]) == 1

    async def test_search_missing_query(self, expenses):
        r = _p(await expenses.handle({"action": "search"}))
        assert "error" in r


class TestExpenseProfitLoss:
    async def test_profit_loss(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Cost", "amount_cents": 30000,
            "expense_date": "2026-02-01",
        })
        r = _p(await expenses.handle({
            "action": "get_profit_loss", "agent_id": "a1", "revenue_cents": 100000,
        }))
        assert r["profit_cents"] == 70000
        assert r["margin_pct"] == 70.0

    async def test_profit_loss_zero_revenue(self, expenses):
        r = _p(await expenses.handle({
            "action": "get_profit_loss", "agent_id": "a1", "revenue_cents": 0,
        }))
        assert r["margin_pct"] == 0


class TestExpenseTaxDeductible:
    async def test_tax_deductible(self, expenses):
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Deductible", "amount_cents": 5000,
            "tax_deductible": 1, "expense_date": "2026-02-01",
        })
        await expenses.handle({
            "action": "record", "agent_id": "a1",
            "description": "Not Deductible", "amount_cents": 2000,
            "tax_deductible": 0, "expense_date": "2026-02-01",
        })
        r = _p(await expenses.handle({"action": "get_tax_deductible", "agent_id": "a1"}))
        assert r["total_deductible_cents"] == 5000
        assert len(r["deductible_expenses"]) == 1


class TestExpenseUnknown:
    async def test_unknown_action(self, expenses):
        r = _p(await expenses.handle({"action": "nuke"}))
        assert "error" in r
