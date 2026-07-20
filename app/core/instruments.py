"""Single source of truth for the futures the platform tracks.

Adding a new instrument is one entry in `INSTRUMENT_REGISTRY` plus the
corresponding `Symbol` Literal value below. Everything downstream — the
yfinance fetcher, the API's `Instrument` Pydantic Literal, the ML
workbench schema — reads from this module so the instrument list never
drifts out of sync between layers.

Instruments fall into three asset classes today:

* `equity_index` — NQ/ES/YM/RTY. Quarterly rolls (Mar/Jun/Sep/Dec).
* `metal`        — GC/SI/HG. Bimonthly rolls (e.g. Apr/Jun/Aug/Dec for
                   GC), filed under the `roll_calendar` table only when
                   the project starts using metal-specific rolls.
* `energy`       — CL/NG. Monthly rolls — every contract month.

The roll_calendar table is intentionally **not** seeded for the metal
and energy symbols yet: their roll behaviour is materially different
from index futures and will get its own dataset when needed. Until
then, queries with `adjustment="ratio"` or `"absolute"` on these
instruments return raw prices (since the joiner finds zero roll
events to apply), which is the correct, unsurprising behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Adding a symbol: extend this Literal AND add the matching registry row
# below. mypy will flag any place that still expects the old shorter set.
Symbol = Literal[
    "NQ", "ES", "YM", "RTY",                  # US equity indices
    "NKD",                                     # international indices
    "ZT", "ZF", "ZN", "ZB",                   # rates
    "6E", "6J", "6B", "6A",                   # FX
    "GC", "SI", "HG", "PL", "PA",             # metals
    "CL", "NG", "HO", "RB", "BZ",             # energy
    "ZC", "ZS", "ZW", "ZL", "ZM",             # grains
    "KC", "SB", "CC",                          # softs
    "HE", "LE",                                # livestock
    "BTC", "ETH", "SOL", "ADA", "BNB", "DOGE", # crypto (Binance spot)
]

AssetClass = Literal[
    "equity_index", "intl_index", "rates", "fx", "metal", "energy",
    "grain", "soft", "livestock", "crypto",
]


@dataclass(frozen=True)
class InstrumentMeta:
    symbol: str
    name: str
    asset_class: AssetClass
    exchange: str
    # Exactly one of these is set: futures come from Yahoo, crypto from
    # Binance. `data_source` names the provider shown in the UI.
    yfinance_ticker: str = ""
    binance_pair: str = ""

    @property
    def data_source(self) -> str:
        return "binance" if self.binance_pair else "yfinance"


INSTRUMENT_REGISTRY: dict[str, InstrumentMeta] = {
    "NQ":  InstrumentMeta("NQ",  "E-mini Nasdaq-100",   "equity_index", "CME",   "NQ=F"),
    "ES":  InstrumentMeta("ES",  "E-mini S&P 500",      "equity_index", "CME",   "ES=F"),
    "YM":  InstrumentMeta("YM",  "E-mini Dow Jones",    "equity_index", "CBOT",  "YM=F"),
    "RTY": InstrumentMeta("RTY", "E-mini Russell 2000", "equity_index", "CME",   "RTY=F"),
    "GC":  InstrumentMeta("GC",  "Gold",                "metal",         "COMEX", "GC=F"),
    "SI":  InstrumentMeta("SI",  "Silver",              "metal",         "COMEX", "SI=F"),
    "HG":  InstrumentMeta("HG",  "Copper",              "metal",         "COMEX", "HG=F"),
    "CL":  InstrumentMeta("CL",  "Crude Oil (WTI)",     "energy",        "NYMEX", "CL=F"),
    "NG":  InstrumentMeta("NG",  "Natural Gas",         "energy",        "NYMEX", "NG=F"),
    # 2026-07-20 expansion (ADR-005 follow-up): every symbol below was
    # verified to serve 1m bars through yfinance before being added.
    "NKD": InstrumentMeta("NKD", "Nikkei 225 (USD)",    "intl_index",    "CME",   "NKD=F"),
    "ZT":  InstrumentMeta("ZT",  "2-Year T-Note",       "rates",         "CBOT",  "ZT=F"),
    "ZF":  InstrumentMeta("ZF",  "5-Year T-Note",       "rates",         "CBOT",  "ZF=F"),
    "ZN":  InstrumentMeta("ZN",  "10-Year T-Note",      "rates",         "CBOT",  "ZN=F"),
    "ZB":  InstrumentMeta("ZB",  "30-Year T-Bond",      "rates",         "CBOT",  "ZB=F"),
    "6E":  InstrumentMeta("6E",  "Euro FX",             "fx",            "CME",   "6E=F"),
    "6J":  InstrumentMeta("6J",  "Japanese Yen",        "fx",            "CME",   "6J=F"),
    "6B":  InstrumentMeta("6B",  "British Pound",       "fx",            "CME",   "6B=F"),
    "6A":  InstrumentMeta("6A",  "Australian Dollar",   "fx",            "CME",   "6A=F"),
    "PL":  InstrumentMeta("PL",  "Platinum",            "metal",         "NYMEX", "PL=F"),
    "PA":  InstrumentMeta("PA",  "Palladium",           "metal",         "NYMEX", "PA=F"),
    "HO":  InstrumentMeta("HO",  "Heating Oil",         "energy",        "NYMEX", "HO=F"),
    "RB":  InstrumentMeta("RB",  "RBOB Gasoline",       "energy",        "NYMEX", "RB=F"),
    "BZ":  InstrumentMeta("BZ",  "Brent Crude",         "energy",        "NYMEX", "BZ=F"),
    "ZC":  InstrumentMeta("ZC",  "Corn",                "grain",         "CBOT",  "ZC=F"),
    "ZS":  InstrumentMeta("ZS",  "Soybeans",            "grain",         "CBOT",  "ZS=F"),
    "ZW":  InstrumentMeta("ZW",  "Wheat",               "grain",         "CBOT",  "ZW=F"),
    "ZL":  InstrumentMeta("ZL",  "Soybean Oil",         "grain",         "CBOT",  "ZL=F"),
    "ZM":  InstrumentMeta("ZM",  "Soybean Meal",        "grain",         "CBOT",  "ZM=F"),
    "KC":  InstrumentMeta("KC",  "Coffee",              "soft",          "ICE",   "KC=F"),
    "SB":  InstrumentMeta("SB",  "Sugar No. 11",        "soft",          "ICE",   "SB=F"),
    "CC":  InstrumentMeta("CC",  "Cocoa",               "soft",          "ICE",   "CC=F"),
    "HE":  InstrumentMeta("HE",  "Lean Hogs",           "livestock",     "CME",   "HE=F"),
    "LE":  InstrumentMeta("LE",  "Live Cattle",         "livestock",     "CME",   "LE=F"),
    # Crypto is Binance spot across the board (ADR-007): the full 1m
    # history is free back to each listing date and using one venue for
    # both history and daily updates avoids a price seam at the join.
    # These trade 24/7 — no session gaps, no contract rolls.
    "BTC":  InstrumentMeta("BTC",  "Bitcoin",   "crypto", "Binance", binance_pair="BTCUSDT"),
    "ETH":  InstrumentMeta("ETH",  "Ether",     "crypto", "Binance", binance_pair="ETHUSDT"),
    "SOL":  InstrumentMeta("SOL",  "Solana",    "crypto", "Binance", binance_pair="SOLUSDT"),
    "ADA":  InstrumentMeta("ADA",  "Cardano",   "crypto", "Binance", binance_pair="ADAUSDT"),
    "BNB":  InstrumentMeta("BNB",  "BNB",       "crypto", "Binance", binance_pair="BNBUSDT"),
    "DOGE": InstrumentMeta("DOGE", "Dogecoin",  "crypto", "Binance", binance_pair="DOGEUSDT"),
}


ALL_SYMBOLS: tuple[str, ...] = tuple(INSTRUMENT_REGISTRY.keys())


def get_yfinance_ticker(symbol: str) -> str | None:
    """Look up the yfinance continuous-contract ticker for a symbol."""
    meta = INSTRUMENT_REGISTRY.get(symbol.upper())
    return meta.yfinance_ticker if meta and meta.yfinance_ticker else None


def get_binance_pair(symbol: str) -> str | None:
    """Look up the Binance spot pair for a symbol (crypto only)."""
    meta = INSTRUMENT_REGISTRY.get(symbol.upper())
    return meta.binance_pair if meta and meta.binance_pair else None


def get_data_source(symbol: str) -> str:
    """Provider name for a symbol — 'binance' or 'yfinance'."""
    meta = INSTRUMENT_REGISTRY.get(symbol.upper())
    return meta.data_source if meta else "yfinance"
