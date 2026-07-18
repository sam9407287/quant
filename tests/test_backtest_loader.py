"""Unit tests for the pure parts of the session loader (ADR-003 B2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from app.backtest.loader import group_sessions, session_atr
from app.backtest.params import BacktestParams, SessionClock
from app.backtest.types import Bar

NY = ZoneInfo("America/New_York")

PARAMS = BacktestParams(
    start=date(2026, 7, 6),
    end=date(2026, 7, 10),
    clock=SessionClock(
        range_start=dtime(9, 0),
        range_end=dtime(9, 30),
        orders_place=dtime(9, 30),
        eod_flat=dtime(16, 0),
    ),
)


def ny_bar(d: date, hhmm: str, px: float = 100.0) -> Bar:
    hh, mm = (int(p) for p in hhmm.split(":"))
    ts = datetime.combine(d, dtime(hh, mm), tzinfo=NY).astimezone(UTC)
    return Bar(ts=ts, open=px, high=px + 1, low=px - 1, close=px)


class TestGroupSessions:
    def test_daytime_bars_stay_on_their_date(self) -> None:
        bars = [ny_bar(date(2026, 7, 6), "09:00"), ny_bar(date(2026, 7, 6), "15:59")]
        sessions = group_sessions(bars, PARAMS)
        assert [d for d, _ in sessions] == [date(2026, 7, 6)]
        assert len(sessions[0][1]) == 2

    def test_bars_at_or_after_eod_roll_to_next_session(self) -> None:
        # 16:00 and a 20:00 evening range bar both seed the NEXT day.
        bars = [
            ny_bar(date(2026, 7, 6), "15:59"),
            ny_bar(date(2026, 7, 6), "16:00"),
            ny_bar(date(2026, 7, 6), "20:00"),
            ny_bar(date(2026, 7, 7), "09:30"),
        ]
        sessions = dict(group_sessions(bars, PARAMS))
        assert len(sessions[date(2026, 7, 6)]) == 1
        assert len(sessions[date(2026, 7, 7)]) == 3

    def test_sessions_sorted_by_date(self) -> None:
        bars = [ny_bar(date(2026, 7, 8), "10:00"), ny_bar(date(2026, 7, 6), "10:00")]
        sessions = group_sessions(bars, PARAMS)
        assert [d for d, _ in sessions] == [date(2026, 7, 6), date(2026, 7, 8)]


class TestSessionAtr:
    @staticmethod
    def _session(d: date, high: float, low: float, close: float) -> tuple[date, list[Bar]]:
        # One synthetic bar carrying the session's aggregate OHLC.
        ts = datetime.combine(d, dtime(10, 0), tzinfo=NY).astimezone(UTC)
        return (d, [Bar(ts=ts, open=close, high=high, low=low, close=close)])

    def test_warmup_and_no_lookahead(self) -> None:
        sessions = [
            self._session(date(2026, 7, 6), high=110, low=100, close=105),  # TR = 10
            self._session(date(2026, 7, 7), high=112, low=104, close=110),  # TR = 8
            self._session(date(2026, 7, 8), high=130, low=110, close=120),  # TR = 20
        ]
        atr = session_atr(sessions, period=2)
        # First two sessions are warm-up; the third sees mean(10, 8) — its
        # own huge TR of 20 must NOT leak into its own ATR.
        assert set(atr) == {date(2026, 7, 8)}
        assert atr[date(2026, 7, 8)] == 9.0

    def test_gap_uses_prev_close_in_true_range(self) -> None:
        sessions = [
            self._session(date(2026, 7, 6), high=110, low=100, close=105),  # TR = 10
            # Gapped down: TR = max(2, |92-105|, |90-105|) = 15
            self._session(date(2026, 7, 7), high=92, low=90, close=91),
            self._session(date(2026, 7, 8), high=95, low=90, close=94),
        ]
        atr = session_atr(sessions, period=2)
        assert atr[date(2026, 7, 8)] == 12.5  # mean(10, 15)

    def test_empty_input(self) -> None:
        assert session_atr([], period=14) == {}
