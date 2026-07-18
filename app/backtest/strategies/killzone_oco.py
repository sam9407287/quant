"""ICT Judas-Swing killzone OCO session logic (docs/STRATEGIES.md).

Pure function over one session's 1m bars — no I/O, no clock, no DB —
so the whole decision path is unit-testable with synthetic fixtures.
Conservatism rules (ADR-003 §2.1): when one bar touches both SL and TP
the trade books as a stop-loss; when one bar touches both entry levels
equidistantly from its open, the session books as `ambiguous`, no trade.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time, tzinfo

from app.backtest.params import BacktestParams, OffsetMode
from app.backtest.types import Bar, DayResult, Direction, ExitReason


def _in_window(t: time, start: time, end: time) -> bool:
    """Half-open [start, end) membership that survives a midnight wrap."""
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def _offset_points(
    mode: OffsetMode, value: float, level: float, atr: float | None
) -> float:
    if mode == "points":
        return value
    if mode == "pct":
        return level * value / 100.0
    if atr is None:
        raise ValueError("ATR mode requires a per-session atr value")
    return atr * value


def run_session(
    session_date: date,
    bars: Sequence[Bar],
    params: BacktestParams,
    atr: float | None = None,
) -> DayResult:
    """Play one session through the killzone-OCO rules → one DayResult."""
    zone: tzinfo = params.clock.zone
    clock = params.clock

    def local(bar: Bar) -> time:
        return bar.ts.astimezone(zone).time()

    range_bars = [b for b in bars if _in_window(local(b), clock.range_start, clock.range_end)]
    if not range_bars:
        return DayResult(session_date=session_date, exit_reason="no_data")

    range_high = max(b.high for b in range_bars)
    range_low = min(b.low for b in range_bars)

    upper = range_high + _offset_points(
        params.entry_offset_mode, params.entry_offset_value, range_high, atr
    )
    lower = range_low - _offset_points(
        params.entry_offset_mode, params.entry_offset_value, range_low, atr
    )

    # fade = mean reversion (sell the high side, buy the low side);
    # breakout = trade in the direction of the break on the same levels.
    upper_dir: Direction = "short" if params.direction_mode == "fade" else "long"
    lower_dir: Direction = "long" if params.direction_mode == "fade" else "short"

    monitor = [b for b in bars if _in_window(local(b), clock.orders_place, clock.eod_flat)]
    if not monitor:
        return DayResult(
            session_date=session_date,
            exit_reason="no_data",
            range_high=range_high,
            range_low=range_low,
        )

    slip = params.slippage_points_per_side

    entry_idx: int | None = None
    direction: Direction | None = None
    entry_level = 0.0
    for i, b in enumerate(monitor):
        hit_upper = b.high >= upper
        hit_lower = b.low <= lower
        if hit_upper and hit_lower:
            # Both entry levels inside one 1m bar: touch order unknowable
            # at this resolution. Resolve by proximity to the bar's open;
            # a dead tie is unresolvable → no trade.
            d_upper = abs(b.open - upper)
            d_lower = abs(b.open - lower)
            if d_upper == d_lower:
                return DayResult(
                    session_date=session_date,
                    exit_reason="ambiguous",
                    range_high=range_high,
                    range_low=range_low,
                )
            hit_upper = d_upper < d_lower
            hit_lower = not hit_upper
        if hit_upper or hit_lower:
            entry_idx = i
            direction = upper_dir if hit_upper else lower_dir
            entry_level = upper if hit_upper else lower
            break

    if entry_idx is None or direction is None:
        return DayResult(
            session_date=session_date,
            exit_reason="no_fill",
            range_high=range_high,
            range_low=range_low,
        )

    sign = 1.0 if direction == "long" else -1.0
    entry_price = entry_level + sign * slip  # slippage is always adverse
    entry_bar = monitor[entry_idx]

    sl_points = _offset_points(params.sl_mode, params.sl_value, entry_price, atr)
    tp_pts = params.tp_points if params.tp_points is not None else sl_points * (params.rrr or 0.0)
    sl_level = entry_price - sign * sl_points
    tp_level = entry_price + sign * tp_pts

    mae = 0.0
    mfe = 0.0
    exit_reason: ExitReason = "eod"
    exit_price: float | None = None
    exit_ts = None
    # Entry bar included: its full range already happened around the
    # fill, and excluding it would optimistically skip same-bar stops.
    for b in monitor[entry_idx:]:
        mae = max(mae, sign * (entry_price - (b.low if sign > 0 else b.high)))
        mfe = max(mfe, sign * ((b.high if sign > 0 else b.low) - entry_price))
        stop_hit = b.low <= sl_level if sign > 0 else b.high >= sl_level
        target_hit = b.high >= tp_level if sign > 0 else b.low <= tp_level
        if stop_hit:  # checked first: both-in-one-bar books as SL
            exit_reason = "sl"
            exit_price = sl_level - sign * slip
            exit_ts = b.ts
            break
        if target_hit:
            exit_reason = "tp"
            exit_price = tp_level
            exit_ts = b.ts
            break

    if exit_price is None:  # forced flat at eod_flat (or data ran out)
        last = monitor[-1]
        exit_price = last.close - sign * slip
        exit_ts = last.ts

    pnl_points = sign * (exit_price - entry_price)
    pnl_usd = (
        pnl_points * params.point_value_usd * params.contracts
        - params.commission_usd_per_rt
    )

    return DayResult(
        session_date=session_date,
        exit_reason=exit_reason,
        direction=direction,
        entry_ts=entry_bar.ts,
        entry_price=entry_price,
        exit_ts=exit_ts,
        exit_price=exit_price,
        pnl_points=pnl_points,
        pnl_usd=pnl_usd,
        mae_points=mae,
        mfe_points=mfe,
        range_high=range_high,
        range_low=range_low,
    )
