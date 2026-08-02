"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import backtest, coverage, kbars, ml, roll_calendar, strategies
from app.core.config import get_settings

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup and shutdown hooks."""
    # Nothing to initialise yet; DB connections are created per-request.
    yield


app = FastAPI(
    title="Quant Futures API",
    description=(
        "OHLCV data and analytics for CME index futures "
        "(NQ, ES, YM, RTY)."
    ),
    version="0.5.0",
    lifespan=lifespan,
    # In production the interactive docs and OpenAPI schema are hidden —
    # they enumerate every endpoint and shape of a non-public app.
    docs_url=None if _settings.is_production else "/docs",
    redoc_url=None if _settings.is_production else "/redoc",
    openapi_url=None if _settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    # PUT/DELETE are needed for /api/v1/strategies; OPTIONS is the preflight.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach baseline security headers to every response.

    Railway terminates TLS at the edge, but HSTS instructs browsers to
    stay on HTTPS; the rest block MIME-sniffing, clickjacking and
    referrer leakage. The API serves only JSON, so a strict frame-deny
    and no-referrer are safe.
    """
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

app.include_router(kbars.router)
app.include_router(coverage.router)
app.include_router(roll_calendar.router)
app.include_router(ml.router)
app.include_router(backtest.router)
app.include_router(strategies.router)


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok", "version": app.version}
