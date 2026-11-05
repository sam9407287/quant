"""State-machine and sizing tests (ADR-010 phase 3)."""

from __future__ import annotations

import math

import pytest

from app.pairs.schemas import SignalRules
from app.pairs.signals import EntryParams, Observation, PairState, step
from app.pairs.sizing import size_position

PARAMS = EntryParams(alpha=0.0, beta=1.0, mean=0.0, std=0.01, half_life=10.0, z_window=20)
RULES = SignalRules()


def obs(z: float | None, *, pvalue: float = 0.01, qualified: bool = True, log_y: float | None = None) -> Observation:
    """Observation whose frozen z equals `z` under PARAMS (log_x = 0)."""
    ly = (z or 0.0) * PARAMS.std if log_y is None else log_y
    return Observation(log_y=ly, log_x=0.0, z_live=z, pvalue=pvalue, qualified=qualified, live_params=PARAMS)


class TestEntries:
    def test_short_spread_on_high_z(self) -> None:
        tr = step(PairState(), obs(2.3), RULES)
        assert tr.event == "entry" and tr.state.side == "short_spread"
        assert tr.state.entry_params is PARAMS and tr.state.entry_z == 2.3
        assert tr.state.days_held == 0

    def test_long_spread_on_low_z(self) -> None:
        tr = step(PairState(), obs(-2.0), RULES)
        assert tr.event == "entry" and tr.state.side == "long_spread"

    def test_no_entry_inside_band(self) -> None:
        tr = step(PairState(), obs(1.9), RULES)
        assert tr.event == "none" and tr.state.side == "flat"

    def test_no_entry_when_unqualified_unless_gate_off(self) -> None:
        assert step(PairState(), obs(2.5, qualified=False), RULES).event == "none"
        loose = RULES.model_copy(update={"require_qualified": False})
        assert step(PairState(), obs(2.5, qualified=False), loose).event == "entry"

    def test_cooldown_blocks_and_decrements(self) -> None:
        st = PairState(cooldown_remaining=2)
        tr = step(st, obs(3.0), RULES)
        assert tr.event == "none" and tr.state.cooldown_remaining == 1
        tr = step(tr.state, obs(3.0), RULES)
        assert tr.event == "none" and tr.state.cooldown_remaining == 0
        tr = step(tr.state, obs(3.0), RULES)
        assert tr.event == "entry"

    def test_missing_z_is_no_entry(self) -> None:
        assert step(PairState(), obs(None), RULES).event == "none"


def opened(side: str = "short_spread") -> PairState:
    return PairState(side=side, entry_params=PARAMS, entry_z=2.2 if side == "short_spread" else -2.2)  # type: ignore[arg-type]


