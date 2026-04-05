"""MCP tools that expose DingDawg's 13 business skills as individual MCP tools.

Each business skill (appointments, invoicing, contacts, etc.) gets its own
dedicated MCP tool with typed parameters instead of routing through the
generic skill_execute tool. This makes the tools discoverable and
self-documenting for Claude Desktop, Claude Code, and other MCP clients.

Tools (13):
    book_appointment     — Schedule, cancel, reschedule, or list appointments
    create_invoice       — Create, send, or mark invoices as paid
    manage_contacts      — Add, update, search, or tag CRM contacts
    send_notification    — Queue email, SMS, push, or webhook notifications
    manage_webhooks      — Register, trigger, or list outbound webhooks
    manage_forms         — Create and manage intake/feedback forms
    customer_engagement  — Loyalty, campaigns, and engagement tracking
    manage_reviews       — Request, track, and respond to customer reviews
    referral_program     — Create and track referral campaigns
    manage_inventory     — Track products, stock levels, and adjustments
    track_expenses       — Record, categorize, and report business expenses
    business_operations  — Tasks, staff scheduling, and business metrics
    data_store           — Key-value data storage for agent state

All tools require agent_handle to identify the target agent and route
through the existing SkillExecutor pipeline with full audit trail.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_business_skill_tools(mcp: FastMCP, get_state) -> None:
    """Register all 13 business skill MCP tools on the given FastMCP server.

    Parameters
    ----------
    mcp:
        The FastMCP server instance to register tools on.
    get_state:
        Callable returning the app state object (must have skill_executor
        and agent_registry attributes).
    """

    def _executor():
        state = get_state()
        if state is None:
            raise RuntimeError("MCP server not wired — call wire_app_state() first")
        return state.skill_executor

    async def _resolve_agent_id(agent_handle: str) -> str:
        """Resolve an agent handle to its UUID."""
        state = get_state()
        if state is None:
            raise RuntimeError("MCP server not wired")
        registry = state.agent_registry
        agent = await registry.get_agent_by_handle(agent_handle)
        if agent is None:
            raise ValueError(f"Agent not found: @{agent_handle}")
        return agent.id

    async def _run_skill(
        skill_name: str,
        agent_handle: str,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a skill through the SkillExecutor and return parsed result."""
        agent_id = await _resolve_agent_id(agent_handle)
        executor = _executor()
        enriched = {
            **params,
            "agent_id": agent_id,
            "action": action,
        }
        result = await executor.execute(skill_name=skill_name, parameters=enriched)
        output = {}
        if result.output:
            try:
                output = json.loads(result.output)
            except (json.JSONDecodeError, TypeError):
                output = {"raw": result.output}
        return {
            "success": result.success,
            "data": output,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "audit_id": result.audit_id,
        }

    # -----------------------------------------------------------------------
    # Tool 1: book_appointment
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="book_appointment",
        description=(
            "Schedule, cancel, reschedule, complete, or list appointments for a "
            "DingDawg business agent. Actions: schedule, cancel, reschedule, "
            "complete, list, get."
        ),
    )
    async def book_appointment(
        agent_handle: str,
        action: str,
        contact_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        appointment_id: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage appointments for a business agent."""
        params: Dict[str, Any] = {}
        if contact_name:
            params["contact_name"] = contact_name
        if contact_email:
            params["contact_email"] = contact_email
        if contact_phone:
            params["contact_phone"] = contact_phone
        if title:
            params["title"] = title
        if description:
            params["description"] = description
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if location:
            params["location"] = location
        if notes:
            params["notes"] = notes
        if appointment_id:
            params["id"] = appointment_id
        if status_filter:
            params["status"] = status_filter
        return await _run_skill("appointments", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 2: create_invoice
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="create_invoice",
        description=(
            "Create, send, mark as paid, void, or list invoices for a business "
            "agent. Actions: create, send, mark_paid, void, list, get, report."
        ),
    )
    async def create_invoice(
        agent_handle: str,
        action: str,
        client_name: Optional[str] = None,
        client_email: Optional[str] = None,
        line_items: Optional[str] = None,
        tax_rate: Optional[float] = None,
        due_date: Optional[str] = None,
        currency: str = "USD",
        notes: Optional[str] = None,
        invoice_id: Optional[str] = None,
        payment_method: Optional[str] = None,
        paid_amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Manage invoices for a business agent."""
        params: Dict[str, Any] = {"currency": currency}
        if client_name:
            params["client_name"] = client_name
        if client_email:
            params["client_email"] = client_email
        if line_items:
            try:
                params["line_items"] = json.loads(line_items)
            except json.JSONDecodeError:
                return {"success": False, "error": "line_items must be valid JSON array", "data": {}}
        if tax_rate is not None:
            params["tax_rate"] = tax_rate
        if due_date:
            params["due_date"] = due_date
        if notes:
            params["notes"] = notes
        if invoice_id:
            params["id"] = invoice_id
        if payment_method:
            params["payment_method"] = payment_method
        if paid_amount_cents is not None:
            params["paid_amount_cents"] = paid_amount_cents
        return await _run_skill("invoicing", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 3: manage_contacts
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="manage_contacts",
        description=(
            "Add, update, search, tag, or delete CRM contacts for a business "
            "agent. Actions: add, update, search, get, delete, tag, untag, list."
        ),
    )
    async def manage_contacts(
        agent_handle: str,
        action: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        company: Optional[str] = None,
        tags: Optional[str] = None,
        notes: Optional[str] = None,
        source: Optional[str] = None,
        contact_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage CRM contacts for a business agent."""
        params: Dict[str, Any] = {}
        if name:
            params["name"] = name
        if email:
            params["email"] = email
        if phone:
            params["phone"] = phone
        if company:
            params["company"] = company
        if tags:
            try:
                params["tags"] = json.loads(tags)
            except json.JSONDecodeError:
                params["tags"] = [tags]
        if notes:
            params["notes"] = notes
        if source:
            params["source"] = source
        if contact_id:
            params["id"] = contact_id
        if query:
            params["query"] = query
        return await _run_skill("contacts", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 4: send_notification
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="send_notification",
        description=(
            "Queue an email, SMS, push, or webhook notification for a business "
            "agent. Actions: send, list, cancel, get."
        ),
    )
    async def send_notification(
        agent_handle: str,
        action: str,
        channel: Optional[str] = None,
        recipient: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        priority: str = "normal",
        notification_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Queue or manage notifications for a business agent."""
        params: Dict[str, Any] = {"priority": priority}
        if channel:
            params["channel"] = channel
        if recipient:
            params["recipient"] = recipient
        if subject:
            params["subject"] = subject
        if body:
            params["body"] = body
        if notification_id:
            params["id"] = notification_id
        return await _run_skill("notifications", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 5: manage_webhooks
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="manage_webhooks",
        description=(
            "Register, trigger, update, or list outbound webhooks for a business "
            "agent. Actions: register, trigger, list, update, deactivate, logs."
        ),
    )
    async def manage_webhooks(
        agent_handle: str,
        action: str,
        name: Optional[str] = None,
        url: Optional[str] = None,
        method: str = "POST",
        webhook_id: Optional[str] = None,
        payload: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage outbound webhooks for a business agent."""
        params: Dict[str, Any] = {"method": method}
        if name:
            params["name"] = name
        if url:
            params["url"] = url
        if webhook_id:
            params["webhook_id"] = webhook_id
            params["id"] = webhook_id
        if payload:
            try:
                params["payload"] = json.loads(payload)
            except json.JSONDecodeError:
                params["payload"] = {"message": payload}
        return await _run_skill("webhooks", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 6: manage_forms
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="manage_forms",
        description=(
            "Create and manage intake forms, feedback forms, and surveys for a "
            "business agent. Actions: create, list, get, submit, results, delete."
        ),
    )
    async def manage_forms(
        agent_handle: str,
        action: str,
        title: Optional[str] = None,
        fields: Optional[str] = None,
        form_id: Optional[str] = None,
        submission_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage forms for a business agent."""
        params: Dict[str, Any] = {}
        if title:
            params["title"] = title
        if fields:
            try:
                params["fields"] = json.loads(fields)
            except json.JSONDecodeError:
                return {"success": False, "error": "fields must be valid JSON array", "data": {}}
        if form_id:
            params["id"] = form_id
        if submission_data:
            try:
                params["data"] = json.loads(submission_data)
            except json.JSONDecodeError:
                return {"success": False, "error": "submission_data must be valid JSON", "data": {}}
        return await _run_skill("forms", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 7: customer_engagement
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="customer_engagement",
        description=(
            "Track customer loyalty, run campaigns, and measure engagement for a "
            "business agent. Actions: add_points, get_loyalty, create_campaign, "
            "list_campaigns, track_interaction."
        ),
    )
    async def customer_engagement_tool(
        agent_handle: str,
        action: str,
        contact_id: Optional[str] = None,
        points: Optional[int] = None,
        campaign_name: Optional[str] = None,
        campaign_type: Optional[str] = None,
        interaction_type: Optional[str] = None,
        metadata: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage customer engagement for a business agent."""
        params: Dict[str, Any] = {}
        if contact_id:
            params["contact_id"] = contact_id
        if points is not None:
            params["points"] = points
        if campaign_name:
            params["campaign_name"] = campaign_name
        if campaign_type:
            params["campaign_type"] = campaign_type
        if interaction_type:
            params["interaction_type"] = interaction_type
        if metadata:
            try:
                params["metadata"] = json.loads(metadata)
            except json.JSONDecodeError:
                params["metadata"] = {"note": metadata}
        return await _run_skill("customer-engagement", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 8: manage_reviews
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="manage_reviews",
        description=(
            "Request, track, and respond to customer reviews for a business "
            "agent. Actions: request, list, get, respond, report."
        ),
    )
    async def manage_reviews(
        agent_handle: str,
        action: str,
        contact_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        rating: Optional[int] = None,
        review_text: Optional[str] = None,
        response_text: Optional[str] = None,
        review_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage customer reviews for a business agent."""
        params: Dict[str, Any] = {}
        if contact_name:
            params["contact_name"] = contact_name
        if contact_email:
            params["contact_email"] = contact_email
        if rating is not None:
            params["rating"] = rating
        if review_text:
            params["review_text"] = review_text
        if response_text:
            params["response_text"] = response_text
        if review_id:
            params["id"] = review_id
        return await _run_skill("review-manager", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 9: referral_program
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="referral_program",
        description=(
            "Create and track customer referral campaigns for a business agent. "
            "Actions: create_campaign, generate_code, redeem, list, stats."
        ),
    )
    async def referral_program_tool(
        agent_handle: str,
        action: str,
        campaign_name: Optional[str] = None,
        reward_type: Optional[str] = None,
        reward_value: Optional[str] = None,
        referral_code: Optional[str] = None,
        referrer_id: Optional[str] = None,
        referee_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage referral programs for a business agent."""
        params: Dict[str, Any] = {}
        if campaign_name:
            params["campaign_name"] = campaign_name
        if reward_type:
            params["reward_type"] = reward_type
        if reward_value:
            params["reward_value"] = reward_value
        if referral_code:
            params["referral_code"] = referral_code
        if referrer_id:
            params["referrer_id"] = referrer_id
        if referee_id:
            params["referee_id"] = referee_id
        if campaign_id:
            params["id"] = campaign_id
        return await _run_skill("referral-program", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 10: manage_inventory
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="manage_inventory",
        description=(
            "Track products, stock levels, and inventory adjustments for a "
            "business agent. Actions: add_product, update_stock, list, get, "
            "low_stock, adjust."
        ),
    )
    async def manage_inventory(
        agent_handle: str,
        action: str,
        product_name: Optional[str] = None,
        sku: Optional[str] = None,
        quantity: Optional[int] = None,
        unit_price_cents: Optional[int] = None,
        category: Optional[str] = None,
        product_id: Optional[str] = None,
        adjustment_reason: Optional[str] = None,
        low_stock_threshold: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Manage inventory for a business agent."""
        params: Dict[str, Any] = {}
        if product_name:
            params["product_name"] = product_name
        if sku:
            params["sku"] = sku
        if quantity is not None:
            params["quantity"] = quantity
        if unit_price_cents is not None:
            params["unit_price_cents"] = unit_price_cents
        if category:
            params["category"] = category
        if product_id:
            params["id"] = product_id
        if adjustment_reason:
            params["reason"] = adjustment_reason
        if low_stock_threshold is not None:
            params["threshold"] = low_stock_threshold
        return await _run_skill("inventory", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 11: track_expenses
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="track_expenses",
        description=(
            "Record, categorize, and report on business expenses for an agent. "
            "Actions: record, list, get, categorize, report, delete."
        ),
    )
    async def track_expenses(
        agent_handle: str,
        action: str,
        amount_cents: Optional[int] = None,
        category: Optional[str] = None,
        vendor: Optional[str] = None,
        description: Optional[str] = None,
        date: Optional[str] = None,
        expense_id: Optional[str] = None,
        period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Track expenses for a business agent."""
        params: Dict[str, Any] = {}
        if amount_cents is not None:
            params["amount_cents"] = amount_cents
        if category:
            params["category"] = category
        if vendor:
            params["vendor"] = vendor
        if description:
            params["description"] = description
        if date:
            params["date"] = date
        if expense_id:
            params["id"] = expense_id
        if period:
            params["period"] = period
        return await _run_skill("expenses", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 12: business_operations
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="business_operations",
        description=(
            "Manage tasks, staff scheduling, and business metrics for an agent. "
            "Actions: create_task, list_tasks, update_task, schedule_staff, "
            "list_staff, metrics, dashboard."
        ),
    )
    async def business_operations_tool(
        agent_handle: str,
        action: str,
        task_title: Optional[str] = None,
        task_description: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
        task_id: Optional[str] = None,
        staff_name: Optional[str] = None,
        shift_start: Optional[str] = None,
        shift_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage business operations for an agent."""
        params: Dict[str, Any] = {}
        if task_title:
            params["title"] = task_title
        if task_description:
            params["description"] = task_description
        if assignee:
            params["assignee"] = assignee
        if due_date:
            params["due_date"] = due_date
        if priority:
            params["priority"] = priority
        if task_id:
            params["id"] = task_id
        if staff_name:
            params["staff_name"] = staff_name
        if shift_start:
            params["shift_start"] = shift_start
        if shift_end:
            params["shift_end"] = shift_end
        return await _run_skill("business-ops", agent_handle, action, params)

    # -----------------------------------------------------------------------
    # Tool 13: data_store
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="data_store",
        description=(
            "Key-value data storage for persisting agent state and custom data. "
            "Actions: set, get, delete, list, search."
        ),
    )
    async def data_store_tool(
        agent_handle: str,
        action: str,
        key: Optional[str] = None,
        value: Optional[str] = None,
        namespace: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manage key-value data for a business agent."""
        params: Dict[str, Any] = {}
        if key:
            params["key"] = key
        if value:
            params["value"] = value
        if namespace:
            params["namespace"] = namespace
        if prefix:
            params["prefix"] = prefix
        return await _run_skill("data-store", agent_handle, action, params)

    logger.info("Registered 13 business skill MCP tools")
