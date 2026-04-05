"""Entry point for running ISG Agent 1 gateway.

Usage:
    python -m isg_agent
    isg-agent  (if installed via pip)
"""

from __future__ import annotations

import sys


def main() -> None:
    """Launch the ISG Agent 1 gateway server."""
    try:
        import uvicorn

        from isg_agent.config import get_settings

        settings = get_settings()

        uvicorn.run(
            "isg_agent.app:create_app",
            factory=True,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            reload=False,
        )
    except KeyboardInterrupt:
        print("\nISG Agent 1 gateway shutting down.")
        sys.exit(0)
    except ImportError as exc:
        print(f"Missing dependency: {exc}", file=sys.stderr)
        print("Run: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
