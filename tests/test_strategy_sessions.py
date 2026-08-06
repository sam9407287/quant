"""Session labelling and order-driven (OCO) entries — ADR-009.

The point of these tests is that an ICT-style killzone is expressible as
ordinary strategy modules, and that it composes with the indicator
filters rather than living in a separate engine. The conservatism rules
(SL wins a bar that touches both, gap-through fills at the open, an
unresolvable OCO tie stands the session down) are asserted here because
each of them is the difference between an honest backtest and a
flattering one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pandas as pd
import pytest
from pydantic import ValidationError

from app.strategies.engine import evaluate
from app.strategies.schemas import (
    Bracket,
    Condition,
    Operand,
    SessionSpec,
    StopEntry,
    StrategyDefinition,
)
from app.strategies.session import build_sessions, window_extreme

Row = tuple[str, float, float, float, float]  # ("HH:MM", open, high, low, close)


def bars(*days: tuple[str, list[Row]]) -> pd.DataFrame:
    """Readable OHLC fixture: ("2026-01-05", [("09:00", o,h,l,c), ...])."""
    recs = []
    for day, rows in days:
        for hhmm, o, h, low, c in rows:
            hh, mm = (int(x) for x in hhmm.split(":"))
            y, mo, d = (int(x) for x in day.split("-"))
            recs.append(
                {
                    "ts": datetime(y, mo, d, hh, mm, tzinfo=UTC),
                    "open": o, "high": h, "low": low, "close": c, "volume": 1000,
                }
            )
    return pd.DataFrame(recs)


def session(open_="09:00", close="16:00", tz="UTC") -> SessionSpec:
    oh, om = (int(x) for x in open_.split(":"))
    ch, cm = (int(x) for x in close.split(":"))
    return SessionSpec(tz=tz, open=time(oh, om), close=time(ch, cm))


def range_hi(start="09:00", end="10:00") -> Operand:
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    return Operand(kind="session_high", time_start=time(sh, sm), time_end=time(eh, em))


def range_lo(start="09:00", end="10:00") -> Operand:
    hi = range_hi(start, end)
    return Operand(kind="session_low", time_start=hi.time_start, time_end=hi.time_end)


def ict(**kw) -> StrategyDefinition:
    """The killzone shape: range 09:00–10:00, orders rest from 10:00."""
    entry = StopEntry(
        upper_level=range_hi(), lower_level=range_lo(),
        mode=kw.pop("mode", "breakout"),
        offset_mode=kw.pop("offset_mode", "points"),
        offset_value=kw.pop("offset_value", 0.0),
        active_from=kw.pop("active_from", time(10, 0)),
        oco=kw.pop("oco", True),
    )
    return StrategyDefinition(
        timeframe="1h", session=session(), stop_entry=entry, **kw
    )


# The range forms 09:00–10:00 with high 110 / low 90; nothing else touches it.
RANGE_DAY: list[Row] = [
    ("09:00", 100, 105, 95, 100),
    ("09:30", 100, 110, 90, 100),
]


class TestSessionLabelling:
    def test_bars_outside_the_session_are_excluded(self) -> None:
        df = bars(("2026-01-05", [("08:00", 1, 1, 1, 1), ("09:00", 1, 1, 1, 1),
                                  ("16:00", 1, 1, 1, 1)]))
        s = build_sessions(df["ts"], session())
        assert list(s.in_session) == [False, True, False]  # close is exclusive

    def test_session_is_named_for_the_day_it_opened(self) -> None:
        """An overnight session keeps one label across midnight."""
        df = bars(("2026-01-05", [("18:00", 1, 1, 1, 1), ("23:30", 1, 1, 1, 1)]),
                  ("2026-01-06", [("02:00", 1, 1, 1, 1), ("18:00", 1, 1, 1, 1)]))
        s = build_sessions(df["ts"], session("18:00", "17:00"))
        assert list(s.in_session) == [True, True, True, True]
        assert list(s.sid) == [date(2026, 1, 5)] * 3 + [date(2026, 1, 6)]

    def test_last_of_session_marks_the_final_in_session_bar(self) -> None:
        df = bars(("2026-01-05", [("09:00", 1, 1, 1, 1), ("15:30", 1, 1, 1, 1)]),
                  ("2026-01-06", [("09:00", 1, 1, 1, 1)]))
        s = build_sessions(df["ts"], session())
        assert list(s.last_of_session) == [False, True, True]

    def test_local_timezone_shifts_the_window(self) -> None:
        """09:00 New York is 14:00 UTC in January — the bars feed is UTC."""
        df = bars(("2026-01-05", [("13:59", 1, 1, 1, 1), ("14:00", 1, 1, 1, 1)]))
        s = build_sessions(df["ts"], session(tz="America/New_York"))
        assert list(s.in_session) == [False, True]


class TestWindowExtreme:
    def test_unreadable_until_the_window_closes(self) -> None:
        """The no-lookahead guarantee: a forming range has no value."""
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 101, 99, 100)]))
        s = build_sessions(df["ts"], session())
        hi = window_extreme(df, s, time(9, 0), time(10, 0), "high")
        assert pd.isna(hi.iat[0]) and pd.isna(hi.iat[1])
        assert hi.iat[2] == 110

    def test_each_session_measures_its_own_range(self) -> None:
        df = bars(
            ("2026-01-05", RANGE_DAY + [("10:00", 100, 101, 99, 100)]),
            ("2026-01-06", [("09:00", 200, 220, 180, 200), ("10:00", 200, 201, 199, 200)]),
        )
        s = build_sessions(df["ts"], session())
        lo = window_extreme(df, s, time(9, 0), time(10, 0), "low")
        assert lo.iat[2] == 90
        assert lo.iat[4] == 180

    def test_a_session_with_no_range_bars_stands_down(self) -> None:
        """Better no trade than a level borrowed from another day."""
        df = bars(("2026-01-05", [("11:00", 100, 101, 99, 100)]))
        s = build_sessions(df["ts"], session())
        hi = window_extreme(df, s, time(9, 0), time(10, 0), "high")
        assert pd.isna(hi.iat[0])


class TestSchemaGuards:
    def test_session_operand_without_a_session_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires the strategy to define a session"):
            StrategyDefinition(
                timeframe="1h",
                entry_long=Condition(op="gt", left=Operand(kind="price"), right=range_hi()),
            )

    def test_session_operand_needs_a_window(self) -> None:
        with pytest.raises(ValidationError, match="requires time_start and time_end"):
            Operand(kind="session_high")

    def test_stop_entry_needs_a_level(self) -> None:
        with pytest.raises(ValidationError, match="at least one of upper_level/lower_level"):
            StopEntry()

    def test_stop_entry_alone_is_a_valid_strategy(self) -> None:
        assert ict().entry_long is None  # no signal condition needed


class TestStopEntry:
    def test_breakout_fills_long_at_the_upper_level(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 99, 114)]))
        trades = evaluate(df, ict())
        assert len(trades) == 1
        assert trades[0].direction == "long"
        assert trades[0].entry_price == 110  # the level, not the bar's high

    def test_breakout_gapping_through_fills_at_the_open(self) -> None:
        """A stop order does not fill back at its level after a gap."""
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 118, 120, 117, 119)]))
        trades = evaluate(df, ict())
        assert trades[0].entry_price == 118

    def test_fade_sells_the_upper_break_at_the_level(self) -> None:
        """Limit orders fill at the level or better, so no gap adjustment."""
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 118, 120, 117, 119)]))
        trades = evaluate(df, ict(mode="fade"))
        assert trades[0].direction == "short"
        assert trades[0].entry_price == 110

    def test_offset_pushes_the_level_out(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 111, 99, 110)]))
        assert evaluate(df, ict(offset_value=2.0)) == []  # 111 never reaches 112
        hit = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 113, 99, 112)]))
        assert evaluate(hit, ict(offset_value=2.0))[0].entry_price == 112

    def test_orders_do_not_rest_before_the_activation_time(self) -> None:
        """A break during the range itself is not a signal."""
        df = bars(("2026-01-05", [
            ("09:00", 100, 105, 95, 100),
            ("09:30", 100, 110, 90, 100),
            ("09:45", 100, 130, 99, 129),   # blows through, still inside the range
        ]))
        assert evaluate(df, ict()) == []

    def test_no_fill_when_price_never_reaches_a_level(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 105, 95, 100)]))
        assert evaluate(df, ict()) == []


class TestOCO:
    def test_the_first_fill_cancels_the_other_side(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [
            ("10:00", 100, 115, 99, 114),   # takes the upper
            ("10:30", 100, 101, 80, 85),    # would have taken the lower
        ]))
        trades = evaluate(df, ict())
        assert len(trades) == 1
        assert trades[0].direction == "long"

    def test_without_oco_the_other_side_can_still_fill(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [
            ("10:00", 100, 115, 99, 114),   # long fills and takes profit
            ("10:30", 100, 101, 80, 85),    # the lower level is still live
        ]))
        trades = evaluate(df, ict(oco=False, tp=Bracket(mode="points", value=3)))
        assert [t.direction for t in trades] == ["long", "short"]

    def test_an_equidistant_tie_stands_the_session_down(self) -> None:
        """Both levels in one bar, no way to know which traded first."""
        df = bars(("2026-01-05", RANGE_DAY + [
            ("10:00", 100, 115, 85, 100),   # open is exactly between 110 and 90
            ("10:30", 100, 120, 99, 119),   # a clean break afterwards
        ]))
        assert evaluate(df, ict()) == []

    def test_a_resolvable_straddle_picks_the_nearer_level(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 108, 115, 85, 100)]))
        trades = evaluate(df, ict())
        assert len(trades) == 1
        assert trades[0].direction == "long"  # open 108 is nearer 110 than 90

    def test_the_stand_down_lasts_only_that_session(self) -> None:
        df = bars(
            ("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 85, 100)]),
            ("2026-01-06", RANGE_DAY + [("10:00", 100, 115, 99, 114)]),
        )
        trades = evaluate(df, ict())
        assert len(trades) == 1
        assert trades[0].entry_ts.date() == date(2026, 1, 6)


class TestSessionLifecycle:
    def test_a_position_is_flattened_at_the_session_close(self) -> None:
        df = bars(
            ("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 99, 114), ("15:30", 114, 116, 113, 115)]),
            ("2026-01-06", [("09:00", 200, 201, 199, 200)]),
        )
        trades = evaluate(df, ict())
        assert len(trades) == 1
        assert trades[0].exit_reason == "eod"
        assert trades[0].exit_price == 115  # the last in-session bar's close

    def test_max_trades_per_session_caps_re_entry(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [
            ("10:00", 100, 115, 99, 114),
            ("10:30", 100, 101, 80, 85),
            ("11:00", 85, 86, 84, 85),
            ("11:30", 85, 120, 84, 119),
        ]))
        defn = ict(oco=False, max_trades_per_session=1, tp=Bracket(mode="points", value=3))
        assert len(evaluate(df, defn)) == 1

    def test_the_cap_resets_next_session(self) -> None:
        df = bars(
            ("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 99, 114)]),
            ("2026-01-06", RANGE_DAY + [("10:00", 100, 115, 99, 114)]),
        )
        assert len(evaluate(df, ict(max_trades_per_session=1))) == 2


class TestBracketsOnStopEntries:
    def test_the_entry_bar_can_stop_the_trade_out(self) -> None:
        """Excluding the entry bar's range would skip same-bar stops."""
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 100, 101)]))
        trades = evaluate(df, ict(sl=Bracket(mode="points", value=5)))
        assert trades[0].exit_reason == "sl"
        assert trades[0].exit_price == 105

    def test_a_bar_touching_both_books_the_loss(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 130, 100, 129)]))
        defn = ict(sl=Bracket(mode="points", value=5), tp=Bracket(mode="points", value=10))
        assert evaluate(df, defn)[0].exit_reason == "sl"


