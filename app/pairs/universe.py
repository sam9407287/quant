"""Tradeable universe for the pairs lab: tickers, asset groups, contract specs.

Kept apart from `app.core.instruments` on purpose. That registry drives the
1m fetcher and the chart; adding an ETF or a stock there would make the
fetcher crawl it every day. The pairs lab only needs daily closes, and its
universe is wider (ETFs, single stocks, more futures), so it owns its own
table and links back to the registry symbol where one exists (for
`roll_calendar` lookups and the synchronised 1m snapshot source).

Contract multipliers and tick sizes follow the CME / CBOT / COMEX / NYMEX /
ICE specifications as of 2026 and are expressed per 1.0 move of the price
*as yfinance quotes it* (grains in cents per bushel, FX in USD per unit).
They feed sizing and cost math only — verify against the exchange before
trading real size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.core.instruments import INSTRUMENT_REGISTRY

AssetGroup = Literal[
    "equity_index", "rates", "fx", "metal", "energy", "grain", "soft", "livestock",
    "etf", "stock",
]
InstrumentKind = Literal["futures", "etf", "stock"]


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """One listed contract: USD value of a 1.0 price move and its tick."""

    code: str
    multiplier: float
    tick_size: float
    micro: bool = False

    @property
    def tick_value(self) -> float:
        return self.multiplier * self.tick_size


@dataclass(frozen=True, slots=True)
class PairInstrument:
    """A member of the pairs universe and everything sizing needs to know."""

    ticker: str
    name: str
    group: AssetGroup
    kind: InstrumentKind
    exchange: str
    # Local (America/New_York) time at which the daily settlement/close is
    # struck. Legs of a cross-group pair settle at different times, which
    # the guide and the snapshot source both account for.
    settlement_et: str
    contracts: tuple[ContractSpec, ...] = ()
    registry_symbol: str | None = None
    # Contract months per year — the proxy used for roll-cost frequency when
    # no roll calendar exists for the instrument. 0 means never rolls.
    roll_months_per_year: int = 0

    @property
    def tradeable(self) -> tuple[ContractSpec, ...]:
        """Contracts to size with; shares behave as a 1x contract with 0.01 tick."""
        if self.contracts:
            return self.contracts
        return (ContractSpec(code=self.ticker, multiplier=1.0, tick_size=0.01),)

    @property
    def standard(self) -> ContractSpec:
        return next(c for c in self.tradeable if not c.micro)

    @property
    def micro(self) -> ContractSpec | None:
        return next((c for c in self.tradeable if c.micro), None)

    @property
    def smallest(self) -> ContractSpec:
        return min(self.tradeable, key=lambda c: c.multiplier)


def _fut(
    ticker: str,
    name: str,
    group: AssetGroup,
    exchange: str,
    settlement_et: str,
    contracts: tuple[ContractSpec, ...],
    *,
    registry: str | None = None,
    rolls: int,
) -> PairInstrument:
    return PairInstrument(
        ticker=ticker, name=name, group=group, kind="futures", exchange=exchange,
        settlement_et=settlement_et, contracts=contracts, registry_symbol=registry,
        roll_months_per_year=rolls,
    )


def _etf(ticker: str, name: str, group: AssetGroup = "etf") -> PairInstrument:
    return PairInstrument(
        ticker=ticker, name=name, group=group, kind="etf", exchange="NYSE Arca",
        settlement_et="16:00",
    )


def _stock(ticker: str, name: str) -> PairInstrument:
    return PairInstrument(
        ticker=ticker, name=name, group="stock", kind="stock", exchange="US",
        settlement_et="16:00",
    )


_INSTRUMENTS: tuple[PairInstrument, ...] = (
    # ── Equity indices (settle 15:00 CT = 16:00 ET) ───────────────────────
    _fut("NQ=F", "E-mini Nasdaq-100", "equity_index", "CME", "16:00",
         (ContractSpec("NQ", 20.0, 0.25), ContractSpec("MNQ", 2.0, 0.25, micro=True)),
         registry="NQ", rolls=4),
    _fut("ES=F", "E-mini S&P 500", "equity_index", "CME", "16:00",
         (ContractSpec("ES", 50.0, 0.25), ContractSpec("MES", 5.0, 0.25, micro=True)),
         registry="ES", rolls=4),
    _fut("YM=F", "E-mini Dow", "equity_index", "CBOT", "16:00",
         (ContractSpec("YM", 5.0, 1.0), ContractSpec("MYM", 0.5, 1.0, micro=True)),
         registry="YM", rolls=4),
    _fut("RTY=F", "E-mini Russell 2000", "equity_index", "CME", "16:00",
         (ContractSpec("RTY", 50.0, 0.1), ContractSpec("M2K", 5.0, 0.1, micro=True)),
         registry="RTY", rolls=4),
    _fut("NKD=F", "Nikkei 225 (USD)", "equity_index", "CME", "16:00",
         (ContractSpec("NKD", 5.0, 5.0),), registry="NKD", rolls=4),
    # ── Rates (settle 14:00 CT = 15:00 ET; prices in points of 100) ───────
    _fut("ZT=F", "2-Year T-Note", "rates", "CBOT", "15:00",
         (ContractSpec("ZT", 2000.0, 0.0078125),), registry="ZT", rolls=4),
    _fut("ZF=F", "5-Year T-Note", "rates", "CBOT", "15:00",
         (ContractSpec("ZF", 1000.0, 0.0078125),), registry="ZF", rolls=4),
    _fut("ZN=F", "10-Year T-Note", "rates", "CBOT", "15:00",
         (ContractSpec("ZN", 1000.0, 0.015625),), registry="ZN", rolls=4),
    _fut("ZB=F", "30-Year T-Bond", "rates", "CBOT", "15:00",
         (ContractSpec("ZB", 1000.0, 0.03125),), registry="ZB", rolls=4),
    # ── FX (settle 14:00 CT = 15:00 ET) ───────────────────────────────────
    _fut("6E=F", "Euro FX", "fx", "CME", "15:00",
         (ContractSpec("6E", 125_000.0, 0.00005), ContractSpec("M6E", 12_500.0, 0.0001, micro=True)),
         registry="6E", rolls=4),
    _fut("6B=F", "British Pound", "fx", "CME", "15:00",
         (ContractSpec("6B", 62_500.0, 0.0001), ContractSpec("M6B", 6_250.0, 0.0001, micro=True)),
         registry="6B", rolls=4),
    _fut("6J=F", "Japanese Yen", "fx", "CME", "15:00",
         (ContractSpec("6J", 12_500_000.0, 0.0000005),), registry="6J", rolls=4),
    _fut("6A=F", "Australian Dollar", "fx", "CME", "15:00",
         (ContractSpec("6A", 100_000.0, 0.00005), ContractSpec("M6A", 10_000.0, 0.0001, micro=True)),
         registry="6A", rolls=4),
    _fut("6C=F", "Canadian Dollar", "fx", "CME", "15:00",
         (ContractSpec("6C", 100_000.0, 0.00005), ContractSpec("MCD", 10_000.0, 0.0001, micro=True)),
         rolls=4),
    # ── Metals (COMEX settles 13:30 ET; NYMEX PGMs 13:05 ET) ──────────────
    _fut("GC=F", "Gold", "metal", "COMEX", "13:30",
         (ContractSpec("GC", 100.0, 0.1), ContractSpec("MGC", 10.0, 0.1, micro=True)),
         registry="GC", rolls=6),
    _fut("SI=F", "Silver", "metal", "COMEX", "13:25",
         (ContractSpec("SI", 5000.0, 0.005), ContractSpec("SIL", 1000.0, 0.005, micro=True)),
         registry="SI", rolls=5),
    _fut("HG=F", "Copper", "metal", "COMEX", "13:00",
         (ContractSpec("HG", 25_000.0, 0.0005), ContractSpec("MHG", 2_500.0, 0.0005, micro=True)),
         registry="HG", rolls=5),
    _fut("PL=F", "Platinum", "metal", "NYMEX", "13:05",
         (ContractSpec("PL", 50.0, 0.1),), registry="PL", rolls=4),
    _fut("PA=F", "Palladium", "metal", "NYMEX", "13:00",
         (ContractSpec("PA", 100.0, 0.5),), registry="PA", rolls=4),
    # ── Energy (NYMEX settles 14:30 ET) ───────────────────────────────────
    _fut("CL=F", "Crude Oil (WTI)", "energy", "NYMEX", "14:30",
         (ContractSpec("CL", 1000.0, 0.01), ContractSpec("MCL", 100.0, 0.01, micro=True)),
         registry="CL", rolls=12),
    _fut("BZ=F", "Brent Crude", "energy", "NYMEX", "14:30",
         (ContractSpec("BZ", 1000.0, 0.01),), registry="BZ", rolls=12),
    _fut("NG=F", "Natural Gas", "energy", "NYMEX", "14:30",
         (ContractSpec("NG", 10_000.0, 0.001), ContractSpec("MNG", 1_000.0, 0.001, micro=True)),
         registry="NG", rolls=12),
    _fut("HO=F", "Heating Oil", "energy", "NYMEX", "14:30",
         (ContractSpec("HO", 42_000.0, 0.0001),), registry="HO", rolls=12),
    _fut("RB=F", "RBOB Gasoline", "energy", "NYMEX", "14:30",
         (ContractSpec("RB", 42_000.0, 0.0001),), registry="RB", rolls=12),
    # ── Grains (CBOT settles 13:20 CT = 14:20 ET; quoted in cents) ────────
    _fut("ZC=F", "Corn", "grain", "CBOT", "14:20",
         (ContractSpec("ZC", 50.0, 0.25), ContractSpec("XC", 10.0, 0.125, micro=True)),
         registry="ZC", rolls=5),
    _fut("ZW=F", "Wheat", "grain", "CBOT", "14:20",
         (ContractSpec("ZW", 50.0, 0.25), ContractSpec("XW", 10.0, 0.125, micro=True)),
         registry="ZW", rolls=5),
    _fut("ZS=F", "Soybeans", "grain", "CBOT", "14:20",
         (ContractSpec("ZS", 50.0, 0.25), ContractSpec("XK", 10.0, 0.125, micro=True)),
         registry="ZS", rolls=7),
    _fut("ZL=F", "Soybean Oil", "grain", "CBOT", "14:20",
         (ContractSpec("ZL", 600.0, 0.01),), registry="ZL", rolls=8),
    _fut("ZM=F", "Soybean Meal", "grain", "CBOT", "14:20",
         (ContractSpec("ZM", 100.0, 0.1),), registry="ZM", rolls=8),
    # ── Softs (ICE US) ────────────────────────────────────────────────────
    _fut("KC=F", "Coffee C", "soft", "ICE", "13:25",
         (ContractSpec("KC", 375.0, 0.05),), registry="KC", rolls=5),
    _fut("SB=F", "Sugar No. 11", "soft", "ICE", "13:00",
         (ContractSpec("SB", 1120.0, 0.01),), registry="SB", rolls=4),
    _fut("CC=F", "Cocoa", "soft", "ICE", "13:30",
         (ContractSpec("CC", 10.0, 1.0),), registry="CC", rolls=5),
    # ── Livestock (CME settles 13:05 CT = 14:05 ET) ───────────────────────
    _fut("HE=F", "Lean Hogs", "livestock", "CME", "14:05",
         (ContractSpec("HE", 400.0, 0.025),), registry="HE", rolls=8),
    _fut("LE=F", "Live Cattle", "livestock", "CME", "14:05",
         (ContractSpec("LE", 400.0, 0.025),), registry="LE", rolls=6),
    # ── ETFs ──────────────────────────────────────────────────────────────
    _etf("SPY", "SPDR S&P 500"),
    _etf("QQQ", "Invesco Nasdaq-100"),
    _etf("DIA", "SPDR Dow Jones"),
    _etf("IWM", "iShares Russell 2000"),
    _etf("EWA", "iShares MSCI Australia"),
    _etf("EWC", "iShares MSCI Canada"),
    _etf("GLD", "SPDR Gold"),
    _etf("SLV", "iShares Silver"),
    _etf("USO", "United States Oil"),
    _etf("BNO", "United States Brent Oil"),
    _etf("XLE", "Energy Select Sector"),
    _etf("XOP", "SPDR Oil & Gas E&P"),
    _etf("TLT", "iShares 20+ Year Treasury"),
    _etf("IEF", "iShares 7-10 Year Treasury"),
    _etf("FXA", "Invesco Australian Dollar"),
    _etf("FXC", "Invesco Canadian Dollar"),
    _etf("XLF", "Financial Select Sector"),
    _etf("KRE", "SPDR Regional Banking"),
    _etf("SMH", "VanEck Semiconductor"),
    _etf("SOXX", "iShares Semiconductor"),
    # ── Single stocks: classic same-industry pairs ────────────────────────
    _stock("KO", "Coca-Cola"),
    _stock("PEP", "PepsiCo"),
    _stock("XOM", "Exxon Mobil"),
    _stock("CVX", "Chevron"),
    _stock("V", "Visa"),
    _stock("MA", "Mastercard"),
    _stock("HD", "Home Depot"),
    _stock("LOW", "Lowe's"),
    _stock("WMT", "Walmart"),
    _stock("TGT", "Target"),
    _stock("UPS", "United Parcel Service"),
    _stock("FDX", "FedEx"),
)

UNIVERSE: dict[str, PairInstrument] = {inst.ticker: inst for inst in _INSTRUMENTS}
ALL_TICKERS: tuple[str, ...] = tuple(UNIVERSE.keys())


@dataclass(frozen=True, slots=True)
class PairSpec:
    """A named Y/X pair with the economic reason it is on the list."""

    name: str
    y: str
    x: str
    rationale: str
    overrides: dict[str, object] = field(default_factory=dict)


# The ten pairs from the brief. Order matters only for display.
DEFAULT_PAIRS: tuple[PairSpec, ...] = (
    PairSpec("NQ/ES", "NQ=F", "ES=F", "Large-cap tech vs. the broad market; heavy index overlap."),
    PairSpec("ES/YM", "ES=F", "YM=F", "Two US large-cap benchmarks."),
    PairSpec("NQ/YM", "NQ=F", "YM=F", "Control pair: different weighting and sector mix."),
    PairSpec("ES/RTY", "ES=F", "RTY=F", "Large vs. small caps; style rotation."),
    PairSpec("ZN/ZF", "ZN=F", "ZF=F", "Adjacent tenors on the Treasury curve."),
    PairSpec("GC/SI", "GC=F", "SI=F", "Gold/silver ratio."),
    PairSpec("CL/BZ", "CL=F", "BZ=F", "Same commodity, different delivery hub."),
    PairSpec("6A/6C", "6A=F", "6C=F", "Two commodity currencies."),
    PairSpec("EWA/EWC", "EWA", "EWC", "Chan's textbook example; two resource economies."),
    PairSpec("KO/PEP", "KO", "PEP", "Direct competitors; the classic equity pair."),
)


def get_instrument(ticker: str) -> PairInstrument:
    """Resolve a ticker or raise a ValueError naming it (API maps to 400)."""
    try:
        return UNIVERSE[ticker]
    except KeyError as exc:
        raise ValueError(f"unknown pairs-universe ticker: {ticker!r}") from exc


def price_field_for(ticker: str) -> str:
    """Which stored column represents the instrument's price series.

    Futures carry no dividends, so close == settlement; ETFs and stocks
    must use the dividend-adjusted close or every ex-date looks like a
    spread shock.
    """
    return "close" if get_instrument(ticker).kind == "futures" else "adj_close"


def tickers_by_kind(kind: InstrumentKind) -> tuple[str, ...]:
    return tuple(t for t, inst in UNIVERSE.items() if inst.kind == kind)


def registry_symbol_for(ticker: str) -> str | None:
    """The 1m-registry symbol behind a futures ticker, when the DB stores one."""
    sym = get_instrument(ticker).registry_symbol
    return sym if sym in INSTRUMENT_REGISTRY else None
