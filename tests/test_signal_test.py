"""Unit tests for the signal-test engine (CMT quant curriculum)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.strategies.schemas import Condition, Operand, StrategyDefinition
from app.strategies.signal_test import signal_test

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def mk_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [T0 + timedelta(hours=i) for i in range(len(closes))],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def long_above(level: float) -> StrategyDefinition:
    return StrategyDefinition(
        timeframe="1h",
        entry_long=Condition(
            op="cross_above",
            left=Operand(kind="price"),
            right=Operand(kind="const", value=level),
        ),
    )


class TestSignalTest:
    def test_measures_forward_return_from_each_signal(self) -> None:
        # Cross above 100 at index 2 (99→101), then price rises to 110.
        closes = [99, 99, 101, 103, 105, 107, 110]
        res = signal_test(mk_df(closes), long_above(100.0), horizon=4)
        assert res.signal_count == 1
        # entry close 101, +4 bars close 110 → (110-101)/101*100
        assert res.mean_return_pct == pytest.approx((110 - 101) / 101 * 100, rel=1e-3)
        assert res.win_rate == 1.0
        assert len(res.avg_path_pct) == 5  # day 0..4
        assert res.avg_path_pct[0] == pytest.approx(0.0)

    def test_short_signal_return_is_negated(self) -> None:
        # A short signal wins when price FALLS.
        d = StrategyDefinition(
            timeframe="1h",
            entry_short=Condition(
                op="cross_below",
                left=Operand(kind="price"),
                right=Operand(kind="const", value=100.0),
            ),
        )
        closes = [101, 101, 99, 97, 95]  # cross below 100 at idx 2
        res = signal_test(mk_df(closes), d, horizon=2)
        assert res.signal_count == 1
        # entry 99, two bars later 95, short → +(99-95)/99*100 > 0
        assert res.mean_return_pct > 0
        assert res.win_rate == 1.0

    def test_tail_signals_without_full_horizon_are_dropped(self) -> None:
        # A signal on the last bar has no forward data.
        closes = [99, 101, 102]  # cross above 100 at idx 1
        res = signal_test(mk_df(closes), long_above(100.0), horizon=5)
        assert res.signal_count == 0

    def test_multiple_signals_aggregate(self) -> None:
        # Two separate crosses above 100.
        closes = [99, 101, 99, 98, 101, 103, 105, 107]
        res = signal_test(mk_df(closes), long_above(100.0), horizon=2)
        assert res.signal_count == 2
        assert 0.0 <= res.win_rate <= 1.0
        assert res.best_return_pct >= res.worst_return_pct

    def test_distribution_and_dispersion_present(self) -> None:
        closes = [99, 101, 100, 98, 101, 103, 99, 97, 101, 104, 106, 108]
        res = signal_test(mk_df(closes), long_above(100.0), horizon=2, bins=5)
        assert len(res.distribution) == 5
        assert sum(n for _, n in res.distribution) == res.signal_count
        assert res.std_return_pct >= 0.0

    def test_no_signal_returns_empty(self) -> None:
        res = signal_test(mk_df([50, 51, 52, 53]), long_above(100.0), horizon=2)
        assert res.signal_count == 0
        assert res.mean_return_pct == 0.0

    def test_empty_frame(self) -> None:
        res = signal_test(mk_df([]), long_above(100.0))
        assert res.signal_count == 0
