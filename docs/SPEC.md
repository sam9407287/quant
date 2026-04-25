# System Specification (SPEC)

## 1. System Goals

Build a production-grade quantitative analytics platform for CME index futures with:
- Complete historical OHLCV data collection and continuous daily updates
- Multi-timeframe technical signal analysis
- Strategy backtesting engine
- Extensible architecture for live trading automation

## 2. Instruments

| Symbol | Full Name | Exchange | yfinance Ticker |
|--------|-----------|----------|-----------------|
| NQ | E-mini Nasdaq-100 | CME | `NQ=F` |
| ES | E-mini S&P 500 | CME | `ES=F` |
| YM | E-mini Dow Jones | CBOT | `YM=F` |
| RTY | E-mini Russell 2000 | CME | `RTY=F` |

## 3. Development Phases

### Period 1 — Data Collection (Current)

**Goal:** Establish a stable, clean, continuously-updated 1m OHLCV database.

**Functional requirements:**
- [ ] One-time historical import from FirstRate Data CSV (from 2008)
- [ ] Daily automated fetch of latest 1m bars (runs after market close)
- [ ] Data integrity validation: gap detection and anomaly flagging
- [ ] Contract roll calendar maintenance (auto-record each quarterly roll)
- [ ] REST API to query bars at any supported timeframe
- [ ] REST API for data coverage status

**Acceptance criteria:**
- All four instruments have complete 1m data from 2008 to present
- Daily auto-fetch runs cleanly for 2+ consecutive weeks
- Gap detection script reports < 0.1% missing bars in normal trading sessions

---

### Period 2 — Strategy Research (after Period 1)

**Goal:** Develop and validate trading signals using stored data.

**Functional requirements:**
- [ ] Technical indicator computation API (EMA, RSI, MACD, ATR, Bollinger Bands, Volume MA)
- [ ] Multi-timeframe indicator queries (retrieve 1m/5m/15m/1h/4h/1d simultaneously)
- [ ] Signal schema: type, direction, strength, entry/stop/target prices
- [ ] Backtesting engine via VectorBT integration
- [ ] Backtest reports: total return, Sharpe ratio, max drawdown, win rate, profit factor
- [ ] Walk-forward validation
- [ ] Signal history query API

**Acceptance criteria:**
- At least one strategy backtested with Sharpe Ratio > 1.0 and max drawdown < 20%

---

### Period 3 — Live Trading (after Period 2)

**Goal:** Connect real-time data feed and execute validated strategies.

**Functional requirements:**
- [ ] IBKR TWS API integration for real-time 1m bar ingestion
- [ ] Real-time signal detection with WebSocket push to clients
- [ ] Automated order management: market, limit, and stop orders
- [ ] Position sizing and risk controls
- [ ] Real-time P&L tracking
- [ ] Paper trading mode for validation
- [ ] Emergency kill switch (halt all open positions)

**Acceptance criteria:**
- Paper trading runs stably for 30 days with signals matching expected execution

---

## 4. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Data latency (Period 1–2) | Daily update complete by 18:00 UTC same day |
| Data latency (Period 3) | < 500 ms end-to-end signal generation |
| Query performance | Single instrument, 1 year of 1m bars returned in < 2 s |
| Availability | 99% (Railway Pro SLA) |
| Data completeness | < 0.1% missing bars in valid trading sessions |
| Deployment target | Railway Pro (API + Fetcher services, PostgreSQL plugin) |

---

## 5. Multi-Timeframe Analysis Design

```
Timeframes          Purpose
─────────────────────────────────────────────────────
Weekly, Daily   →   Market regime (trend / range / risk-off)
4H, 1H          →   Primary trend direction + key structure levels
15m, 5m         →   Entry signal confirmation
1m              →   Precise entry / exit positioning
```

All timeframes are derived from the 1m base data via TimescaleDB Continuous Aggregates.

---

## 6. API Specification

### Period 1 Endpoints

```
GET /api/v1/kbars
  Query params:
    instrument  : NQ | ES | YM | RTY       (required)
    timeframe   : 1m|5m|15m|1h|4h|1d|1w   (required)
    start       : ISO 8601 UTC datetime     (required)
    end         : ISO 8601 UTC datetime     (required)
    adjustment  : raw|ratio|absolute        (default: ratio)
    limit       : int                       (default: 5000, max: 50000)
    cursor      : str                       (pagination cursor)
  Response: { data: [{ts, open, high, low, close, volume}], next_cursor }

GET /api/v1/coverage
  Query params:
    instrument : NQ | ES | YM | RTY | all  (default: all)
  Response: [{ instrument, earliest_ts, latest_ts, bar_count, gap_count, last_fetch_ts }]

GET /api/v1/coverage/gaps
  Query params:
    instrument : NQ | ES | YM | RTY        (required)
    start      : date                       (required)
    end        : date                       (required)
  Response: [{ gap_start, gap_end, missing_bar_count }]

GET /api/v1/roll-calendar
  Query params:
    instrument : NQ | ES | YM | RTY        (required)
    year       : int                        (optional)
  Response: [{ old_contract, new_contract, roll_date, price_diff, price_ratio }]

GET /health
  Response: { status: "ok", db: "ok", version: "1.0.0" }
```

### Period 2 Additional Endpoints

```
GET /api/v1/indicators
  Query params: instrument, timeframe, start, end
                indicators (comma-separated: ema20,ema60,rsi14,macd,atr14)

GET /api/v1/signals
  Query params: instrument, strategy, start, end

POST /api/v1/backtest
  Body: { strategy_name, instrument, params, start_date, end_date }
  Response: { report_id }

GET /api/v1/backtest/{report_id}
  Response: { total_return, sharpe_ratio, max_drawdown, win_rate, profit_factor,
              trade_count, equity_curve }
```

---

## 7. Data Quality Standards

### Valid trading sessions (CME Globex)
- Sunday 18:00 – Friday 17:00 ET
- Daily settlement break: 17:00–18:00 ET (excluded from gap analysis)

### Anomaly detection rules
- Single bar price change > 5%  → flagged, requires manual review
- Volume = 0 during trading hours → flagged
- Timestamp outside trading session → rejected at ingest

### Gap definition
- Two or more consecutive missing 1m bars within a valid trading session
