"""Signal-strategy evaluation: bars DataFrame + definition → trades.

Execution model (ADR-004):
- Conditions are evaluated on each bar's CLOSE; the resulting order
  executes at the NEXT bar's OPEN — no lookahead by construction.
- One position at a time. Exits: the direction's exit condition, the
  SL/TP bracket, an opposite entry signal (close and reverse), or end
  of data.
- Bracket conservatism matches the killzone engine: a bar touching
  both SL and TP books as SL; a later bar that OPENS beyond the stop
  fills at that open (gap-through), except the entry bar itself.

A strategy may additionally declare a session (ADR-009), which adds an
order-driven entry path alongside the signal one:

- `stop_entry` rests two orders at price levels; they fill INTRABAR the
  moment a bar trades through, not at the next open. One bar touching
  both resolves by proximity to that bar's open, and a dead tie stands
  the session down — the same conservatism the killzone engine uses.
- A position still open on the session's last bar is flattened there.
- Filters gate resting orders exactly as they gate signals.

Both paths share one position and one bracket, so an ICT-style stop
entry and an indicator filter compose rather than living in separate
engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from app.ml.features import build_feature
from app.ml.schemas import FeatureSpec
from app.strategies.schemas import (
    Bracket,
    Condition,
    Operand,
    StopEntry,
    StrategyDefinition,
)
from app.strategies.session import Sessions, build_sessions, window_extreme

ExitReason = Literal["signal", "sl", "tp", "end", "eod"]


@dataclass(frozen=True, slots=True)
class Trade:
    """One round trip; sl/tp levels kept for the chart's position boxes."""

    direction: Literal["long", "short"]
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    exit_reason: ExitReason
    sl_level: float | None
    tp_level: float | None

    @property
    def pnl_points(self) -> float:
        sign = 1.0 if self.direction == "long" else -1.0
        return sign * (self.exit_price - self.entry_price)


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    """Wilder-style Average True Range."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False).mean()


def _operand_series(df: pd.DataFrame, op: Operand, sessions: Sessions | None = None) -> pd.Series:
    close = df["close"].astype(float)
    if op.kind in ("session_high", "session_low"):
        if sessions is None:  # schema forbids this; belt and braces
            raise ValueError(f"{op.kind} requires a session")
        assert op.time_start is not None and op.time_end is not None
        side = "high" if op.kind == "session_high" else "low"
        return window_extreme(df, sessions, op.time_start, op.time_end, side)
    if op.kind == "price":
        return close
    if op.kind == "const":
        return pd.Series(float(op.value or 0.0), index=df.index)
    if op.kind == "highest_high":
        # Extreme of the PRIOR `window` bars — shifted so the current
        # bar cannot trivially "break" a channel that includes itself.
        return df["high"].astype(float).rolling(op.window).max().shift(1)
    if op.kind == "lowest_low":
        return df["low"].astype(float).rolling(op.window).min().shift(1)
    if op.kind == "macd":
        return _ema(close, op.window) - _ema(close, op.window2)
    if op.kind == "macd_signal":
        return _ema(_ema(close, op.window) - _ema(close, op.window2), 9)
    if op.kind == "atr":
        return _atr(df, op.window)
    if op.kind == "roc":
        # Rate of change, %: return over the prior `window` bars.
        return (close / close.shift(op.window) - 1.0) * 100.0
    if op.kind in ("bollinger_upper", "bollinger_lower"):
        mid = close.rolling(op.window).mean()
        band = close.rolling(op.window).std(ddof=0) * float(op.value or 2.0)
        return mid + band if op.kind == "bollinger_upper" else mid - band
    # ema / sma / rsi — same math the ML workbench uses.
    if op.kind == "ema" or op.kind == "sma" or op.kind == "rsi":
        return build_feature(df, FeatureSpec(kind=op.kind, window=op.window))
    raise ValueError(f"unhandled operand kind: {op.kind}")


def _condition_series(
    df: pd.DataFrame, cond: Condition | None, sessions: Sessions | None = None
) -> pd.Series:
    """Boolean series: True at bar i = condition holds at bar i's close."""
    if cond is None:
        return pd.Series(False, index=df.index)
    left = _operand_series(df, cond.left, sessions)
    right = _operand_series(df, cond.right, sessions)
    if cond.op == "gt":
        out = left > right
    elif cond.op == "lt":
        out = left < right
    elif cond.op == "cross_above":
        out = (left > right) & (left.shift(1) <= right.shift(1))
    else:  # cross_below
        out = (left < right) & (left.shift(1) >= right.shift(1))
    return out.fillna(False)


