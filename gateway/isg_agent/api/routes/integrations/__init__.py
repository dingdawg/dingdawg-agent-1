"""Per-agent integration sub-modules.

This package replaces the old ``integrations.py`` flat file.  The DDMain
bridge router (previously the sole content of ``integrations.py``) is
re-exported here so that ``app.py`` can continue to import it unchanged:

    from isg_agent.api.routes.integrations import router as integrations_router

The notify-integrations sub-modules (email, sms, vapi, google_calendar,
status, management) are internal implementation details consumed only by
``notify_integrations.py``.
"""

from isg_agent.api.routes.integrations._ddmain import router

__all__ = ["router"]
