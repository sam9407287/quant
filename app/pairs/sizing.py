"""Position sizing for a pair: ideal fractional legs and integer contracts.

Hedge geometry: the regression is on log prices, so β is an elasticity —
a 1 % move in X maps to β % in Y. For P&L to track the spread the *dollar*
notional of the X leg must be β times the Y leg:

    N_x = β · N_y,   where N = qty × price × multiplier.

`fractional` sizing reports that ideal (the research truth); `integer`
rounds to whole contracts, micro first when available, and reports how
far the rounded ratio drifted from β. The difference between the two
modes over a backtest is the "tradeability tax".
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pairs.universe import ContractSpec, PairInstrument, get_instrument


@dataclass(frozen=True, slots=True)
class LegSize:
    ticker: str
    contract: str
    qty: float            # whole number in integer mode, any float in fractional mode
    multiplier: float
    tick_size: float
    price: float

    @property
    def notional(self) -> float:
        return self.qty * self.price * self.multiplier

    @property
    def contracts(self) -> float:
        return abs(self.qty)


@dataclass(frozen=True, slots=True)
class PositionSize:
    y: LegSize
    x: LegSize
    beta: float
    target_y_notional: float
    mode: str
    feasible: bool
    rounding_error_pct: float | None
    adverse_2sigma_usd: float | None

    @property
    def gross_notional(self) -> float:
        return self.y.notional + self.x.notional

    @property
    def realised_ratio(self) -> float | None:
        return None if self.y.notional == 0 else self.x.notional / self.y.notional


def size_position(
    y_ticker: str,
    x_ticker: str,
    *,
    price_y: float,
    price_x: float,
    beta: float,
    gross_notional: float,
    mode: str = "fractional",
    prefer_micro: bool = True,
    spread_std: float | None = None,
) -> PositionSize:
    """Split `gross_notional` across the legs so that N_x = β · N_y.

    `spread_std` (log units ≈ fractional move) turns into a dollar estimate
    of a two-sigma adverse spread move on the Y notional, which is the
    number to compare against any loss limit.
    """
    if beta <= 0:
        raise ValueError("sizing needs a positive hedge ratio")
    if gross_notional <= 0 or price_y <= 0 or price_x <= 0:
        raise ValueError("notional and prices must be positive")

    inst_y, inst_x = get_instrument(y_ticker), get_instrument(x_ticker)
    target_y = gross_notional / (1.0 + beta)
    target_x = beta * target_y

    if mode == "fractional":
        cy = inst_y.smallest if prefer_micro else inst_y.standard
        cx = inst_x.smallest if prefer_micro else inst_x.standard
        y_leg = LegSize(y_ticker, cy.code, target_y / (price_y * cy.multiplier), cy.multiplier, cy.tick_size, price_y)
        x_leg = LegSize(x_ticker, cx.code, target_x / (price_x * cx.multiplier), cx.multiplier, cx.tick_size, price_x)
        return PositionSize(
            y=y_leg, x=x_leg, beta=beta, target_y_notional=target_y, mode=mode, feasible=True,
            rounding_error_pct=0.0, adverse_2sigma_usd=_adverse(target_y, spread_std),
        )

    y_leg = _round_leg(inst_y, y_ticker, price_y, target_y, prefer_micro)
    x_leg = _round_leg(inst_x, x_ticker, price_x, target_x, prefer_micro)
    feasible = y_leg.qty >= 1 and x_leg.qty >= 1
    error: float | None = None
    if feasible:
        error = abs((x_leg.notional / y_leg.notional) / beta - 1.0) * 100.0
    return PositionSize(
        y=y_leg, x=x_leg, beta=beta, target_y_notional=target_y, mode=mode, feasible=feasible,
        rounding_error_pct=error, adverse_2sigma_usd=_adverse(y_leg.notional, spread_std) if feasible else None,
    )


def _round_leg(inst: PairInstrument, ticker: str, price: float, target: float, prefer_micro: bool) -> LegSize:
    """Pick the contract and whole quantity closest to the target notional.

    Micro first when preferred: it exists precisely so the ratio can land
    nearer β. If the micro rounds to zero the standard is tried as well,
    and the leg is reported infeasible when both do.
    """
    candidates: list[ContractSpec] = list(inst.tradeable)
    candidates.sort(key=lambda c: c.multiplier if prefer_micro else -c.multiplier)
    best: LegSize | None = None
    for spec in candidates:
        unit = price * spec.multiplier
        qty = int(round(target / unit))
        leg = LegSize(ticker, spec.code, float(qty), spec.multiplier, spec.tick_size, price)
        if qty >= 1 and (best is None or abs(leg.notional - target) < abs(best.notional - target)):
            best = leg
        if best is None:
            best = leg
    assert best is not None
    return best


def _adverse(y_notional: float, spread_std: float | None) -> float | None:
    if spread_std is None or spread_std <= 0:
        return None
    return -2.0 * spread_std * y_notional
