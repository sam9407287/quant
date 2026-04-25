# 系統設計文件 (System Design)

## 1. 整體架構

### Period 1（當前）

```
┌─────────────────────────────────────────────────────┐
│                  Railway Platform                    │
│                                                      │
│  ┌─────────────────┐    ┌──────────────────────┐   │
│  │   API Service   │    │   Fetcher Service    │   │
│  │   (FastAPI)     │    │   (Worker/Cron)      │   │
│  │                 │    │                      │   │
│  │  GET /kbars     │    │  每日 18:00 EST 執行  │   │
│  │  GET /coverage  │    │  yfinance → DB        │   │
│  └────────┬────────┘    └──────────┬───────────┘   │
│           │                        │                │
│           └──────────┬─────────────┘                │
│                      │                              │
│         ┌────────────▼────────────┐                 │
│         │      TimescaleDB        │                 │
│         │   (PostgreSQL + ext)    │                 │
│         │                        │                 │
│         │  kbars_1m (hypertable) │                 │
│         │  roll_calendar          │                 │
│         │  data_coverage          │                 │
│         │  [continuous aggregates]│                 │
│         └─────────────────────────┘                 │
└─────────────────────────────────────────────────────┘
          ▲                   ▲
          │                   │
   [開發者/分析工具]        [yfinance]
   Jupyter / API            Yahoo Finance
                            (CME 官方延遲數據)
```

### Period 3（未來）

```
加入：
  ┌──────────────────────────────┐
  │  Real-time Engine Service    │
  │  (ib_insync + asyncio)       │
  │                              │
  │  1m bar → Redis → Signal     │
  │  Signal → Order → IBKR API   │
  └──────────────────────────────┘
       ↕ TCP
  ┌──────────────────┐
  │  IB Gateway      │  ← 獨立 VPS 或本機
  │  (Docker)        │
  └──────────────────┘
       ↕
  [IBKR 伺服器]
```

---

## 2. 資料庫設計

### TimescaleDB Schema

