"""Backtest orchestration: many sessions in, one DayResult per session out.

The engine stays pure — sessions arrive as already-grouped bar
sequences (the DB→session grouping lives in the loader, ADR-003 B2) so
every code path here is reachable from unit tests without a database.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from app.backtest.params import BacktestParams
from app.backtest.strategies.killzone_oco import run_session
from app.backtest.types import Bar, DayResult

__all__ = ["Bar", "DayResult", "run_backtest"]


def run_backtest(
    sessions: Iterable[tuple[date, Sequence[Bar]]],
    params: BacktestParams,
    atr_by_date: Mapping[date, float] | None = None,
) -> list[DayResult]:
    """Run every session through the strategy; results keep input order."""
    if params.uses_atr and atr_by_date is None:
        raise ValueError("params use ATR mode but no atr_by_date was provided")

    results: list[DayResult] = []
    for session_date, bars in sessions:
        if any(bars[i].ts >= bars[i + 1].ts for i in range(len(bars) - 1)):
            raise ValueError(f"bars for {session_date} are not strictly sorted by ts")
        atr = atr_by_date.get(session_date) if atr_by_date is not None else None
        if params.uses_atr and atr is None:
            # A missing ATR (e.g. warm-up window) is a data condition,
            # not a crash: record the session as unplayable.
            results.append(DayResult(session_date=session_date, exit_reason="no_data"))
            continue
        results.append(run_session(session_date, bars, params, atr=atr))
    return results
