"""Daily-bar data layer for the pairs lab: fetch, check, store, align.

Why a second price table instead of `kbars_1d`: that continuous aggregate
buckets 1m bars at UTC midnight, which slices a CME session in half and
only reaches back to when 1m collection began (2026-04). Cointegration
tests need years of settlement-aligned daily closes, which yfinance
serves for free at `interval=1d`. The two stores never mix.

Pure helpers (normalisation, quality checks, alignment) take and return
DataFrames so they are unit-testable without a database or network; the
async functions are thin SQL shells around them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pairs.universe import UNIVERSE, price_field_for, registry_symbol_for

logger = logging.getLogger(__name__)

DAILY_COLUMNS: tuple[str, ...] = (
    "ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume",
)

# A single-day log move beyond this is flagged (not dropped): it is either
# a data error or a roll gap, and both must be visible in the UI.
EXTREME_LOG_MOVE = 0.25

Downloader = Callable[..., pd.DataFrame]


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One data-quality finding, kept for the job log and the dashboard."""

    ticker: str
    trading_date: date | None
    kind: str  # non_positive | duplicate | future_date | extreme_move | missing_close
    detail: str


# ---------------------------------------------------------------------------
# Fetch + normalise
# ---------------------------------------------------------------------------

def _default_downloader() -> Downloader:
    import yfinance as yf

    return yf.download  # type: ignore[no-any-return]