```sql
-- ============================================
-- 擴充 TimescaleDB
-- ============================================
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================
-- 主數據表：1m 原始 K 棒（唯一手動維護的表）
-- ============================================
CREATE TABLE kbars_1m (
    instrument  TEXT        NOT NULL,   -- 'NQ', 'ES', 'YM', 'RTY'
    ts          TIMESTAMPTZ NOT NULL,   -- UTC 時間
    open        NUMERIC(12, 4) NOT NULL,
    high        NUMERIC(12, 4) NOT NULL,
    low         NUMERIC(12, 4) NOT NULL,
    close       NUMERIC(12, 4) NOT NULL,
    volume      BIGINT      NOT NULL,
    source      TEXT        NOT NULL    -- 'firstrate', 'yfinance', 'ibkr'
);

-- 轉為 hypertable，按時間自動分區（每週一個 chunk）
SELECT create_hypertable('kbars_1m', 'ts', chunk_time_interval => INTERVAL '1 week');

-- 唯一索引（防止重複寫入）
CREATE UNIQUE INDEX ON kbars_1m (instrument, ts);

-- 查詢索引
CREATE INDEX ON kbars_1m (instrument, ts DESC);

-- ============================================
-- 高時間框架（Continuous Aggregates，自動推導）
-- ============================================
CREATE MATERIALIZED VIEW kbars_5m
WITH (timescaledb.continuous) AS
SELECT
    instrument,
    time_bucket('5 minutes', ts)  AS ts,
    first(open, ts)               AS open,
    max(high)                     AS high,
    min(low)                      AS low,
    last(close, ts)               AS close,
    sum(volume)                   AS volume
FROM kbars_1m
GROUP BY instrument, time_bucket('5 minutes', ts);

-- 同理建立 15m, 1h, 4h, 1d, 1w
CREATE MATERIALIZED VIEW kbars_15m WITH (timescaledb.continuous) AS
SELECT instrument, time_bucket('15 minutes', ts) AS ts,
    first(open,ts), max(high), min(low), last(close,ts), sum(volume)
FROM kbars_1m GROUP BY 1, 2;

CREATE MATERIALIZED VIEW kbars_1h WITH (timescaledb.continuous) AS
SELECT instrument, time_bucket('1 hour', ts) AS ts,
    first(open,ts), max(high), min(low), last(close,ts), sum(volume)
FROM kbars_1m GROUP BY 1, 2;

CREATE MATERIALIZED VIEW kbars_4h WITH (timescaledb.continuous) AS
SELECT instrument, time_bucket('4 hours', ts) AS ts,
    first(open,ts), max(high), min(low), last(close,ts), sum(volume)
FROM kbars_1m GROUP BY 1, 2;

CREATE MATERIALIZED VIEW kbars_1d WITH (timescaledb.continuous) AS
SELECT instrument, time_bucket('1 day', ts) AS ts,
    first(open,ts), max(high), min(low), last(close,ts), sum(volume)
FROM kbars_1m GROUP BY 1, 2;

CREATE MATERIALIZED VIEW kbars_1w WITH (timescaledb.continuous) AS
SELECT instrument, time_bucket('1 week', ts) AS ts,
    first(open,ts), max(high), min(low), last(close,ts), sum(volume)
FROM kbars_1m GROUP BY 1, 2;

-- 自動刷新策略（每小時刷新最近 2 天的數據）
SELECT add_continuous_aggregate_policy('kbars_5m',
    start_offset => INTERVAL '2 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
-- 同理設定其他時間框架的 policy

-- ============================================
-- 換倉日曆
-- ============================================
CREATE TABLE roll_calendar (
    id              SERIAL PRIMARY KEY,
    instrument      TEXT        NOT NULL,   -- 'NQ', 'ES', 'YM', 'RTY'
    old_contract    TEXT        NOT NULL,   -- 'NQH25'
    new_contract    TEXT        NOT NULL,   -- 'NQM25'
    roll_date       DATE        NOT NULL,
    roll_ts         TIMESTAMPTZ,            -- 精確換倉時間（午夜 EST）
    price_diff      NUMERIC(12, 4),         -- new_open - old_close（Absolute Adjust 用）
    price_ratio     NUMERIC(10, 8),         -- new_open / old_close（Ratio Adjust 用）
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX ON roll_calendar (instrument, roll_date);

-- ============================================
-- 數據覆蓋追蹤
-- ============================================
CREATE TABLE data_coverage (
    instrument      TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,   -- '1m', '5m', '15m', '1h', '4h', '1d', '1w'
    earliest_ts     TIMESTAMPTZ,
    latest_ts       TIMESTAMPTZ,
    bar_count       BIGINT  DEFAULT 0,
    gap_count       INT     DEFAULT 0,  -- 偵測到的缺口數
    last_fetch_ts   TIMESTAMPTZ,
    last_fetch_ok   BOOLEAN DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (instrument, timeframe)
);
```

---

## 3. 換倉（Roll）處理設計

### 換倉時間表（CME 標準）

```
NQ / ES / RTY：每年 3, 6, 9, 12 月第三個星期五
YM           ：每年 3, 6, 9, 12 月第三個星期五

實際換倉日（Volume 轉移日）通常在到期日前 2 週：
  2025 年換倉日參考：
    2025-03-13（3 月合約 → 6 月合約）
    2025-06-12（6 月合約 → 9 月合約）
    2025-09-11（9 月合約 → 12 月合約）
    2025-12-11（12 月合約 → 2026 年 3 月合約）
```

### 合約代碼命名規則

```
格式：[商品][月份代碼][年份後兩位]
  H = 3月, M = 6月, U = 9月, Z = 12月

範例：
  NQH25 = NQ 2025年3月合約
  ESM25 = ES 2025年6月合約
  YMU25 = YM 2025年9月合約
  RTYZ25 = RTY 2025年12月合約
```

### Ratio Adjustment 計算邏輯

```python
# 換倉當天，計算 ratio
ratio = new_contract_open / old_contract_close

# 查詢時，對換倉日之前的所有 close/open/high/low 乘上 ratio（累乘）
# 越舊的數據累乘的 ratio 越多，保留漲跌幅百分比關係

# 範例：
# roll_calendar 有 3 次換倉記錄
# 查詢 2020 年的數據 → 需乘上 2020-2025 年間所有 ratio 的連乘積
```

