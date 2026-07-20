"""Local parameter sweep for the killzone-OCO engine (no DB writes)."""

from __future__ import annotations

import csv
import itertools
import sys
import time as _time
from datetime import date, datetime, time

sys.path.insert(0, "/Users/sam/Desktop/quant-futures")

from app.backtest.engine import run_backtest  # noqa: E402
from app.backtest.loader import group_sessions  # noqa: E402
from app.backtest.params import BacktestParams, SessionClock  # noqa: E402
from app.backtest.types import Bar  # noqa: E402

CSV_PATH = "/private/tmp/claude-501/-Users-sam-Desktop-scheduling-api/bc8fc887-da4f-4255-92e8-22a806def3b6/scratchpad/nq_1m.csv"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "sweep_results.csv"

START, END = date(2026, 4, 20), date(2026, 7, 17)


def load_bars() -> list[Bar]:
    bars = []
    with open(CSV_PATH) as f:
        next(f)
        for line in f:
            ts, o, h, low, c = line.rstrip().split(",")
            bars.append(Bar(
                ts=datetime.fromisoformat(ts.replace("Z", "+00:00")),
                open=float(o), high=float(h), low=float(low), close=float(c),
            ))
    return bars


def hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def profit_factor(results) -> tuple[float | None, int, float, float, float]:
    traded = [r for r in results if r.exit_reason in ("tp", "sl", "eod")]
    wins = sum(r.pnl_usd for r in traded if r.pnl_usd > 0)
    losses = -sum(r.pnl_usd for r in traded if r.pnl_usd < 0)
    total = sum(r.pnl_usd for r in traded)
    wr = (sum(1 for r in traded if r.pnl_usd > 0) / len(traded)) if traded else 0.0
    pf = (wins / losses) if losses > 0 else None
    return pf, len(traded), total, wr, losses


def run_grid(grid: list[dict]) -> list[dict]:
    bars = load_bars()
    session_cache: dict[tuple, list] = {}
    rows = []
    t0 = _time.time()
    for i, g in enumerate(grid):
        clock = SessionClock(
            tz="America/New_York",
            range_start=hhmm(g["rs"]), range_end=hhmm(g["re"]),
            orders_place=hhmm(g["op"]), eod_flat=hhmm(g["eod"]),
        )
        params = BacktestParams(
            instrument="NQ", start=START, end=END, clock=clock,
            direction_mode=g["dir"],
            entry_offset_mode="points", entry_offset_value=g["off"],
            sl_mode="points", sl_value=g["sl"], rrr=g["rrr"],
        )
        key = (g["eod"],)
        if key not in session_cache:
            all_s = group_sessions(bars, params)
            session_cache[key] = [(d, b) for d, b in all_s if START <= d <= END]
        results = run_backtest(session_cache[key], params)
        pf, n, total, wr, gross_loss = profit_factor(results)
        rows.append({**g, "pf": round(pf, 3) if pf is not None else "",
                     "trades": n, "pnl": round(total, 1),
                     "win_rate": round(wr, 3)})
        if (i + 1) % 200 == 0:
            print(f"{i+1}/{len(grid)} ({_time.time()-t0:.0f}s)", flush=True)
    return rows


WINDOWS = {
    "asia":      ("20:00", "00:00"),
    "london":    ("02:00", "05:00"),
    "premkt":    ("00:00", "09:30"),
    "overnight": ("18:00", "09:30"),
    "open30":    ("09:00", "09:30"),
}


def base_grid() -> list[dict]:
    grid = []
    for w, (rs, re), in WINDOWS.items():
        for eod in ("11:30", "15:55"):
            for d in ("fade", "breakout"):
                for sl in (30, 50, 75, 100, 150):
                    for rrr in (1.0, 1.5, 2.0, 3.0):
                        for off in (0.0, 10.0, 25.0):
                            grid.append(dict(win=w, rs=rs, re=re, op="09:30",
                                             eod=eod, dir=d, sl=sl, rrr=rrr, off=off))
    return grid


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "base"
    grid = base_grid()
    print(f"grid size: {len(grid)}")
    rows = run_grid(grid)
    with open(OUT_PATH, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    good = [r for r in rows if r["pf"] != "" and float(r["pf"]) >= 1.5 and r["trades"] >= 30]
    print(f"combos with PF>=1.5 and >=30 trades: {len(good)}")
    good.sort(key=lambda r: -float(r["pf"]))
    for r in good[:15]:
        print(r)