def normalise_download(raw: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
    """Flatten a yfinance batch download into the long DAILY_COLUMNS shape.

    yfinance returns flat columns for one ticker and a two-level column
    index for several; with `group_by="ticker"` the first level is the
    ticker. Rows without a close are dropped (holiday padding), and the
    index is reduced to a calendar date because daily bars carry no useful
    time-of-day.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    frames: list[pd.DataFrame] = []
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        for ticker in tickers:
            if ticker not in level0:
                continue
            frames.append(_one_ticker_frame(raw[ticker], ticker))
    else:
        if len(tickers) != 1:
            raise ValueError("flat yfinance columns but more than one ticker requested")
        frames.append(_one_ticker_frame(raw, tickers[0]))

    if not frames:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    return out[list(DAILY_COLUMNS)].sort_values(["ticker", "trading_date"]).reset_index(drop=True)


def _one_ticker_frame(block: pd.DataFrame, ticker: str) -> pd.DataFrame:
    df = block.copy()
    df.columns = [str(c) for c in df.columns]
    rename = {
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Adj Close": "adj_close", "Volume": "volume",
    }
    df = df.rename(columns=rename)
    if "close" not in df.columns:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]
    for col in ("open", "high", "low", "volume"):
        if col not in df.columns:
            df[col] = np.nan
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df["trading_date"] = [d.date() for d in idx]
    df["ticker"] = ticker
    df = df.dropna(subset=["close"])
    df["adj_close"] = df["adj_close"].fillna(df["close"])
    return df[list(DAILY_COLUMNS)]


def fetch_daily_history(
    tickers: Sequence[str],
    start: date,
    end: date,
    downloader: Downloader | None = None,
) -> pd.DataFrame:
    """Download daily OHLCV for many tickers in one vendor call.

    `end` is inclusive here; yfinance treats its `end` as exclusive, so a
    day is added. `auto_adjust=False` keeps both the raw and the adjusted
    close, which the futures/ETF split in `price_field_for` relies on.
    """
    if not tickers:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    download = downloader or _default_downloader()
    raw = download(
        tickers=list(tickers),
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    return normalise_download(raw, tickers)


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

def quality_check(
    df: pd.DataFrame,
    *,
    today: date | None = None,
    extreme_log_move: float = EXTREME_LOG_MOVE,
) -> tuple[pd.DataFrame, list[QualityIssue]]:
    """Drop rows that cannot be real; flag rows that merely look suspicious.

    Dropped: non-positive prices, duplicate (ticker, date), dates after
    today. Flagged only: a close-to-close log move beyond the threshold —
    for a futures front-month series that is usually a roll gap, and the
    scan needs to know about it rather than lose the day.
    """
    issues: list[QualityIssue] = []
    if df.empty:
        return df, issues
    today = today or datetime.now(UTC).date()
    work = df.copy()

    bad_price = (work["close"] <= 0) | (work["adj_close"] <= 0)
    for _, row in work[bad_price].iterrows():
        issues.append(QualityIssue(row["ticker"], row["trading_date"], "non_positive",
                                   f"close={row['close']}"))
    work = work[~bad_price]

    future = work["trading_date"] > today
    for _, row in work[future].iterrows():
        issues.append(QualityIssue(row["ticker"], row["trading_date"], "future_date",
                                   f"after {today}"))
    work = work[~future]

    dup = work.duplicated(subset=["ticker", "trading_date"], keep="first")
    for _, row in work[dup].iterrows():
        issues.append(QualityIssue(row["ticker"], row["trading_date"], "duplicate", "dropped"))
    work = work[~dup]

    work = work.sort_values(["ticker", "trading_date"]).reset_index(drop=True)
    log_ret = np.log(work["close"]).groupby(work["ticker"]).diff()
    for i in np.flatnonzero(log_ret.abs() > extreme_log_move):
        row = work.iloc[i]
        issues.append(QualityIssue(row["ticker"], row["trading_date"], "extreme_move",
                                   f"log move {log_ret.iloc[i]:+.3f}"))
    return work, issues


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_UPSERT_CHUNK = 2000


async def upsert_daily_bars(session: AsyncSession, df: pd.DataFrame, source: str = "yfinance") -> int:
    """Insert or refresh daily bars in chunks; returns rows written.

    Updates on conflict (not DO NOTHING): vendors revise settlement prices
    for a day or two, and a stale close would poison the spread.
    """
    if df.empty:
        return 0
    stmt = text(
        """
        INSERT INTO pairs_daily_bars
            (ticker, trading_date, open, high, low, close, adj_close, volume, source, fetched_at)
        VALUES
            (:ticker, :trading_date, :open, :high, :low, :close, :adj_close, :volume, :source, NOW())
        ON CONFLICT (ticker, trading_date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, adj_close = EXCLUDED.adj_close,
            volume = EXCLUDED.volume, source = EXCLUDED.source, fetched_at = NOW()
        """
    )
    rows = [
        {
            "ticker": r.ticker,
            "trading_date": r.trading_date,
            "open": _float_or_none(r.open),
            "high": _float_or_none(r.high),
            "low": _float_or_none(r.low),
            "close": float(r.close),
            "adj_close": float(r.adj_close),
            "volume": _int_or_none(r.volume),
            "source": source,
        }
        for r in df.itertuples(index=False)
    ]
    for i in range(0, len(rows), _UPSERT_CHUNK):
        await session.execute(stmt, rows[i : i + _UPSERT_CHUNK])
    await session.commit()
    return len(rows)


def _float_or_none(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def _int_or_none(v: Any) -> int | None:
    f = _float_or_none(v)
    return None if f is None else int(f)


async def load_wide_prices(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Date × ticker price matrix using each instrument's proper price field."""
    if not tickers:
        return pd.DataFrame()
    stmt = text(
        """
        SELECT ticker, trading_date, close, adj_close
        FROM pairs_daily_bars
        WHERE ticker IN :tickers
          AND (:start IS NULL OR trading_date >= :start)
          AND (:end IS NULL OR trading_date <= :end)
        ORDER BY trading_date
        """
    ).bindparams(bindparam("tickers", expanding=True))
    rows = (await session.execute(stmt, {"tickers": list(tickers), "start": start, "end": end})).fetchall()
    if not rows:
        return pd.DataFrame(columns=list(tickers))
    frame = pd.DataFrame(rows, columns=["ticker", "trading_date", "close", "adj_close"])
    frame["price"] = np.where(
        frame["ticker"].map(lambda t: price_field_for(t) if t in UNIVERSE else "close") == "adj_close",
        frame["adj_close"],
        frame["close"],
    )
    wide = frame.pivot(index="trading_date", columns="ticker", values="price").sort_index()
    wide.index = pd.to_datetime(wide.index)
    return wide.reindex(columns=[t for t in tickers if t in wide.columns])


async def daily_coverage(session: AsyncSession) -> list[dict[str, Any]]:
    """Per-ticker first/last date and bar count for the dashboard."""
    stmt = text(
        """
        SELECT ticker, MIN(trading_date) AS first_date, MAX(trading_date) AS last_date,
               COUNT(*) AS bar_count, MAX(fetched_at) AS last_fetch
        FROM pairs_daily_bars
        GROUP BY ticker
        ORDER BY ticker
        """
    )
    rows = (await session.execute(stmt)).fetchall()
    return [dict(r._mapping) for r in rows]


async def latest_trading_date(session: AsyncSession, tickers: Sequence[str]) -> date | None:
    """Most recent date on which *every* requested ticker has a bar."""
    if not tickers:
        return None
    stmt = text(
        """
        SELECT trading_date
        FROM pairs_daily_bars
        WHERE ticker IN :tickers
        GROUP BY trading_date
        HAVING COUNT(DISTINCT ticker) = :n
        ORDER BY trading_date DESC
        LIMIT 1
        """
    ).bindparams(bindparam("tickers", expanding=True))
    row = (await session.execute(stmt, {"tickers": list(tickers), "n": len(set(tickers))})).first()
    return None if row is None else row[0]


async def equity_roll_dates(session: AsyncSession, ticker: str) -> list[date]:
    """Roll dates from `roll_calendar` for tickers backed by a registry symbol."""
    symbol = registry_symbol_for(ticker)
    if symbol is None:
        return []
    stmt = text("SELECT roll_date FROM roll_calendar WHERE instrument = :sym ORDER BY roll_date")
    rows = (await session.execute(stmt, {"sym": symbol})).fetchall()
    return [r[0] for r in rows]


async def snapshot_prices_from_1m(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    at_et: str,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Date × ticker matrix of prices struck at one New York wall-clock time.

    Cross-group pairs settle at different times (gold 13:30 ET, S&P 16:00
    ET); a spread built from settlements mixes two moments. The 1m store
    lets every leg be read at the same instant instead. Limited to tickers
    that map to a registry symbol and to the span the 1m collection covers.
    """
    symbols = {t: registry_symbol_for(t) for t in tickers}
    wanted = {s: t for t, s in symbols.items() if s is not None}
    if not wanted:
        return pd.DataFrame()
    hh, mm = (int(p) for p in at_et.split(":"))
    stmt = text(
        """
        SELECT instrument,
               (ts AT TIME ZONE 'America/New_York')::date AS d,
               open::float AS price
        FROM kbars_1m
        WHERE instrument IN :syms
          AND EXTRACT(HOUR FROM (ts AT TIME ZONE 'America/New_York')) = :hh
          AND EXTRACT(MINUTE FROM (ts AT TIME ZONE 'America/New_York')) = :mm
          AND (:start IS NULL OR ts >= :start)
          AND (:end IS NULL OR ts < :end)
        ORDER BY d
        """
    ).bindparams(bindparam("syms", expanding=True))
    ny = ZoneInfo("America/New_York")
    params = {
        "syms": list(wanted),
        "hh": hh,
        "mm": mm,
        "start": None if start is None else datetime.combine(start, datetime.min.time(), tzinfo=ny),
        "end": None if end is None else datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=ny),
    }
    rows = (await session.execute(stmt, params)).fetchall()
    if not rows:
        return pd.DataFrame(columns=list(wanted.values()))
    frame = pd.DataFrame(rows, columns=["instrument", "d", "price"])
    frame["ticker"] = frame["instrument"].map(wanted)
    wide = frame.pivot(index="d", columns="ticker", values="price").sort_index()
    wide.index = pd.to_datetime(wide.index)
    return wide


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def align_pair(wide: pd.DataFrame, y: str, x: str, *, max_ffill: int = 1) -> pd.DataFrame:
    """Two-column frame on the common trading days with bounded forward fill.

    A one-day fill bridges an exchange holiday on one leg; anything longer
    is a real hole and the day is dropped rather than invented.
    """
    if y not in wide.columns or x not in wide.columns:
        return pd.DataFrame(columns=[y, x])
    pair = wide[[y, x]].copy()
    if max_ffill > 0:
        pair = pair.ffill(limit=max_ffill)
    return pair.dropna()


def log_price_matrix(wide: pd.DataFrame, *, max_ffill: int = 1, min_rows: int = 0) -> pd.DataFrame:
    """log(price) matrix with bounded fill; drops columns too short to use."""
    if wide.empty:
        return wide
    filled = wide.ffill(limit=max_ffill) if max_ffill > 0 else wide
    logged = np.log(filled.where(filled > 0))
    if min_rows:
        keep = [c for c in logged.columns if logged[c].notna().sum() >= min_rows]
        logged = logged[keep]
    return logged