class TestComposesWithFilters:
    """The reason this work exists: killzone modules and indicator
    modules in one strategy, one engine, one position."""

    def test_a_filter_can_suppress_the_resting_orders(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 99, 114)]))
        blocked = ict(filters=[Condition(
            op="gt", left=Operand(kind="price"), right=Operand(kind="const", value=1e6)
        )])
        assert evaluate(df, blocked) == []

    def test_a_passing_filter_leaves_the_setup_intact(self) -> None:
        df = bars(("2026-01-05", RANGE_DAY + [("10:00", 100, 115, 99, 114)]))
        allowed = ict(filters=[Condition(
            op="gt", left=Operand(kind="price"), right=Operand(kind="const", value=0)
        )])
        assert len(evaluate(df, allowed)) == 1

    def test_the_filter_is_read_at_the_previous_close(self) -> None:
        """Using the fill bar's own close to authorise the fill is lookahead."""
        df = bars(("2026-01-05", RANGE_DAY + [
            ("10:00", 100, 115, 99, 50),    # closes below 60 — gate shuts here
            ("10:30", 50, 120, 49, 119),    # so this bar's orders are suppressed
        ]))
        defn = ict(filters=[Condition(
            op="gt", left=Operand(kind="price"), right=Operand(kind="const", value=60)
        )])
        trades = evaluate(df, defn)
        assert len(trades) == 1
        assert trades[0].entry_ts.hour == 10 and trades[0].entry_ts.minute == 0
