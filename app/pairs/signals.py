"""The pairs state machine: one pure `step` shared by backtest and live job.

Keeping a single implementation is what makes the backtest a statement
about the live system rather than a cousin of it. The function takes the
state after yesterday's close, today's observation, and the rules, and
returns the new state plus the event that happened (if any). No dates,
no I/O: the caller decides what "today" is and what to do with an event.

Exit priority when several conditions hold on the same day:
stop → breakdown → time stop → exit. An exit never re-enters the same day.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from app.pairs.schemas import Event, Side, SignalRules


@dataclass(frozen=True, slots=True)
class EntryParams:
    """Parameters frozen when a position opens (ADR-010 §2.4, parameter freeze)."""

    alpha: float
    beta: float
    mean: float
    std: float
    half_life: float | None
    z_window: int

    def frozen_z(self, log_y: float, log_x: float) -> float:
        spread = log_y - self.alpha - self.beta * log_x
        if not np.isfinite(self.std) or self.std <= 1e-12:
            return float("nan")
        return float((spread - self.mean) / self.std)


@dataclass(frozen=True, slots=True)
class PairState:
    """Everything that persists from one trading day to the next."""

    side: Side = "flat"
    entry_params: EntryParams | None = None
    entry_z: float | None = None
    days_held: int = 0
    breakdown_days: int = 0
    cooldown_remaining: int = 0

    @property
    def in_position(self) -> bool:
        return self.side != "flat"


@dataclass(frozen=True, slots=True)
class Observation:
    """What the scanner knows at today's close for one pair."""

    log_y: float
    log_x: float
    z_live: float | None          # z against today's rolling parameters
    pvalue: float | None          # latest EG p-value (may be stepped)
    qualified: bool               # passed the qualification gate today
    live_params: EntryParams | None


@dataclass(frozen=True, slots=True)
class Transition:
    """Result of one step: the new state and what, if anything, happened."""

    state: PairState
    event: Event
    z_used: float | None

    @property
    def side_after(self) -> Side:
        return self.state.side


def step(state: PairState, obs: Observation, rules: SignalRules) -> Transition:
    """Advance one pair by one trading day."""
    if state.in_position:
        return _step_in_position(state, obs, rules)
    return _step_flat(state, obs, rules)


def _step_flat(state: PairState, obs: Observation, rules: SignalRules) -> Transition:
    cooldown = max(state.cooldown_remaining - 1, 0)
    idle = replace(state, cooldown_remaining=cooldown)
    if state.cooldown_remaining > 0:
        return Transition(idle, "none", obs.z_live)
    if rules.require_qualified and not obs.qualified:
        return Transition(idle, "none", obs.z_live)
    z = obs.z_live
    if z is None or not np.isfinite(z) or obs.live_params is None:
        return Transition(idle, "none", z)

    side: Side | None = None
    if z >= rules.entry_z:
        side = "short_spread"
    elif z <= -rules.entry_z:
        side = "long_spread"
    if side is None:
        return Transition(idle, "none", z)

    opened = PairState(
        side=side,
        entry_params=obs.live_params,
        entry_z=float(z),
        days_held=0,
        breakdown_days=0,
        cooldown_remaining=0,
    )
    return Transition(opened, "entry", float(z))


def _step_in_position(state: PairState, obs: Observation, rules: SignalRules) -> Transition:
    assert state.entry_params is not None
    params = state.entry_params
    days_held = state.days_held + 1

    if rules.freeze_params:
        z = params.frozen_z(obs.log_y, obs.log_x)
    else:
        z = float(obs.z_live) if obs.z_live is not None else float("nan")

    breakdown_days = (
        state.breakdown_days + 1
        if obs.pvalue is not None and np.isfinite(obs.pvalue) and obs.pvalue > rules.breakdown_pvalue
        else 0
    )
    held = replace(state, days_held=days_held, breakdown_days=breakdown_days)

    def closed(event: Event, cooldown: bool) -> Transition:
        flat = PairState(cooldown_remaining=rules.cooldown_days if cooldown else 0)
        return Transition(flat, event, None if not np.isfinite(z) else float(z))

    if np.isfinite(z):
        adverse = z >= rules.stop_z if state.side == "short_spread" else z <= -rules.stop_z
        if adverse:
            return closed("stop", cooldown=True)
    if breakdown_days >= rules.breakdown_days:
        return closed("breakdown", cooldown=True)
    if params.half_life is not None and days_held > rules.time_stop_half_lives * params.half_life:
        return closed("time_stop", cooldown=False)
    if np.isfinite(z):
        if rules.exit_rule == "threshold":
            if abs(z) <= rules.exit_z:
                return closed("exit", cooldown=False)
        elif (state.side == "short_spread" and z <= 0) or (state.side == "long_spread" and z >= 0):
            return closed("exit", cooldown=False)
    return Transition(held, "none", None if not np.isfinite(z) else float(z))
