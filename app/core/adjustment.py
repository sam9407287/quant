"""Price adjustment logic for continuous futures contracts.

Futures contracts expire quarterly. When rolling from one contract to the
next, a price gap appears because the two contracts rarely trade at the same
price. This module applies backward price adjustments so that historical bars
form a smooth, uninterrupted series suitable for technical analysis.

Two adjustment methods are provided:
- Ratio (recommended): multiplies prior bars by new_open / old_close.
  Percentage moves are preserved; absolute levels shift.
- Absolute: adds (new_open - old_close) to prior bars.
  Dollar moves are preserved; can produce negative prices for old data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RollEvent:
    """A single contract roll with its price adjustment factors."""

    instrument: str
    roll_date: date
    price_diff: Decimal   # new_open - old_close  (absolute adjustment)
    price_ratio: Decimal  # new_open / old_close  (ratio adjustment)


def apply_ratio_adjustment(
    bars: list[dict],
    rolls: list[RollEvent],
    ts_key: str = "ts",
) -> list[dict]:
    """Return bars with ratio (back-adjusted) prices applied.

    Bars are processed in ascending timestamp order. For each roll event,
    all bars whose timestamp is strictly before the roll date have their
    OHLC multiplied by the cumulative product of all ratios from that roll
    onward to the end of the rolls list.

    Args:
        bars:   List of bar dicts with keys ts, open, high, low, close, volume.
        rolls:  Roll events sorted ascending by roll_date.
        ts_key: Key used to access the timestamp field.

    Returns:
        New list of bar dicts with adjusted OHLC values.
    """
    if not rolls:
        return bars

    sorted_rolls = sorted(rolls, key=lambda r: r.roll_date)

    # Precompute cumulative ratio for bars before each roll boundary.
    # A bar before roll[i] needs product(ratio[i], ratio[i+1], ..., ratio[-1]).
    cumulative: list[Decimal] = []
    running = Decimal("1")
    for roll in reversed(sorted_rolls):
        running *= roll.price_ratio
        cumulative.insert(0, running)

    result: list[dict] = []
    for bar in bars:
        bar_date = _to_date(bar[ts_key])
        factor = Decimal("1")
        for i, roll in enumerate(sorted_rolls):
            if bar_date < roll.roll_date:
                factor = cumulative[i]
                break

        if factor == Decimal("1"):
            result.append(bar)
        else:
            result.append(
                {
                    **bar,
                    "open": _round4(Decimal(str(bar["open"])) * factor),
                    "high": _round4(Decimal(str(bar["high"])) * factor),
                    "low": _round4(Decimal(str(bar["low"])) * factor),
                    "close": _round4(Decimal(str(bar["close"])) * factor),
                }
            )
    return result


def apply_absolute_adjustment(
    bars: list[dict],
    rolls: list[RollEvent],
    ts_key: str = "ts",
) -> list[dict]:
    """Return bars with absolute (additive) price adjustment applied.

    Each bar whose timestamp is before a roll date has the cumulative sum
    of all subsequent price_diff values added to its OHLC.

    Args:
        bars:   List of bar dicts.
        rolls:  Roll events sorted ascending by roll_date.
        ts_key: Key used to access the timestamp field.

    Returns:
        New list of bar dicts with adjusted OHLC values.
    """
    if not rolls:
        return bars

    sorted_rolls = sorted(rolls, key=lambda r: r.roll_date)

    cumulative: list[Decimal] = []
    running = Decimal("0")
    for roll in reversed(sorted_rolls):
        running += roll.price_diff
        cumulative.insert(0, running)

    result: list[dict] = []
    for bar in bars:
        bar_date = _to_date(bar[ts_key])
        offset = Decimal("0")
        for i, roll in enumerate(sorted_rolls):
            if bar_date < roll.roll_date:
                offset = cumulative[i]
                break

        if offset == Decimal("0"):
            result.append(bar)
        else:
            result.append(
                {
                    **bar,
                    "open": _round4(Decimal(str(bar["open"])) + offset),
                    "high": _round4(Decimal(str(bar["high"])) + offset),
                    "low": _round4(Decimal(str(bar["low"])) + offset),
                    "close": _round4(Decimal(str(bar["close"])) + offset),
                }
            )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_date(ts: object) -> date:
    """Extract a date from a datetime, date, or ISO string."""
    if hasattr(ts, "date"):
        return ts.date()  # type: ignore[return-value]
    if isinstance(ts, date):
        return ts
    # ISO string fallback
    return date.fromisoformat(str(ts)[:10])


def _round4(value: Decimal) -> Decimal:
    """Round to 4 decimal places (standard for futures OHLC)."""
    return value.quantize(Decimal("0.0001"))
