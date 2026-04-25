"""Unit tests for contract roll detection utilities."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fetcher.roll_detector import (
    compute_roll_factors,
    is_valid_contract,
    next_contract,
    parse_contract_code,
)


class TestParseContractCode:
    def test_valid_nq(self) -> None:
        assert parse_contract_code("NQH25") == ("NQ", "H", 25)

    def test_valid_es_lower(self) -> None:
        assert parse_contract_code("esm25") == ("ES", "M", 25)

    def test_valid_rty(self) -> None:
        assert parse_contract_code("RTYZ26") == ("RTY", "Z", 26)

    def test_invalid_returns_none(self) -> None:
        assert parse_contract_code("NQ=F") is None
        assert parse_contract_code("NQ") is None
        assert parse_contract_code("NQX25") is None  # X not a valid month code


class TestIsValidContract:
    def test_valid(self) -> None:
        assert is_valid_contract("NQM25") is True

    def test_invalid(self) -> None:
        assert is_valid_contract("NQ=F") is False
        assert is_valid_contract("") is False


class TestNextContract:
    def test_h_to_m(self) -> None:
        assert next_contract("NQH25") == "NQM25"

    def test_m_to_u(self) -> None:
        assert next_contract("ESM25") == "ESU25"

    def test_u_to_z(self) -> None:
        assert next_contract("YMU25") == "YMZ25"

    def test_z_rolls_to_next_year(self) -> None:
        assert next_contract("NQZ25") == "NQH26"

    def test_year_boundary_rty(self) -> None:
        assert next_contract("RTYZ26") == "RTYH27"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            next_contract("NQ=F")


class TestComputeRollFactors:
    def test_typical_roll(self) -> None:
        diff, ratio = compute_roll_factors(old_close=18000.0, new_open=18050.0)
        assert diff == Decimal("50.0000")
        assert ratio == Decimal("1.00277778")

    def test_negative_diff(self) -> None:
        """Roll can go either direction."""
        diff, ratio = compute_roll_factors(old_close=18050.0, new_open=18000.0)
        assert diff == Decimal("-50.0000")
        assert ratio < Decimal("1")

    def test_zero_diff_gives_ratio_one(self) -> None:
        diff, ratio = compute_roll_factors(old_close=18000.0, new_open=18000.0)
        assert diff == Decimal("0.0000")
        assert ratio == Decimal("1.00000000")

    def test_precision_4_decimal_places(self) -> None:
        diff, _ = compute_roll_factors(18000.0, 18050.123456)
        assert str(diff).find(".") != -1
        decimal_places = len(str(diff).split(".")[1])
        assert decimal_places == 4
