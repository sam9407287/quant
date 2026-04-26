"""Detect futures contract roll events from yfinance volume data.

yfinance returns the current front-month contract via the generic ticker
(e.g. NQ=F). The contract name embedded in the ticker metadata changes
on roll date. This module compares the active contract symbol across
consecutive fetches and records a new roll_calendar entry when a change
is detected.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

logger = logging.getLogger(__name__)

# Matches contract codes like NQH25, ESM25, RTYZ26
_CONTRACT_RE = re.compile(r"^([A-Z]+)([HMUZ])(\d{2})$")

# Month code → quarter number
_MONTH_TO_QUARTER: dict[str, int] = {"H": 1, "M": 2, "U": 3, "Z": 4}


def parse_contract_code(code: str) -> tuple[str, str, int] | None:
    """Parse a contract code into (symbol, month_code, year).

    Args:
        code: e.g. 'NQH25'.

    Returns:
        Tuple of (symbol, month_code, 2-digit year) or None if not parseable.
    """
    m = _CONTRACT_RE.match(code.upper())
    if not m:
        return None
    symbol, month, year_str = m.group(1), m.group(2), m.group(3)
    return symbol, month, int(year_str)


def is_valid_contract(code: str) -> bool:
    """Return True if the code matches the expected CME contract format."""
    return parse_contract_code(code) is not None


def next_contract(current: str) -> str:
    """Compute the expected next contract code after a quarterly roll.

    Args:
        current: e.g. 'NQH25' → returns 'NQM25'.

    Returns:
        Next contract code string.

    Raises:
        ValueError: If current cannot be parsed.
    """
    parsed = parse_contract_code(current)
    if parsed is None:
        raise ValueError(f"Cannot parse contract code: {current!r}")

    symbol, month, year = parsed
    quarter = _MONTH_TO_QUARTER[month]
    month_codes = ["H", "M", "U", "Z"]

    next_quarter_idx = quarter % 4       # 0 = H, 1 = M, 2 = U, 3 = Z
    next_month = month_codes[next_quarter_idx]
    next_year = year + 1 if quarter == 4 else year

    return f"{symbol}{next_month}{next_year:02d}"


def compute_roll_factors(
    old_close: float,
    new_open: float,
) -> tuple[Decimal, Decimal]:
    """Compute price_diff and price_ratio from a roll event.

    Args:
        old_close: Last close of the expiring contract.
        new_open:  First open of the new front-month contract.

    Returns:
        (price_diff, price_ratio) as Decimals rounded to 4 places.
    """
    old = Decimal(str(old_close))
    new = Decimal(str(new_open))
    diff = (new - old).quantize(Decimal("0.0001"))
    ratio = (new / old).quantize(Decimal("0.00000001"))
    return diff, ratio
