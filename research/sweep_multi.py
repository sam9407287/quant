"""Cross-instrument sweep in pct mode (comparable across price scales)."""

from __future__ import annotations

import csv
import sys
import time as _time
from datetime import date, datetime, time

sys.path.insert(0, "/Users/sam/Desktop/quant-futures")

from app.backtest.engine import run_backtest  # noqa: E402
from app.backtest.loader import group_sessions  # noqa: E402
from app.backtest.params import BacktestParams, SessionClock  # noqa: E402
from app.backtest.types import Bar  # noqa: E402

DIR = "/private/tmp/claude-501/-Users-sam-Desktop-scheduling-api/bc8fc887-da4f-4255-92e8-22a806def3b6/scratchpad"
START, END = date(2026, 4, 20), date(2026, 7, 17)

WINDOWS = {
    "premkt":    ("00:00", "09:30"),
    "overnight": ("18:00", "09:30"),
    "open30":    ("09:00", "09:30"),
    "euro_pre":  ("02:00", "09:30"),
}


def load_bars(inst: str) -> list[Bar]:
    bars = []
    with open(f"{DIR}/{inst.lower()}_1m.csv") as f:
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


def stats(results):
    traded = [r for r in results if r.exit_reason in ("tp", "sl", "eod")]
    wins = sum(r.pnl_points for r in traded if r.pnl_points > 0)
    losses = -sum(r.pnl_points for r in traded if r.pnl_points < 0)
    wr = (sum(1 for r in traded if r.pnl_points > 0) / len(traded)) if traded else 0.0
    pf = (wins / losses) if losses > 0 else None
    return pf, len(traded), wr


def run_instrument(inst: str) -> list[dict]:
    bars = load_bars(inst)
    cache: dict[str, list] = {}
    rows = []
    grid = []
    for w, (rs, re) in WINDOWS.items():
        for eod in ("11:30", "15:55"):
            for d in ("fade", "breakout"):
                for sl in (0.05, 0.08, 0.11, 0.15, 0.22, 0.35):   # % of entry
                    for rrr in (0.6, 0.8, 1.0, 1.5, 2.0):
                        for off in (0.0, 0.05, 0.09, 0.14, 0.22): # % of level
                            grid.append((w, rs, re, eod, d, sl, rrr, off))
    t0 = _time.time()
    for i, (w, rs, re, eod, d, sl, rrr, off) in enumerate(grid):
        clock = SessionClock(tz="America/New_York", range_start=hhmm(rs),
                             range_end=hhmm(re), orders_place=hhmm("09:30"),
                             eod_flat=hhmm(eod))
        params = BacktestParams(
            instrument=inst, start=START, end=END, clock=clock,  # type: ignore[arg-type]
            direction_mode=d, entry_offset_mode="pct", entry_offset_value=off,
            sl_mode="pct", sl_value=sl, rrr=rrr,
        )
        if eod not in cache:
            all_s = group_sessions(bars, params)
            cache[eod] = [(dd, b) for dd, b in all_s if START <= dd <= END]
        pf, n, wr = stats(run_backtest(cache[eod], params))
        rows.append(dict(inst=inst, win=w, eod=eod, dir=d, sl=sl, rrr=rrr, off=off,
                         pf=round(pf, 3) if pf is not None else "", trades=n,
                         win_rate=round(wr, 3)))
    print(f"{inst}: {len(grid)} combos in {_time.time()-t0:.0f}s", flush=True)
    return rows


if __name__ == "__main__":
    insts = sys.argv[1].split(",")
    all_rows = []
    for inst in insts:
        all_rows.extend(run_instrument(inst))
    out = f"{DIR}/multi_{'_'.join(insts)}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    print("saved", out)
