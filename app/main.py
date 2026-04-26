"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import coverage, kbars, roll_calendar
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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(kbars.router)
app.include_router(coverage.router)
app.include_router(roll_calendar.router)


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok", "version": app.version}
