"""Unit tests for the signal-strategy evaluation engine (ADR-004)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from app.strategies.engine import evaluate
from app.strategies.schemas import (
    Bracket,
    Condition,
    Operand,
    StrategyDefinition,
)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def mk_df(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows = [(open, high, low, close), ...] on an hourly clock."""
    return pd.DataFrame(
        {
            "ts": [T0 + timedelta(hours=i) for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1000] * len(rows),
        }
    )


def price() -> Operand:
    return Operand(kind="price")


def const(v: float) -> Operand:
    return Operand(kind="const", value=v)


def cross_above(left: Operand, right: Operand) -> Condition:
    return Condition(op="cross_above", left=left, right=right)


def defn(**kw: object) -> StrategyDefinition:
    base: dict[str, object] = {"timeframe": "1h"}
    base.update(kw)
    return StrategyDefinition(**base)  # type: ignore[arg-type]


LONG_ABOVE_100 = defn(entry_long=cross_above(price(), const(100.0)))


class TestSignalExecution:
    def test_entry_fills_at_next_bar_open(self) -> None:
        df = mk_df([
            (99, 99.5, 98.5, 99),      # below
            (99, 101.5, 99, 101),      # close crosses above 100 → signal
            (101.5, 102, 101, 101.8),  # entry here at OPEN 101.5
            (101.8, 102, 101, 101.9),
        ])
        trades = evaluate(df, LONG_ABOVE_100)
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == "long"
        assert t.entry_price == 101.5
        assert t.entry_ts == df.at[2, "ts"]
        assert t.exit_reason == "end"  # never exited → closed on last close

    def test_signal_exit_at_next_open(self) -> None:
        d = defn(
            entry_long=cross_above(price(), const(100.0)),
            exit_long=Condition(op="cross_below", left=price(), right=const(100.0)),
        )
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),       # entry signal
            (101.5, 102, 101, 101.8),   # entry @101.5
            (101, 101.5, 99, 99.5),     # close crosses below 100 → exit signal
            (99.4, 99.6, 99, 99.2),     # exit here at OPEN 99.4
        ])
        [t] = evaluate(df, d)
        assert t.exit_reason == "signal"
        assert t.exit_price == 99.4
        assert t.pnl_points == pytest.approx(99.4 - 101.5)

    def test_opposite_entry_reverses_position(self) -> None:
        d = defn(
            entry_long=cross_above(price(), const(100.0)),
            entry_short=Condition(op="cross_below", left=price(), right=const(100.0)),
        )
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),       # long signal
            (101.5, 102, 101, 101.8),   # long entry @101.5
            (101, 101.5, 99, 99.5),     # short signal while long
            (99.4, 99.6, 98, 99.2),     # close long AND open short @99.4
            (99.2, 99.4, 98.5, 99.0),
        ])
        trades = evaluate(df, d)
        assert len(trades) == 2
        assert trades[0].direction == "long"
        assert trades[0].exit_reason == "signal"
        assert trades[0].exit_price == 99.4
        assert trades[1].direction == "short"
        assert trades[1].entry_price == 99.4
        assert trades[1].exit_reason == "end"

    def test_signal_on_last_bar_does_not_enter(self) -> None:
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),  # signal on the final bar — no next open
        ])
        assert evaluate(df, LONG_ABOVE_100) == []

    def test_simultaneous_long_and_short_signals_stand_aside(self) -> None:
        d = defn(
            entry_long=Condition(op="gt", left=price(), right=const(100.0)),
            entry_short=Condition(op="gt", left=price(), right=const(100.0)),
        )
        df = mk_df([(101, 102, 100.5, 101.5)] * 4)
        assert evaluate(df, d) == []


