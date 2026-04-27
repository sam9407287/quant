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
    "NQ", "ES", "YM", "RTY",   # equity indices
    "GC", "SI", "HG",           # metals
    "CL", "NG",                 # energy
]

AssetClass = Literal["equity_index", "metal", "energy"]


@dataclass(frozen=True)
class InstrumentMeta:
    symbol: str
    name: str
    asset_class: AssetClass
    exchange: str
    yfinance_ticker: str


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
}


ALL_SYMBOLS: tuple[str, ...] = tuple(INSTRUMENT_REGISTRY.keys())


def get_yfinance_ticker(symbol: str) -> str | None:
    """Look up the yfinance continuous-contract ticker for a symbol."""
    meta = INSTRUMENT_REGISTRY.get(symbol.upper())
    return meta.yfinance_ticker if meta else None
