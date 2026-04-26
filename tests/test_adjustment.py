"""Unit tests for price adjustment logic.

These tests are pure — no database or network calls.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.adjustment import (
    RollEvent,
    apply_absolute_adjustment,
    apply_ratio_adjustment,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bar(ts: date, o: float, h: float, lo: float, c: float, v: int = 1000) -> dict:
    """Build a minimal bar dict for testing."""
    return {
        "ts": datetime(ts.year, ts.month, ts.day, 9, 0, tzinfo=UTC),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": v,
    }


ROLL_A = RollEvent(
    instrument="NQ",
    roll_date=date(2024, 3, 14),
    price_diff=Decimal("50.00"),
    price_ratio=Decimal("1.002500"),   # 18050 / 18000 ≈ 1.0028
)

ROLL_B = RollEvent(
    instrument="NQ",
    roll_date=date(2024, 6, 13),
    price_diff=Decimal("30.00"),
    price_ratio=Decimal("1.001500"),
)


# ---------------------------------------------------------------------------
# apply_ratio_adjustment
# ---------------------------------------------------------------------------

class TestRatioAdjustment:
    def test_no_rolls_returns_bars_unchanged(self) -> None:
        bars = [_bar(date(2024, 1, 10), 18000, 18100, 17900, 18050)]
        result = apply_ratio_adjustment(bars, rolls=[])
        assert result == bars

    def test_bars_after_all_rolls_are_unchanged(self) -> None:
        bar = _bar(date(2024, 7, 1), 19000, 19100, 18900, 19050)
        result = apply_ratio_adjustment([bar], rolls=[ROLL_A, ROLL_B])
        assert result[0]["open"] == 19000
        assert result[0]["close"] == 19050

    def test_bar_before_first_roll_gets_product_of_all_ratios(self) -> None:
        bar = _bar(date(2024, 1, 5), 18000, 18100, 17900, 18050)
        result = apply_ratio_adjustment([bar], rolls=[ROLL_A, ROLL_B])
        # cumulative ratio = ROLL_A.ratio * ROLL_B.ratio
        expected_ratio = ROLL_A.price_ratio * ROLL_B.price_ratio
        assert result[0]["open"] == (Decimal("18000") * expected_ratio).quantize(Decimal("0.0001"))
        assert result[0]["high"] == (Decimal("18100") * expected_ratio).quantize(Decimal("0.0001"))
        assert result[0]["volume"] == bar["volume"]   # volume never adjusted

    def test_bar_between_two_rolls_gets_only_later_ratio(self) -> None:
        bar = _bar(date(2024, 4, 1), 18500, 18600, 18400, 18550)
        result = apply_ratio_adjustment([bar], rolls=[ROLL_A, ROLL_B])
        # Only ROLL_B applies to bars between ROLL_A and ROLL_B
        expected = (Decimal("18500") * ROLL_B.price_ratio).quantize(Decimal("0.0001"))
        assert result[0]["open"] == expected

    def test_roll_date_itself_is_not_adjusted(self) -> None:
        """Bars on the roll date belong to the new contract — no adjustment."""
        bar = _bar(ROLL_A.roll_date, 18050, 18100, 18000, 18080)
        result = apply_ratio_adjustment([bar], rolls=[ROLL_A])
        assert result[0]["open"] == 18050

    def test_returns_new_list_without_mutating_input(self) -> None:
        bars = [_bar(date(2024, 1, 5), 18000, 18100, 17900, 18050)]
        original_open = bars[0]["open"]
        apply_ratio_adjustment(bars, rolls=[ROLL_A])
        assert bars[0]["open"] == original_open   # original untouched

    def test_rolls_unsorted_still_correct(self) -> None:
        bar_early = _bar(date(2024, 1, 5), 18000, 18100, 17900, 18050)
        result_sorted = apply_ratio_adjustment([bar_early], rolls=[ROLL_A, ROLL_B])
        result_unsorted = apply_ratio_adjustment([bar_early], rolls=[ROLL_B, ROLL_A])
        assert result_sorted[0]["open"] == result_unsorted[0]["open"]

    def test_single_bar_single_roll(self) -> None:
        bar = _bar(date(2024, 3, 1), 18000, 18000, 18000, 18000)
        roll = RollEvent(
            instrument="NQ",
            roll_date=date(2024, 3, 14),
            price_diff=Decimal("50"),
            price_ratio=Decimal("1.00277778"),  # 18050/18000
        )
        result = apply_ratio_adjustment([bar], rolls=[roll])
        expected = (Decimal("18000") * Decimal("1.00277778")).quantize(Decimal("0.0001"))
        assert result[0]["open"] == expected


# ---------------------------------------------------------------------------
# apply_absolute_adjustment
# ---------------------------------------------------------------------------

class TestAbsoluteAdjustment:
    def test_no_rolls_returns_bars_unchanged(self) -> None:
        bars = [_bar(date(2024, 1, 10), 18000, 18100, 17900, 18050)]
        result = apply_absolute_adjustment(bars, rolls=[])
        assert result == bars

    def test_bars_after_all_rolls_unchanged(self) -> None:
        bar = _bar(date(2024, 7, 1), 19000, 19100, 18900, 19050)
        result = apply_absolute_adjustment([bar], rolls=[ROLL_A, ROLL_B])
        assert result[0]["close"] == 19050

    def test_bar_before_first_roll_gets_sum_of_all_diffs(self) -> None:
        bar = _bar(date(2024, 1, 5), 18000, 18100, 17900, 18050)
        result = apply_absolute_adjustment([bar], rolls=[ROLL_A, ROLL_B])
        total_diff = ROLL_A.price_diff + ROLL_B.price_diff   # 80.00
        assert result[0]["open"] == (Decimal("18000") + total_diff).quantize(Decimal("0.0001"))

    def test_bar_between_rolls_gets_only_later_diff(self) -> None:
        bar = _bar(date(2024, 4, 1), 18500, 18600, 18400, 18550)
        result = apply_absolute_adjustment([bar], rolls=[ROLL_A, ROLL_B])
        assert result[0]["open"] == (Decimal("18500") + ROLL_B.price_diff).quantize(Decimal("0.0001"))

    def test_volume_is_never_modified(self) -> None:
        bar = _bar(date(2024, 1, 5), 18000, 18100, 17900, 18050, v=99999)
        result = apply_absolute_adjustment([bar], rolls=[ROLL_A])
        assert result[0]["volume"] == 99999


# ---------------------------------------------------------------------------
# Datetime-variant ts fields
# ---------------------------------------------------------------------------

class TestTsVariants:
    """ts field may be date, datetime, or ISO string — all must work."""

    def test_date_object(self) -> None:
        bar = {"ts": date(2024, 1, 5), "open": 18000, "high": 18100, "low": 17900, "close": 18050, "volume": 1}
        result = apply_ratio_adjustment([bar], rolls=[ROLL_A])
        assert result[0]["open"] != 18000  # adjusted

    def test_iso_string(self) -> None:
        bar = {"ts": "2024-01-05T09:00:00+00:00", "open": 18000, "high": 18100, "low": 17900, "close": 18050, "volume": 1}
        result = apply_ratio_adjustment([bar], rolls=[ROLL_A])
        assert result[0]["open"] != 18000
