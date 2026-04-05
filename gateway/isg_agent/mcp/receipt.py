"""SHA-256 hash-chain receipt builder for DingDawg Agent 1 MCP tools.

Every MCP tool call produces an ``MCPReceipt`` that:

1.  Hashes its canonical inputs  (SHA-256 of sorted-key JSON).
2.  Hashes its canonical outputs (SHA-256 of sorted-key JSON).
3.  Chains from the previous receipt hash (or 64 zeros for genesis).
4.  Produces a self-binding ``receipt_hash`` over all of the above.

The chain makes retrospective tampering detectable: changing *any* receipt
invalidates every subsequent receipt's ``prev_receipt_hash``.

Usage
-----
::

    from isg_agent.mcp.receipt import build_receipt

    receipt = build_receipt(
        tool_name="agent_create",
        agent_handle="my-agent",
        inputs={"user_id": "u1", "handle": "my-agent", ...},
        outputs={"agent_id": "abc", "status": "active", ...},
        prev_hash="0" * 64,   # genesis; omit for first call
    )
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from isg_agent.mcp.models import MCPReceipt

__all__ = ["build_receipt", "GENESIS_HASH"]

# Sentinel for the first receipt in a chain (no previous receipt).
GENESIS_HASH: str = "0" * 64

# Base URL for public receipt verification endpoint.
_VERIFY_BASE_URL: str = "https://agent1.dingdawg.com/receipts"


def _canonical_hash(data: Any) -> str:
    """Return the SHA-256 hex digest of the canonical JSON encoding of *data*.

    Canonical means:
    - ``sort_keys=True`` so key ordering is deterministic.
    - ``ensure_ascii=True`` (default) for consistent byte representation.
    - No extra whitespace (``separators=(",", ":")``) for compactness.

    Parameters
    ----------
    data:
        Any JSON-serialisable Python object.

    Returns
    -------
    str
        64-character lowercase hex SHA-256 digest.
    """
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_receipt(
    tool_name: str,
    agent_handle: str,
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    prev_hash: str = GENESIS_HASH,
) -> MCPReceipt:
    """Build a tamper-evident hash-chain receipt for one MCP tool invocation.

    Parameters
    ----------
    tool_name:
        Name of the MCP tool that was called (e.g. ``"agent_create"``).
    agent_handle:
        The @handle of the agent targeted by the tool call.  Use an empty
        string or ``"system"`` when no specific agent is targeted.
    inputs:
        Plain-dict representation of the tool inputs (must be JSON-safe).
    outputs:
        Plain-dict representation of the tool outputs (must be JSON-safe).
    prev_hash:
        The ``receipt_hash`` of the previous receipt in the chain.  Pass
        ``GENESIS_HASH`` (``"0" * 64``) for the very first receipt.

    Returns
    -------
    MCPReceipt
        Fully populated receipt ready to attach to a tool response.

    Notes
    -----
    The ``receipt_hash`` binds the entire receipt in one digest::

        receipt_hash = SHA-256(
            audit_id || tool_name || agent_handle || timestamp ||
            input_hash || output_hash || prev_receipt_hash
        )

    This means every field (including the chain link) is covered by the
    self-hash, making selective field mutation detectable.
    """
    audit_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    input_hash = _canonical_hash(inputs)
    output_hash = _canonical_hash(outputs)

    # Self-binding hash — covers all receipt fields so nothing can be changed
    # without invalidating the receipt_hash itself.
    binding_payload = {
        "audit_id": audit_id,
        "tool_name": tool_name,
        "agent_handle": agent_handle,
        "timestamp": timestamp,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "prev_receipt_hash": prev_hash,
    }
    receipt_hash = _canonical_hash(binding_payload)

    verify_url = f"{_VERIFY_BASE_URL}/{audit_id}"

    return MCPReceipt(
        audit_id=audit_id,
        tool_name=tool_name,
        agent_handle=agent_handle,
        timestamp=timestamp,
        input_hash=input_hash,
        output_hash=output_hash,
        prev_receipt_hash=prev_hash,
        receipt_hash=receipt_hash,
        verify_url=verify_url,
    )
