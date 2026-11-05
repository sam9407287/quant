"""Offline smoke test of the pairs lab: synthetic data → scan → backtest → report.

No database, no network, no credentials. Runs in CI and before a deploy
to prove the analytical pipeline still fits together end to end:

    python scripts/smoke_pairs.py            # human-readable summary, exit 0
    python scripts/smoke_pairs.py --json     # machine-readable summary

Exit code 1 means an invariant failed; the message says which.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Runnable as `python scripts/smoke_pairs.py` from the repo root as well as
# `python -m scripts.smoke_pairs`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pairs.backtest import run_with_sensitivity  # noqa: E402
from app.pairs.diagnostics import forward_buckets, rolling_series  # noqa: E402
from app.pairs.notify import entry_embed  # noqa: E402, F401  (import check: notify module loads)
from app.pairs.schemas import BacktestConfig, CostModel, PortfolioConfig, ScanConfig  # noqa: E402
from app.pairs.screen import scan_pairs  # noqa: E402
from app.pairs.synthetic import cointegrated_pair, independent_walks, price_frame  # noqa: E402


def build_prices() -> pd.DataFrame:
    y, x = cointegrated_pair(n=1400, beta=1.1, half_life=9.0, spread_sigma=0.008, seed=41)
    a, b = cointegrated_pair(n=1400, beta=0.8, half_life=20.0, spread_sigma=0.012, seed=42)
    r1, r2 = independent_walks(n=1400, seed=43)
    frame = price_frame({"NQ=F": y, "ES=F": x, "GC=F": a, "SI=F": b, "CL=F": r1, "BZ=F": r2})
    frame["NQ=F"] *= 100
    frame["ES=F"] *= 30
    frame["GC=F"] *= 15
    frame["SI=F"] *= 0.2
    frame["CL=F"] *= 0.5
    frame["BZ=F"] *= 0.5
    return frame


def check(cond: bool, message: str) -> None:
    if not cond:
        print(f"SMOKE FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pairs lab offline smoke test")
    parser.add_argument("--json", action="store_true", help="emit a JSON summary")
    args = parser.parse_args()
    started = time.perf_counter()

    prices = build_prices()
    logp = np.log(prices)
    pairs = [("NQ=F", "ES=F"), ("GC=F", "SI=F"), ("CL=F", "BZ=F")]

    scan_cfg = ScanConfig(mode="explicit", pairs=pairs, formation_window=400, stability_step=5)
    results = scan_pairs(logp, pairs, scan_cfg)
    check(len(results) == 3, f"scan returned {len(results)} rows, expected 3")
    by_name = {r.pair_name: r for r in results}
    check(by_name["NQ/ES"].qualified, f"NQ/ES should qualify: {by_name['NQ/ES'].reasons}")
    check(not by_name["CL/BZ"].qualified, "random walks must not qualify")
    check(all(r.eg_qvalue is not None for r in results), "missing BH q-values")

    y = logp["NQ=F"].to_numpy()
    x = logp["ES=F"].to_numpy()
    rs = rolling_series(y, x, logp.index, formation_window=400, z_window_min=10, z_window_max=60)
    buckets = forward_buckets(rs.spread, rs.zscore, horizons=(10,))
    check(bool(buckets), "forward-return table is empty")

    bt_cfg = BacktestConfig(
        pairs=pairs, formation_window=400, fill="next_open",
        costs=CostModel(commission_per_contract=1.25, slippage_ticks=1.0, roll_cost_per_contract=2.5),
        portfolio=PortfolioConfig(capital=1_000_000, sizing="integer"),
        sensitivity=True, sensitivity_entry_z=[1.5, 2.0], sensitivity_formation=[400],
    )
    opens = prices * (1 + 0.0005)
    result = run_with_sensitivity(prices, bt_cfg, prices_open=opens)
    mt = result.metrics
    check(mt.trade_count > 0, "backtest produced no trades")
    check(len(result.sensitivity) == 4, f"sensitivity grid has {len(result.sensitivity)} cells, expected 4")
    check(mt.tradeability_tax is not None, "integer mode must report the tradeability tax")
    check(-1 <= mt.max_drawdown <= 0, "drawdown out of range")
    net = sum(t.net_pnl for t in result.trades)
    check(abs(result.equity[-1].equity - bt_cfg.portfolio.capital - net) < 1e-6, "equity does not reconcile with trades")

    summary: dict[str, Any] = {
        "runtime_s": round(time.perf_counter() - started, 2),
        "scan": {r.pair_name: {"qualified": r.qualified, "eg_p": round(r.eg_pvalue, 4), "hl": r.half_life} for r in results},
        "forward_buckets": len(buckets),
        "backtest": {
            "trades": mt.trade_count, "total_return": round(mt.total_return, 4), "sharpe": mt.sharpe,
            "deflated_sharpe_p": mt.deflated_sharpe_p, "max_drawdown": round(mt.max_drawdown, 4),
            "tradeability_tax": mt.tradeability_tax, "exit_mix": mt.exit_mix,
        },
    }
    if args.json:
        print(json.dumps(summary, default=str))
    else:
        print("pairs lab smoke: OK")
        for k, v in summary.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
