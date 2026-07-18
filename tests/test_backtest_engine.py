"""Unit tests for the killzone-OCO backtest engine (ADR-003 B1).

Synthetic 1m bars pin every decision rule: OCO single-entry, the
pessimistic SL-first tie rule, EOD forced flat, offset/stop modes, and
the ambiguous both-levels bar. No DB, no fixtures beyond hand-built
bars — if these tests need I/O the engine has lost its purity.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.backtest.engine import run_backtest
from app.backtest.params import BacktestParams, SessionClock
from app.backtest.strategies.killzone_oco import _in_window, run_session
from app.backtest.types import Bar

NY = ZoneInfo("America/New_York")
DAY = date(2026, 7, 6)  # a Monday


def bar(hhmm: str, o: float, h: float, low: float, c: float) -> Bar:
    hh, mm = (int(p) for p in hhmm.split(":"))
    ts = datetime.combine(DAY, dtime(hh, mm), tzinfo=NY).astimezone(UTC)
    return Bar(ts=ts, open=o, high=h, low=low, close=c)


def make_params(**overrides: object) -> BacktestParams:
    base: dict[str, object] = {
        "start": DAY,
        "end": DAY,
        "clock": SessionClock(
            range_start=dtime(9, 0),
            range_end=dtime(9, 30),
            orders_place=dtime(9, 30),
            eod_flat=dtime(16, 0),
        ),
        "sl_mode": "points",
        "sl_value": 5.0,
        "rrr": 2.0,
        "entry_offset_mode": "points",
        "entry_offset_value": 0.0,
    }
    base.update(overrides)
    return BacktestParams(**base)  # type: ignore[arg-type]


# Range bars 09:00–09:29 → high 100, low 90.
RANGE_BARS = [bar("09:00", 95, 100, 90, 95), bar("09:15", 95, 98, 92, 96)]


class TestFadeEntriesAndExits:
    def test_short_at_range_high_exits_at_take_profit(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),      # touches upper → short @100
            bar("09:31", 99, 99, 89.5, 91),     # low ≤ tp level 90 → TP
            bar("09:32", 91, 92, 89, 90),       # would touch lower entry — must be ignored (OCO)
        ]
        result = run_session(DAY, bars, make_params())
        assert result.direction == "short"
        assert result.exit_reason == "tp"
        assert result.entry_price == 100.0
        assert result.exit_price == 90.0  # tp = sl 5 × rrr 2 below entry
        assert result.pnl_points == pytest.approx(10.0)
        assert result.pnl_usd == pytest.approx(20.0)  # MNQ $2/pt × 1 contract
        assert result.range_high == 100.0
        assert result.range_low == 90.0

    def test_long_at_range_low(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 92, 93, 90, 91),        # touches lower → long @90
            bar("09:31", 91, 100.5, 91, 100),    # high ≥ tp level 100 → TP
        ]
        result = run_session(DAY, bars, make_params())
        assert result.direction == "long"
        assert result.exit_reason == "tp"
        assert result.pnl_points == pytest.approx(10.0)

    def test_stop_loss(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),       # short @100, sl level 105
            bar("09:31", 101, 105.5, 100, 105),  # high ≥ 105 → SL
        ]
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "sl"
        assert result.exit_price == 105.0
        assert result.pnl_points == pytest.approx(-5.0)
        assert result.pnl_usd == pytest.approx(-10.0)

    def test_bar_touching_sl_and_tp_books_as_sl(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),        # short @100
            bar("09:31", 99, 106, 89, 95),        # touches 105 AND 90 → pessimistic SL
        ]
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "sl"

    def test_eod_forced_flat(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),       # short @100
            bar("12:00", 99, 101, 97, 98.5),     # drifts, no level hit
            bar("15:59", 98, 99, 97, 97.5),      # last bar before eod_flat
            bar("16:00", 97, 98, 96, 96.5),      # outside window — ignored
        ]
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "eod"
        assert result.exit_price == 97.5  # close of last in-window bar
        assert result.pnl_points == pytest.approx(2.5)

    def test_no_fill(self) -> None:
        bars = RANGE_BARS + [bar("09:30", 95, 99, 91, 95), bar("10:00", 95, 98, 92, 94)]
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "no_fill"
        assert result.pnl_usd == 0.0

    def test_no_range_data(self) -> None:
        result = run_session(DAY, [bar("10:00", 95, 98, 92, 94)], make_params())
        assert result.exit_reason == "no_data"


class TestDirectionAndOffsets:
    def test_breakout_mode_goes_long_at_upper(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),        # touches upper → LONG in breakout
            bar("09:31", 100, 110.5, 100, 110),   # tp level 110 hit
        ]
        result = run_session(DAY, bars, make_params(direction_mode="breakout"))
        assert result.direction == "long"
        assert result.exit_reason == "tp"

    def test_pct_offset_moves_levels_beyond_range(self) -> None:
        params = make_params(entry_offset_mode="pct", entry_offset_value=1.0)
        bars = RANGE_BARS + [
            bar("09:30", 98, 100.5, 97, 99),      # upper is 101 → no fill yet
            bar("09:31", 99, 101.0, 98, 100),     # fills short @101
        ]
        result = run_session(DAY, bars, params)
        assert result.direction == "short"
        assert result.entry_price == pytest.approx(101.0)

    def test_negative_offset_pulls_levels_inside_range(self) -> None:
        params = make_params(entry_offset_value=-2.0)  # upper 98, lower 92
        bars = RANGE_BARS + [bar("09:30", 95, 98.0, 94, 96), bar("09:31", 96, 97, 95, 96)]
        result = run_session(DAY, bars, params)
        assert result.direction == "short"
        assert result.entry_price == pytest.approx(98.0)

    def test_pct_stop_scales_with_entry_price(self) -> None:
        params = make_params(sl_mode="pct", sl_value=1.0)  # 1% of entry 100 = 1 pt
        bars = RANGE_BARS + [
            bar("09:30", 99, 100, 98.5, 99.5),    # short @100, sl 101, tp 98 (low stays above tp)
            bar("09:31", 100, 101.2, 100, 101),   # SL
        ]
        result = run_session(DAY, bars, params)
        assert result.exit_reason == "sl"
        assert result.exit_price == pytest.approx(101.0)

    def test_explicit_tp_points_beats_rrr(self) -> None:
        params = make_params(tp_points=7.0)  # rrr 2 would give tp 90; override → 93
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),
            bar("09:31", 99, 99, 92.8, 94),
        ]
        result = run_session(DAY, bars, params)
        assert result.exit_reason == "tp"
        assert result.exit_price == pytest.approx(93.0)


class TestAmbiguousAndOco:
    def test_both_levels_equidistant_is_ambiguous_no_trade(self) -> None:
        bars = RANGE_BARS + [bar("09:30", 95, 100.5, 89.5, 95)]  # open 95: 5 pts to both
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "ambiguous"
        assert result.direction is None

    def test_both_levels_resolved_by_open_proximity(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100.5, 89.5, 95),   # open 98 → upper (2 pts) beats lower (8)
            bar("09:31", 95, 95, 89, 90),        # tp for the short
        ]
        result = run_session(DAY, bars, make_params())
        assert result.direction == "short"


class TestAtrMode:
    def test_atr_offset_and_engine_plumbing(self) -> None:
        params = make_params(entry_offset_mode="atr", entry_offset_value=1.0)
        bars = RANGE_BARS + [
            bar("09:30", 98, 101.0, 97, 99),      # atr 2 → upper 102: no fill
            bar("09:31", 99, 102.0, 98, 100),     # fills short @102
        ]
        [result] = run_backtest([(DAY, bars)], params, atr_by_date={DAY: 2.0})
        assert result.entry_price == pytest.approx(102.0)

    def test_missing_atr_for_a_session_is_no_data(self) -> None:
        params = make_params(sl_mode="atr", sl_value=2.0)
        [result] = run_backtest([(DAY, RANGE_BARS)], params, atr_by_date={})
        assert result.exit_reason == "no_data"

    def test_atr_params_without_mapping_raises(self) -> None:
        params = make_params(sl_mode="atr")
        with pytest.raises(ValueError, match="atr_by_date"):
            run_backtest([(DAY, RANGE_BARS)], params)


class TestEngineAndParams:
    def test_unsorted_bars_rejected(self) -> None:
        bars = [bar("09:31", 95, 96, 94, 95), bar("09:30", 95, 96, 94, 95)]
        with pytest.raises(ValueError, match="sorted"):
            run_backtest([(DAY, bars)], make_params())

    def test_contract_sizing_scales_pnl(self) -> None:
        params = make_params(point_value_usd=20.0, contracts=3)  # full NQ ×3
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),
            bar("09:31", 99, 99, 89.5, 91),
        ]
        result = run_session(DAY, bars, params)
        assert result.pnl_usd == pytest.approx(10.0 * 20.0 * 3)

    def test_unknown_timezone_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            SessionClock(
                tz="Mars/Olympus",
                range_start=dtime(9, 0),
                range_end=dtime(9, 30),
                orders_place=dtime(9, 30),
                eod_flat=dtime(16, 0),
            )

    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError, match="end date"):
            make_params(start=DAY, end=date(2026, 7, 1))

    def test_needs_rrr_or_tp(self) -> None:
        with pytest.raises(ValidationError, match="rrr or tp_points"):
            make_params(rrr=None, tp_points=None)

    def test_window_membership_wraps_midnight(self) -> None:
        start, end = dtime(20, 0), dtime(2, 0)  # e.g. Asia range seen from NY
        assert _in_window(dtime(23, 0), start, end)
        assert _in_window(dtime(1, 59), start, end)
        assert not _in_window(dtime(2, 0), start, end)
        assert not _in_window(dtime(12, 0), start, end)


class TestGapThroughFills:
    def test_breakout_entry_gapping_open_fills_at_open(self) -> None:
        # Evening range high 100; the 09:30 bar OPENS at 104 — far beyond
        # the level. A buy stop fills near the open, not back at 100.
        bars = RANGE_BARS + [
            bar("09:30", 104, 105, 103, 104.5),
            bar("09:31", 104.5, 114.5, 104, 114),
        ]
        result = run_session(DAY, bars, make_params(direction_mode="breakout"))
        assert result.direction == "long"
        assert result.entry_price == pytest.approx(104.0)

    def test_fade_entry_gapping_open_stays_at_level(self) -> None:
        # Same gap, fade mode: the sell LIMIT at 100 would actually fill
        # at the better open price; booking the level is the conservative
        # side, so entry stays 100.
        bars = RANGE_BARS + [
            bar("09:30", 104, 105, 103, 104.5),
            bar("09:31", 104, 104, 89.5, 91),
        ]
        result = run_session(DAY, bars, make_params())
        assert result.direction == "short"
        assert result.entry_price == pytest.approx(100.0)

    def test_stop_loss_gap_through_fills_at_open(self) -> None:
        bars = RANGE_BARS + [
            bar("09:30", 98, 100, 97, 99),        # short @100, sl level 105
            bar("09:31", 99, 100, 98, 99.5),      # quiet bar
            bar("09:32", 108, 109, 107, 108.5),   # gaps OPEN above 105 → fill at 108
        ]
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "sl"
        assert result.exit_price == pytest.approx(108.0)
        assert result.pnl_points == pytest.approx(-8.0)

    def test_same_bar_stop_still_fills_at_level(self) -> None:
        # On the ENTRY bar the position opened mid-bar; a stop touch on
        # that same bar is not a gap — fills at the stop level.
        bars = RANGE_BARS + [
            bar("09:30", 98, 105.5, 97, 105),     # short @100, bar runs to SL 105
        ]
        result = run_session(DAY, bars, make_params())
        assert result.exit_reason == "sl"
        assert result.exit_price == pytest.approx(105.0)
