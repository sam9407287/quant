# ADR-007: Crypto Sourced from Binance Spot

- **Status:** Accepted — implemented 2026-07-20
- **Date:** 2026-07-20
- **Deciders:** Sam
- **Relates:** ADR-006 (backup), the 2026-07-20 instrument expansion

## 1. Context

Crypto entered the platform as CME futures (`BTC=F`, `ETH=F`) via
yfinance, alongside a brief experiment with yfinance spot quotes
(`SOL-USD`, `ADA-USD`). Two problems:

1. **No usable history.** yfinance serves ~7 days of 1m bars, so the
   CME crypto contracts had ~3 months of data and no way to get more
   without buying it. Futures history costs money; crypto history does
   not have to.
2. **Mixed venues.** Loading history from one source and daily updates
   from another puts a price seam at the join — an aggregated quote and
   a single exchange's trades do not agree bar for bar.

Meanwhile Binance publishes complete 1m history as free public monthly
archives (`data.binance.vision`), no key or account required, back to
each pair's listing date.

## 2. Decision

**All crypto is Binance spot, for both history and daily updates.**

| Symbol | Pair | History from |
|---|---|---|
| BTC | BTCUSDT | 2017-08 |
| ETH | ETHUSDT | 2017-08 |
| BNB | BNBUSDT | 2017-11 |
| ADA | ADAUSDT | 2018-04 |
| DOGE | DOGEUSDT | 2019-07 |
| SOL | SOLUSDT | 2020-08 |

- `fetcher/sources/binance_source.py` implements the existing
  `DataSource` contract twice over: `fetch()` uses the REST klines
  endpoint (paged around the 1000-bar response cap) for the daily
  incremental, `iter_month()` pulls the monthly ZIP archives for bulk
  history. **Epochs are normalised by digit count** — the archives
  switched from millisecond to microsecond stamps in 2025 and both
  vintages are still served.
- `InstrumentMeta` now carries `yfinance_ticker` XOR `binance_pair` and
  derives `data_source`; the scheduler holds one adapter per provider
  and routes per instrument. Futures continue to use yfinance
  unchanged.
- **CME crypto futures were dropped, not kept alongside.** Sam's
  instruction was one provider for crypto. The ~3 months of CME BTC/ETH
  bars are archived to `research/cme_crypto_archive/` because they are
  crawler-accumulated and cannot be re-fetched.
- **The UI names the venue.** Every instrument carries an `exchange`,
  rendered on the dashboard cards and beside the chart's instrument
  selector, so a chart is never ambiguous about which market it shows.

## 3. Consequences

- Crypto gains 6–9 years of 1m history at zero cost, versus the ~3
  months it had. Backtests on crypto are now meaningful today, without
  waiting on the FirstRate purchase decision (which covers futures).
- Crypto trades 24/7: no session gaps, no contract rolls, so the
  roll-adjustment path is a no-op for these symbols (the roll_calendar
  simply has no rows for them, which the joiner already handles).
- Binance spot prices are one venue's, not a composite. That is the
  intended trade-off: internally consistent beats broadly averaged for
  backtesting.
- New direct dependency: `requests` (was transitive via yfinance).

## 4. Operations

Bulk load / reload:

```bash
railway ssh --service fetcher -- python -m scripts.bootstrap_binance
railway ssh --service fetcher -- python -m scripts.bootstrap_binance --purge BTC
```

The loader is resumable — the upsert dedupes on `(instrument, ts)`, so
an interrupted run is fixed by running it again. `--purge` exists for
provider switches, where old rows carry a different venue's prices.