class TestExits:
    def test_threshold_exit(self) -> None:
        tr = step(opened(), obs(0.4), RULES)
        assert tr.event == "exit" and tr.state.side == "flat" and tr.state.cooldown_remaining == 0

    def test_threshold_not_yet(self) -> None:
        tr = step(opened(), obs(0.8), RULES)
        assert tr.event == "none" and tr.state.side == "short_spread" and tr.state.days_held == 1

    def test_cross_zero_exit_needs_a_sign_change(self) -> None:
        rules = RULES.model_copy(update={"exit_rule": "cross_zero"})
        assert step(opened(), obs(0.3), rules).event == "none"
        assert step(opened(), obs(-0.1), rules).event == "exit"
        assert step(opened("long_spread"), obs(0.0), rules).event == "exit"

    def test_stop_in_the_adverse_direction_only(self) -> None:
        tr = step(opened("short_spread"), obs(3.6), RULES)
        assert tr.event == "stop" and tr.state.cooldown_remaining == RULES.cooldown_days
        # A long spread at z=+3.6 is a huge win, not a stop (it exits via threshold/cross rules later).
        assert step(opened("long_spread"), obs(3.6), RULES).event == "none"
        assert step(opened("long_spread"), obs(-3.6), RULES).event == "stop"

    def test_time_stop_after_three_half_lives(self) -> None:
        st = opened()
        st = PairState(side=st.side, entry_params=PARAMS, entry_z=2.2, days_held=30)
        tr = step(st, obs(1.5), RULES)  # day 31 > 3 × 10
        assert tr.event == "time_stop" and tr.state.cooldown_remaining == 0

    def test_breakdown_counts_consecutive_days_and_resets(self) -> None:
        st = opened()
        for _ in range(4):
            tr = step(st, obs(1.5, pvalue=0.2), RULES)
            assert tr.event == "none"
            st = tr.state
        assert st.breakdown_days == 4
        # One good day resets the counter.
        st = step(st, obs(1.5, pvalue=0.02), RULES).state
        assert st.breakdown_days == 0
        for _ in range(4):
            st = step(st, obs(1.5, pvalue=0.2), RULES).state
        tr = step(st, obs(1.5, pvalue=0.2), RULES)
        assert tr.event == "breakdown" and tr.state.cooldown_remaining == RULES.cooldown_days

    def test_priority_stop_beats_breakdown(self) -> None:
        st = PairState(side="short_spread", entry_params=PARAMS, entry_z=2.2, breakdown_days=4)
        assert step(st, obs(4.0, pvalue=0.5), RULES).event == "stop"

    def test_frozen_vs_live_parameters(self) -> None:
        # Live z says "exit", frozen z (from log prices) says "hold".
        o = Observation(log_y=0.015, log_x=0.0, z_live=0.1, pvalue=0.01, qualified=True, live_params=PARAMS)
        assert step(opened(), o, RULES).event == "none"  # frozen z = 1.5
        live = RULES.model_copy(update={"freeze_params": False})
        assert step(opened(), o, live).event == "exit"

    def test_frozen_z_degenerate_std(self) -> None:
        bad = EntryParams(alpha=0.0, beta=1.0, mean=0.0, std=0.0, half_life=5.0, z_window=10)
        assert math.isnan(bad.frozen_z(1.0, 0.0))
        st = PairState(side="short_spread", entry_params=bad, entry_z=2.0)
        assert step(st, obs(0.0), RULES).event == "none"


class TestSizing:
    def test_fractional_matches_beta_exactly(self) -> None:
        s = size_position("NQ=F", "ES=F", price_y=20000, price_x=5000, beta=1.3, gross_notional=230_000, spread_std=0.02)
        assert s.feasible and s.mode == "fractional"
        assert s.realised_ratio == pytest.approx(1.3)
        assert s.y.notional + s.x.notional == pytest.approx(230_000)
        assert s.y.notional == pytest.approx(100_000)
        assert s.y.contract == "MNQ" and s.x.contract == "MES"
        assert s.adverse_2sigma_usd == pytest.approx(-4000)
        assert s.rounding_error_pct == 0.0

    def test_integer_prefers_micro_and_reports_error(self) -> None:
        s = size_position("NQ=F", "ES=F", price_y=20000, price_x=5000, beta=1.0, gross_notional=200_000, mode="integer")
        # Y: 100k / (20000×2) = 2.5 → 2 or 3 MNQ; X: 100k / (5000×5) = 4 MES.
        assert s.feasible
        assert s.y.contract == "MNQ" and s.x.contract == "MES"
        assert s.x.qty == 4 and s.y.qty in (2, 3)
        assert s.rounding_error_pct is not None and s.rounding_error_pct > 0

    def test_integer_falls_back_to_standard_when_closer(self) -> None:
        s = size_position("NQ=F", "ES=F", price_y=20000, price_x=5000, beta=1.0, gross_notional=4_000_000, mode="integer", prefer_micro=False)
        assert s.y.contract == "NQ" and s.x.contract == "ES"
        assert s.y.qty == 5 and s.x.qty == 8

    def test_infeasible_when_too_small(self) -> None:
        s = size_position("NQ=F", "ES=F", price_y=20000, price_x=5000, beta=1.0, gross_notional=10_000, mode="integer")
        assert not s.feasible and s.rounding_error_pct is None and s.adverse_2sigma_usd is None

    def test_shares_size_as_unit_contracts(self) -> None:
        s = size_position("KO", "PEP", price_y=60, price_x=170, beta=0.9, gross_notional=19_000, mode="integer")
        assert s.y.contract == "KO" and s.y.multiplier == 1.0
        assert s.y.qty == round(10_000 / 60)

    def test_validation(self) -> None:
        with pytest.raises(ValueError):
            size_position("NQ=F", "ES=F", price_y=1, price_x=1, beta=-1.0, gross_notional=100)
        with pytest.raises(ValueError):
            size_position("NQ=F", "ES=F", price_y=1, price_x=1, beta=1.0, gross_notional=0)