class TestBrackets:
    D_SL5_TP10 = defn(
        entry_long=cross_above(price(), const(100.0)),
        sl=Bracket(mode="points", value=5.0),
        tp=Bracket(mode="points", value=10.0),
    )

    def test_stop_loss_fill(self) -> None:
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),
            (101.5, 102, 101, 101.8),   # entry @101.5 → sl 96.5 / tp 111.5
            (101, 101.5, 96.0, 97),     # low ≤ 96.5 → SL at level
        ])
        [t] = evaluate(df, self.D_SL5_TP10)
        assert t.exit_reason == "sl"
        assert t.exit_price == pytest.approx(96.5)
        assert t.sl_level == pytest.approx(96.5)
        assert t.tp_level == pytest.approx(111.5)

    def test_stop_gap_through_fills_at_open(self) -> None:
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),
            (101.5, 102, 101, 101.8),   # entry @101.5, sl 96.5
            (94, 95, 93, 94.5),         # OPENS below the stop → fill 94
        ])
        [t] = evaluate(df, self.D_SL5_TP10)
        assert t.exit_reason == "sl"
        assert t.exit_price == pytest.approx(94.0)

    def test_entry_bar_stop_fills_at_level_not_open(self) -> None:
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),
            (101.5, 102, 96.0, 97),     # SAME bar as entry runs to the stop
        ])
        [t] = evaluate(df, self.D_SL5_TP10)
        assert t.exit_reason == "sl"
        assert t.exit_price == pytest.approx(96.5)  # level, no gap logic

    def test_sl_and_tp_same_bar_books_sl(self) -> None:
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),
            (101.5, 112, 96, 105),      # touches 111.5 AND 96.5 → SL
        ])
        [t] = evaluate(df, self.D_SL5_TP10)
        assert t.exit_reason == "sl"

    def test_tp_only_strategy_has_no_sl_level(self) -> None:
        d = defn(
            entry_long=cross_above(price(), const(100.0)),
            tp=Bracket(mode="points", value=10.0),
        )
        df = mk_df([
            (99, 99.5, 98.5, 99),
            (99, 101.5, 99, 101),
            (101.5, 102, 101, 101.8),   # entry @101.5, tp 111.5
            (102, 112, 101, 111),       # TP
        ])
        [t] = evaluate(df, d)
        assert t.exit_reason == "tp"
        assert t.exit_price == pytest.approx(111.5)
        assert t.sl_level is None

    def test_pct_bracket_scales_with_entry(self) -> None:
        d = defn(
            entry_short=Condition(op="lt", left=price(), right=const(100.0)),
            sl=Bracket(mode="pct", value=1.0),
        )
        df = mk_df([
            (99, 99.5, 98, 98.5),       # short signal (close < 100)
            (98.4, 99.0, 98, 98.6),     # entry @98.4 → sl = 98.4 × 1.01 ≈ 99.384
            (98.6, 99.2, 98.4, 98.8),   # stays under the stop
            (99.3, 99.5, 98.9, 99.4),   # high ≥ 99.384 → SL
        ])
        [t] = evaluate(df, d)
        assert t.direction == "short"
        assert t.exit_reason == "sl"
        assert t.exit_price == pytest.approx(98.4 * 1.01)


class TestOperands:
    def test_donchian_breakout_uses_prior_bars_only(self) -> None:
        d = defn(
            entry_long=Condition(
                op="gt",
                left=price(),
                right=Operand(kind="highest_high", window=3),
            ),
        )
        df = mk_df([
            (100, 101, 99, 100),
            (100, 102, 99, 101),
            (101, 103, 100, 102),
            (102, 103, 101, 102.5),      # close 102.5 < max(101,102,103)=103
            (102.5, 104, 102, 103.5),    # close 103.5 > max(102,103,103)=103 → signal
            (103.6, 104, 103, 103.8),    # entry @103.6
        ])
        [t] = evaluate(df, d)
        assert t.entry_price == pytest.approx(103.6)

    def test_ema_cross_strategy_runs(self) -> None:
        d = defn(
            entry_long=cross_above(
                Operand(kind="ema", window=3), Operand(kind="ema", window=8)
            ),
        )
        ramp = [(100 - i, 100 - i + 0.5, 100 - i - 0.5, 100 - i) for i in range(10)]
        ramp += [(90 + i * 2, 90 + i * 2 + 1, 90 + i * 2 - 1, 90 + i * 2 + 0.5) for i in range(10)]
        trades = evaluate(mk_df(ramp), d)
        assert len(trades) == 1
        assert trades[0].direction == "long"

    def test_empty_frame(self) -> None:
        assert evaluate(mk_df([]), LONG_ABOVE_100) == []


class TestDefinitionValidation:
    def test_requires_an_entry(self) -> None:
        with pytest.raises(ValidationError, match="entry_long/entry_short"):
            StrategyDefinition(timeframe="1h")

    def test_const_requires_value(self) -> None:
        with pytest.raises(ValidationError, match="const"):
            Operand(kind="const")
