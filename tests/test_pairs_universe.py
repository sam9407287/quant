"""Integrity tests for the pairs universe and contract specs (ADR-010 phase 1)."""

from __future__ import annotations

import re

import pytest

from app.core.instruments import INSTRUMENT_REGISTRY
from app.pairs.universe import (
    ALL_TICKERS,
    DEFAULT_PAIRS,
    UNIVERSE,
    get_instrument,
    price_field_for,
    registry_symbol_for,
    tickers_by_kind,
)


class TestUniverse:
    def test_tickers_unique_and_keyed_consistently(self) -> None:
        assert len(ALL_TICKERS) == len(set(ALL_TICKERS))
        for ticker, inst in UNIVERSE.items():
            assert inst.ticker == ticker

    def test_every_futures_has_positive_specs(self) -> None:
        for ticker in tickers_by_kind("futures"):
            inst = UNIVERSE[ticker]
            assert inst.contracts, ticker
            for c in inst.contracts:
                assert c.multiplier > 0 and c.tick_size > 0, (ticker, c.code)
            assert inst.roll_months_per_year > 0, ticker

    def test_micro_is_smaller_than_standard(self) -> None:
        for inst in UNIVERSE.values():
            if inst.micro is not None:
                assert inst.micro.multiplier < inst.standard.multiplier, inst.ticker
                assert inst.smallest is inst.micro

    def test_shares_behave_as_unit_contract(self) -> None:
        spy = get_instrument("SPY")
        assert spy.contracts == ()
        (spec,) = spy.tradeable
        assert spec.multiplier == 1.0 and spec.code == "SPY" and spec.micro is False
        assert spy.roll_months_per_year == 0

    def test_settlement_time_format(self) -> None:
        for inst in UNIVERSE.values():
            assert re.fullmatch(r"\d{2}:\d{2}", inst.settlement_et), inst.ticker

    def test_registry_links_resolve(self) -> None:
        for inst in UNIVERSE.values():
            if inst.registry_symbol is not None:
                assert inst.registry_symbol in INSTRUMENT_REGISTRY, inst.ticker
                assert INSTRUMENT_REGISTRY[inst.registry_symbol].yfinance_ticker == inst.ticker
        assert registry_symbol_for("NQ=F") == "NQ"
        assert registry_symbol_for("6C=F") is None
        assert registry_symbol_for("SPY") is None

    def test_price_field_split(self) -> None:
        assert price_field_for("ES=F") == "close"
        assert price_field_for("EWA") == "adj_close"
        assert price_field_for("KO") == "adj_close"

    def test_unknown_ticker_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown pairs-universe ticker"):
            get_instrument("NOPE")


class TestDefaultPairs:
    def test_ten_pairs_from_the_brief(self) -> None:
        assert len(DEFAULT_PAIRS) == 10
        names = [p.name for p in DEFAULT_PAIRS]
        assert len(names) == len(set(names))

    def test_legs_exist_and_differ(self) -> None:
        for p in DEFAULT_PAIRS:
            assert p.y in UNIVERSE and p.x in UNIVERSE, p.name
            assert p.y != p.x
            assert p.rationale

    def test_tick_value_math(self) -> None:
        es = get_instrument("ES=F").standard
        assert es.tick_value == pytest.approx(12.5)
        zn = get_instrument("ZN=F").standard
        assert zn.tick_value == pytest.approx(15.625)