### API 查詢時的調整邏輯（Pseudo Code）

```python
def get_kbars(instrument, timeframe, start, end, adjustment='ratio'):
    raw_data = query_timescaledb(instrument, timeframe, start, end)

    if adjustment == 'raw':
        return raw_data

    rolls = get_rolls_after(instrument, start)  # 取 start 之後的所有換倉

    if adjustment == 'ratio':
        cumulative_ratio = product([r.price_ratio for r in rolls])
        raw_data['open']  *= cumulative_ratio
        raw_data['high']  *= cumulative_ratio
        raw_data['low']   *= cumulative_ratio
        raw_data['close'] *= cumulative_ratio

    elif adjustment == 'absolute':
        cumulative_diff = sum([r.price_diff for r in rolls])
        # 加到 OHLC 上

    return raw_data
```

---

## 4. 數據抓取流程設計

### 每日補齊流程（Fetcher Service）

```
每天 美東 18:00（週一至週五）觸發：

For each instrument in [NQ, ES, YM, RTY]:
    1. 用 yfinance 抓最近 7 天的 1m K 棒
    2. 與資料庫中現有數據比對（by timestamp）
    3. 只寫入不存在的新數據（UPSERT ON CONFLICT DO NOTHING）
    4. 偵測是否為換倉日（volume 比較新舊合約）
       → 若是：寫入 roll_calendar
    5. 更新 data_coverage 表

寫入 LOG：
    - 抓取幾筆、寫入幾筆、跳過幾筆
    - 是否偵測到換倉
    - 是否有異常值
```

### 初始化流程（一次性）

```
scripts/bootstrap_csv.py：

1. 解壓縮 FirstRate Data ZIP 檔（Unadjusted 版本）
2. 解析 CSV 格式：
   FirstRate 格式：DateTime, Open, High, Low, Close, Volume
   → 轉換為系統格式：instrument, ts(UTC), open, high, low, close, volume, source='firstrate'
3. 批次寫入 kbars_1m（每批 10,000 筆）
4. 完成後跑一次 verify_coverage.py

CSV 時間欄位注意：
   FirstRate 使用 EST 時間 → 寫入時轉換為 UTC
```

### 缺口偵測邏輯

```python
# scripts/verify_coverage.py

TRADING_SESSIONS = {
    # 美東時間
    'open': time(18, 0),   # 前一天 18:00
    'close': time(17, 0),  # 當天 17:00
    'daily_break': (time(17, 0), time(18, 0))  # 每天休市 1 小時
}

def find_gaps(instrument, start, end):
    """
    在正常交易時段內，找出連續缺少 2 根以上 1m K 棒的區間
    排除：
      - 每天 17:00~18:00 休市
      - 週末（週五 17:00 ~ 週日 18:00）
      - 美國國定假日
    """
```

---

## 5. 專案結構詳細設計

```
quant-futures/
│
├── app/                            # FastAPI 服務
│   ├── api/
│   │   ├── __init__.py
│   │   ├── kbars.py               # GET /kbars
│   │   ├── coverage.py            # GET /coverage, /coverage/gaps
│   │   └── roll_calendar.py       # GET /roll_calendar
│   ├── core/
│   │   ├── config.py              # 環境變數設定
│   │   └── adjustment.py          # Ratio/Absolute 調整邏輯
│   ├── db/
│   │   └── session.py             # SQLAlchemy async session
│   └── main.py                    # FastAPI app 入口
│
├── fetcher/                        # Fetcher Worker 服務
│   ├── sources/
│   │   ├── base.py                # DataSource 抽象介面
│   │   └── yfinance_source.py     # yfinance 實作
│   ├── pipeline.py                # 數據清洗、去重、寫入
│   ├── roll_detector.py           # 換倉日偵測邏輯
│   ├── scheduler.py               # APScheduler 定時任務
│   └── main.py                    # Worker 入口
│
├── db/
│   ├── schema.sql                 # 完整 DDL（含 TimescaleDB 設定）
│   ├── seed_roll_calendar.sql     # 預填換倉日曆（2008-2030）
│   └── session.py                 # 共用 DB 連線
│
├── scripts/
│   ├── bootstrap_csv.py           # 一次性：匯入 FirstRate CSV
│   └── verify_coverage.py        # 數據完整性檢查
│
├── docs/
│   ├── SPEC.md                    # 本文件（規格）
│   └── SYSTEM_DESIGN.md           # 本文件（設計）
│
├── tests/
│   ├── test_pipeline.py           # 去重、寫入邏輯測試
│   ├── test_adjustment.py         # Roll 調整計算測試
│   └── test_api.py                # API 端點測試
│
├── .env.example                   # 環境變數範本
├── Dockerfile                     # API 服務
├── Dockerfile.fetcher             # Fetcher Worker
├── docker-compose.yml             # 本地開發環境
├── railway.toml                   # Railway 部署設定
├── requirements.txt
└── CLAUDE.md
```