def _filter_mask(
    df: pd.DataFrame, defn: StrategyDefinition, sessions: Sessions | None = None
) -> pd.Series:
    """AND of every filter condition — the standing gate on all entries."""
    mask = pd.Series(True, index=df.index)
    for f in defn.filters:
        mask &= _condition_series(df, f, sessions)
    return mask


def _sessions_for(df: pd.DataFrame, defn: StrategyDefinition) -> Sessions | None:
    return build_sessions(df["ts"], defn.session) if defn.session else None


def entry_signal(
    df: pd.DataFrame,
    defn: StrategyDefinition,
    direction: str,
    sessions: Sessions | None = None,
) -> pd.Series:
    """Boolean entry series for a direction: trigger AND all filters.

    Shared by the engine and the signal test so both agree on when a
    strategy's entry actually fires. Callers that already built the
    session labels pass them in; the rest let it derive them.
    """
    if sessions is None:
        sessions = _sessions_for(df, defn)
    trigger = defn.entry_long if direction == "long" else defn.entry_short
    out = _condition_series(df, trigger, sessions) & _filter_mask(df, defn, sessions)
    if sessions is not None:
        out &= sessions.in_session
    return out


def _stop_levels(
    df: pd.DataFrame, entry: StopEntry, sessions: Sessions | None
) -> tuple[pd.Series, pd.Series]:
    """Upper and lower resting-order levels, as known at each bar's OPEN.

    Session extremes are already open-time knowledge: the window has
    closed by the first bar that can read them. Every other operand is
    computed from a bar's CLOSE, so it is shifted one bar — otherwise a
    level derived from bar i would be used to fill inside bar i.
    """
    empty = pd.Series(float("nan"), index=df.index)

    def level(op: Operand | None, sign: float) -> pd.Series:
        if op is None:
            return empty
        base = _operand_series(df, op, sessions)
        if op.kind not in ("session_high", "session_low"):
            base = base.shift(1)
        return base + sign * _offset_points(df, entry, base)

    return level(entry.upper_level, +1.0), level(entry.lower_level, -1.0)


def _offset_points(df: pd.DataFrame, entry: StopEntry, level: pd.Series) -> pd.Series:
    """How far outside the level the orders rest."""
    if entry.offset_mode == "points":
        return pd.Series(entry.offset_value, index=df.index)
    if entry.offset_mode == "pct":
        return level * entry.offset_value / 100.0
    # ATR is a close-derived indicator, so it is lagged for the same
    # reason the level operands above are.
    return _atr(df, entry.atr_period).shift(1) * entry.offset_value


def _bracket_level(entry: float, bracket: Bracket | None, sign: float, side: float) -> float | None:
    """side=-1 for stop (against the position), +1 for target."""
    if bracket is None:
        return None
    points = bracket.value if bracket.mode == "points" else entry * bracket.value / 100.0
    return entry + sign * side * points


