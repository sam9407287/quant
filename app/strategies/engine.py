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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from app.ml.features import build_feature
from app.ml.schemas import FeatureSpec
from app.strategies.schemas import Bracket, Condition, Operand, StrategyDefinition

ExitReason = Literal["signal", "sl", "tp", "end"]


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


def _operand_series(df: pd.DataFrame, op: Operand) -> pd.Series:
    close = df["close"].astype(float)
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


def _condition_series(df: pd.DataFrame, cond: Condition | None) -> pd.Series:
    """Boolean series: True at bar i = condition holds at bar i's close."""
    if cond is None:
        return pd.Series(False, index=df.index)
    left = _operand_series(df, cond.left)
    right = _operand_series(df, cond.right)
    if cond.op == "gt":
        out = left > right
    elif cond.op == "lt":
        out = left < right
    elif cond.op == "cross_above":
        out = (left > right) & (left.shift(1) <= right.shift(1))
    else:  # cross_below
        out = (left < right) & (left.shift(1) >= right.shift(1))
    return out.fillna(False)


def _filter_mask(df: pd.DataFrame, defn: StrategyDefinition) -> pd.Series:
    """AND of every filter condition — the standing gate on all entries."""
    mask = pd.Series(True, index=df.index)
    for f in defn.filters:
        mask &= _condition_series(df, f)
    return mask


def entry_signal(df: pd.DataFrame, defn: StrategyDefinition, direction: str) -> pd.Series:
    """Boolean entry series for a direction: trigger AND all filters.

    Shared by the engine and the signal test so both agree on when a
    strategy's entry actually fires.
    """
    trigger = defn.entry_long if direction == "long" else defn.entry_short
    return _condition_series(df, trigger) & _filter_mask(df, defn)


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
    # Entries are gated by the filters; exits are not (you must be able
    # to leave a position even when a filter has since turned false).
    el = entry_signal(df, defn, "long")
    es = entry_signal(df, defn, "short")
    xl = _condition_series(df, defn.exit_long)
    xs = _condition_series(df, defn.exit_short)

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

    def open_position(direction: Literal["long", "short"], i: int) -> None:
        nonlocal pos_dir, entry_ts, entry_price, entry_i, sl_level, tp_level
        pos_dir = direction
        entry_i = i
        entry_ts = df.at[i, "ts"]
        entry_price = float(df.at[i, "open"])
        sign = 1.0 if direction == "long" else -1.0
        sl_level = _bracket_level(entry_price, defn.sl, sign, -1.0)
        tp_level = _bracket_level(entry_price, defn.tp, sign, +1.0)

    pending: Literal["long", "short", "exit", "reverse_long", "reverse_short"] | None = None

    n = len(df)
    for i in range(n):
        ts = df.at[i, "ts"]
        o, h, low = float(df.at[i, "open"]), float(df.at[i, "high"]), float(df.at[i, "low"])

        # 1. Execute the action scheduled at the previous bar's close.
        if pending is not None:
            if pending == "exit" and pos_dir is not None:
                close_position(ts, o, "signal")
            elif pending in ("reverse_long", "reverse_short") and pos_dir is not None:
                close_position(ts, o, "signal")
                open_position("long" if pending == "reverse_long" else "short", i)
            elif pending in ("long", "short") and pos_dir is None:
                open_position("long" if pending == "long" else "short", i)
            pending = None

        # 2. Bracket monitoring inside bar i (skip nothing on the entry
        #    bar — entry was at this bar's open, its range counts).
        if pos_dir is not None and (sl_level is not None or tp_level is not None):
            sign = 1.0 if pos_dir == "long" else -1.0
            stop_hit = sl_level is not None and (
                low <= sl_level if sign > 0 else h >= sl_level
            )
            target_hit = tp_level is not None and (
                h >= tp_level if sign > 0 else low <= tp_level
            )
            if stop_hit:  # SL first: both-in-one-bar books as the loss
                assert sl_level is not None
                fill = sl_level
                if i > entry_i:  # gap-through opens fill at the open
                    fill = min(sl_level, o) if sign > 0 else max(sl_level, o)
                close_position(ts, float(fill), "sl")
            elif target_hit:
                close_position(ts, float(tp_level), "tp")  # type: ignore[arg-type]

        # 3. Evaluate signals at this bar's close → schedule for i+1.
        if i == n - 1:
            break
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