---

## 6. 環境變數設計

```bash
# .env.example

# 資料庫
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/quant_futures

# Railway 環境自動注入：
# ${{PGHOST}}, ${{PGPORT}}, ${{PGUSER}}, ${{PGPASSWORD}}, ${{PGDATABASE}}

# 數據抓取設定
FETCH_INSTRUMENTS=NQ,ES,YM,RTY          # 要抓的商品
FETCH_CRON=0 18 * * 1-5                 # 每週一至週五 18:00 UTC
FETCH_OVERLAP_DAYS=7                     # yfinance 抓取重疊天數

# API 設定
API_HOST=0.0.0.0
API_PORT=8000

# Period 3 用（現在不需要）
# IBKR_HOST=
# IBKR_PORT=4003
# IBKR_CLIENT_ID=1
```

---

## 7. Railway 部署設定

```toml
# railway.toml

[build]
builder = "DOCKERFILE"

[[services]]
name = "api"
dockerfile = "Dockerfile"
healthcheckPath = "/health"
healthcheckTimeout = 30

[[services]]
name = "fetcher"
dockerfile = "Dockerfile.fetcher"
```

```dockerfile
# Dockerfile（API）
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Dockerfile.fetcher（Worker）
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "fetcher/main.py"]
```

---

## 8. 本地開發環境

```yaml
# docker-compose.yml
version: '3.8'
services:
  db:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: quant_futures
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/schema.sql

  api:
    build:
      context: .
      dockerfile: Dockerfile
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - db

  fetcher:
    build:
      context: .
      dockerfile: Dockerfile.fetcher
    env_file: .env
    depends_on:
      - db

volumes:
  pgdata:
```

---

## 9. 技術選型理由

| 技術 | 選擇原因 |
|------|---------|
| TimescaleDB | 時序數據原生支援、Continuous Aggregates 自動推導高時間框架、比純 PostgreSQL 快 100x |
| FastAPI | async 支援、自動 OpenAPI 文件、Python 生態系完整 |
| APScheduler | 輕量、不需 Redis/Celery、適合單一 Worker 定時任務 |
| yfinance | 免費、穩定、CME 期貨數據來源可靠（Yahoo 取自官方） |
| VectorBT（Period 2）| 向量化回測，百萬根 K 棒秒級完成 |
| pandas-ta | 純 Python，90+ 指標，不需編譯 |
| ib_insync（Period 3）| IBKR 官方 Python 非同步封裝，社群活躍 |

---

## 10. 開發里程碑（Period 1）

```
Week 1
  □ docker-compose 本地環境建立
  □ db/schema.sql 完成（含 Continuous Aggregates）
  □ db/seed_roll_calendar.sql 預填 2008-2030 換倉日

Week 2
  □ scripts/bootstrap_csv.py 完成
  □ 匯入 FirstRate Data CSV，驗證數據筆數
  □ scripts/verify_coverage.py 完成，確認無缺口

Week 3
  □ fetcher/ 每日補齊邏輯完成
  □ 本地測試：手動觸發一次，確認寫入正確
  □ roll_detector.py 完成

Week 4
  □ app/ FastAPI 完成（kbars, coverage API）
  □ Railway 部署（API + Fetcher 兩個 Service）
  □ 確認每日自動跑通

Period 1 完成條件：
  □ 四個商品皆有完整歷史數據
  □ 連續 2 週自動補齊正常
  □ coverage API 顯示缺口 < 0.1%
```