def evaluate(df: pd.DataFrame, defn: StrategyDefinition) -> list[Trade]:
    """Run the strategy over bars (columns: ts, open, high, low, close)."""
    if df.empty:
        return []
    df = df.reset_index(drop=True)
    sessions = _sessions_for(df, defn)
    # Entries are gated by the filters; exits are not (you must be able
    # to leave a position even when a filter has since turned false).
    el = entry_signal(df, defn, "long", sessions)
    es = entry_signal(df, defn, "short", sessions)
    xl = _condition_series(df, defn.exit_long, sessions)
    xs = _condition_series(df, defn.exit_short, sessions)

    stop = defn.stop_entry
    upper = lower = orders_live = None
    if stop is not None:
        upper, lower = _stop_levels(df, stop, sessions)
        # Resting orders answer to the same filters as signal entries, read
        # at the previous close — the last information available before the
        # bar they could fill in.
        orders_live = _filter_mask(df, defn, sessions).shift(1).fillna(False).astype(bool)
        if sessions is not None:
            orders_live &= sessions.in_session
            if stop.active_from is not None:
                orders_live &= sessions.since(stop.active_from)

    trades: list[Trade] = []
    pos_dir: Literal["long", "short"] | None = None
    entry_ts: datetime | None = None
    entry_price = 0.0
    entry_i = -1
    sl_level: float | None = None
    tp_level: float | None = None

    def close_position(ts: datetime, price: float, reason: ExitReason) -> None:
        nonlocal pos_dir
        assert pos_dir is not None and entry_ts is not None
        trades.append(Trade(
            direction=pos_dir, entry_ts=entry_ts, entry_price=entry_price,
            exit_ts=ts, exit_price=price, exit_reason=reason,
            sl_level=sl_level, tp_level=tp_level,
        ))
        pos_dir = None

    def open_position(direction: Literal["long", "short"], i: int, price: float | None = None) -> None:
        nonlocal pos_dir, entry_ts, entry_price, entry_i, sl_level, tp_level
        pos_dir = direction
        entry_i = i
        entry_ts = df.at[i, "ts"]
        # Signal entries fill at the bar's open; a resting order fills at
        # its own level somewhere inside the bar.
        entry_price = float(df.at[i, "open"]) if price is None else price
        sign = 1.0 if direction == "long" else -1.0
        sl_level = _bracket_level(entry_price, defn.sl, sign, -1.0)
        tp_level = _bracket_level(entry_price, defn.tp, sign, +1.0)

    def check_brackets(i: int) -> None:
        """Resolve SL/TP inside bar i. SL wins a bar that touches both."""
        if pos_dir is None or (sl_level is None and tp_level is None):
            return
        ts = df.at[i, "ts"]
        o, h, low = float(df.at[i, "open"]), float(df.at[i, "high"]), float(df.at[i, "low"])
        sign = 1.0 if pos_dir == "long" else -1.0
        stop_hit = sl_level is not None and (low <= sl_level if sign > 0 else h >= sl_level)
        target_hit = tp_level is not None and (h >= tp_level if sign > 0 else low <= tp_level)
        if stop_hit:  # SL first: both-in-one-bar books as the loss
            assert sl_level is not None
            fill = sl_level
            if i > entry_i:  # gap-through opens fill at the open
                fill = min(sl_level, o) if sign > 0 else max(sl_level, o)
            close_position(ts, float(fill), "sl")
        elif target_hit:
            close_position(ts, float(tp_level), "tp")  # type: ignore[arg-type]

    pending: Literal["long", "short", "exit", "reverse_long", "reverse_short"] | None = None

    # Per-session state, reset on every rollover.
    cap = defn.max_trades_per_session
    cur_sid: object = None
    sess_trades = 0
    sess_blocked = False   # an unresolvable OCO tie stands the session down
    oco_filled = False

    def under_cap() -> bool:
        return cap is None or sess_trades < cap

    n = len(df)
    for i in range(n):
        ts = df.at[i, "ts"]
        o, h, low = float(df.at[i, "open"]), float(df.at[i, "high"]), float(df.at[i, "low"])
        in_session = sessions is None or bool(sessions.in_session.iat[i])

        if sessions is not None:
            sid_i = sessions.sid.iat[i]
            if sid_i != cur_sid:
                cur_sid, sess_trades, sess_blocked, oco_filled = sid_i, 0, False, False

        # 1. Execute the action scheduled at the previous bar's close. An
        #    entry scheduled on a session's last bar is dropped rather than
        #    opened outside the session it was reasoned about.
        if pending is not None:
            may_enter = in_session and under_cap()
            if pending == "exit" and pos_dir is not None:
                close_position(ts, o, "signal")
            elif pending in ("reverse_long", "reverse_short") and pos_dir is not None:
                close_position(ts, o, "signal")
                if may_enter:
                    open_position("long" if pending == "reverse_long" else "short", i)
                    sess_trades += 1
            elif pending in ("long", "short") and pos_dir is None and may_enter:
                open_position("long" if pending == "long" else "short", i)
                sess_trades += 1
            pending = None

        # 2. Bracket monitoring inside bar i (skip nothing on the entry
        #    bar — entry was at this bar's open, its range counts).
        check_brackets(i)

        # 3. Resting orders. Unlike a signal these fill INTRABAR, so the
        #    bracket is re-checked on this same bar — the range around the
        #    fill already happened and skipping it would flatter the result.
        if (
            stop is not None
            and pos_dir is None
            and not sess_blocked
            and not oco_filled
            and under_cap()
            and bool(orders_live.iat[i])  # type: ignore[union-attr]
        ):
            up = float(upper.iat[i])  # type: ignore[union-attr]
            lo = float(lower.iat[i])  # type: ignore[union-attr]
            hit_up = up == up and h >= up  # NaN-safe: a NaN level is no order
            hit_lo = lo == lo and low <= lo
            if hit_up and hit_lo:
                # Both levels inside one bar: the touch order is unknowable
                # at this resolution. Resolve by proximity to the open; a
                # dead tie is unresolvable, so the session stands down.
                d_up, d_lo = abs(o - up), abs(o - lo)
                if d_up == d_lo:
                    sess_blocked, hit_up, hit_lo = True, False, False
                else:
                    hit_up = d_up < d_lo
                    hit_lo = not hit_up
            if hit_up or hit_lo:
                level = up if hit_up else lo
                if stop.mode == "breakout":
                    direction: Literal["long", "short"] = "long" if hit_up else "short"
                    # Breakout orders are STOP orders: a bar that already
                    # OPENS beyond the level fills near that open, not back
                    # at the level. Fade orders are LIMIT orders, which fill
                    # at the level or better, so booking the level is
                    # already the conservative read.
                    level = max(level, o) if hit_up else min(level, o)
                else:
                    direction = "short" if hit_up else "long"
                open_position(direction, i, level)
                sess_trades += 1
                if stop.oco:
                    oco_filled = True
                check_brackets(i)

        # 4. Forced flat: a session position is never carried overnight.
        if pos_dir is not None and sessions is not None and bool(sessions.last_of_session.iat[i]):
            close_position(ts, float(df.at[i, "close"]), "eod")
            pending = None

        # 5. Evaluate signals at this bar's close → schedule for i+1.
        if i == n - 1:
            break
        if not in_session:
            continue
        if pos_dir == "long":
            if bool(es.iat[i]):
                pending = "reverse_short"
            elif bool(xl.iat[i]):
                pending = "exit"
        elif pos_dir == "short":
            if bool(el.iat[i]):
                pending = "reverse_long"
            elif bool(xs.iat[i]):
                pending = "exit"
        else:
            long_sig, short_sig = bool(el.iat[i]), bool(es.iat[i])
            if long_sig and not short_sig:
                pending = "long"
            elif short_sig and not long_sig:
                pending = "short"
            # both at once: contradictory — stand aside

    if pos_dir is not None:
        last = n - 1
        close_position(df.at[last, "ts"], float(df.at[last, "close"]), "end")
    return trades
