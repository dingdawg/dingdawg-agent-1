from __future__ import annotations

from typing import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


class CORSConfigError(Exception):
    """Raised when CORS configuration is invalid."""


def configure_cors(
    app: FastAPI,
    *,
    allowed_origins: Sequence[str] | None = None,
    allow_credentials: bool = True,
    allowed_methods: Sequence[str] | None = None,
    allowed_headers: Sequence[str] | None = None,
    max_age: int = 600,
) -> FastAPI:
    """Attach CORS middleware configured for a Next.js frontend."""

    if not isinstance(app, FastAPI):
        raise TypeError(
            f"app must be a FastAPI instance, got {type(app).__name__}."
        )

    if max_age < 0:
        raise CORSConfigError("max_age must be non-negative.")

    origins: list[str] = list(allowed_origins) if allowed_origins else [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    for origin in origins:
        if origin == "*" and allow_credentials:
            raise CORSConfigError(
                "Cannot use wildcard origin ('*') with allow_credentials=True. "
                "Browsers will reject the response."
            )
        if not origin.startswith(("http://", "https://", "*")):
            raise CORSConfigError(
                f"Invalid origin '{origin}': must start with http:// or https://."
            )

    methods: list[str] = list(allowed_methods) if allowed_methods else [
        "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
    ]

    headers: list[str] = list(allowed_headers) if allowed_headers else [
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Requested-With",
        "X-CSRF-Token",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=methods,
        allow_headers=headers,
        max_age=max_age,
    )

    return app


def create_app(
    *,
    title: str = "API",
    allowed_origins: Sequence[str] | None = None,
) -> FastAPI:
    """Create a FastAPI app with CORS pre-configured for Next.js."""

    app = FastAPI(title=title)

    try:
        configure_cors(app, allowed_origins=allowed_origins)
    except CORSConfigError as exc:
        raise CORSConfigError(
            f"Failed to initialize CORS for '{title}': {exc}"
        ) from exc

    @app.options("/{full_path:path}")
    async def preflight_handler(full_path: str) -> dict[str, str]:
        """Explicit OPTIONS fallback for preflight requests."""
        return {"status": "ok"}

    return app


# --- Next.js side: next.config.js rewrites (reference) ---
#
# async rewrites() {
#   return [
#     {
#       source: "/api/:path*",
#       destination: "http://127.0.0.1:8000/api/:path*",
#     },
#   ];
# }