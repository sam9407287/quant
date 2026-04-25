# 系統規格文件 (SPEC)

## 1. 系統目標

建立一個針對 CME 美國指數期貨的量化分析平台，具備：
- 完整歷史 K 棒數據收集與持續更新
- 多時間框架技術訊號分析
- 策略回測引擎
- 未來擴充至即時分析與自動下單

## 2. 目標商品

| 代號 | 全名 | yfinance 代碼 | 交易所 |
|------|------|--------------|--------|
| NQ | E-mini Nasdaq-100 | NQ=F | CME |
| ES | E-mini S&P 500 | ES=F | CME |
| YM | E-mini Dow Jones | YM=F | CBOT |
| RTY | E-mini Russell 2000 | RTY=F | CME |

## 3. 三個開發時期

### Period 1：數據收集期（當前目標）

**目標：** 建立穩定、乾淨、持續更新的 1m K 棒資料庫

**功能需求：**
- [ ] 一次性匯入 FirstRate Data 歷史 CSV（2008 年起）
- [ ] 每日自動補齊最新 1m K 棒（收盤後執行）
- [ ] 數據完整性驗證（偵測缺口、異常值）
- [ ] 換倉日曆維護（每季自動記錄換倉資訊）
- [ ] REST API 查詢 K 棒（支援任意時間框架）
- [ ] 數據覆蓋率查詢 API

**完成條件：**
- 四個商品皆有 2008 年起完整 1m 數據
- 每日自動補齊運作穩定超過 2 週
- 缺口偵測無發現遺漏

---

### Period 2：策略研究期（Period 1 完成後）

**目標：** 基於存好的數據開發、驗證交易訊號

**功能需求：**
- [ ] 技術指標計算 API（EMA, RSI, MACD, ATR, BB, Volume MA）
- [ ] 多時間框架指標查詢（同時取得 1m/5m/15m/1h/4h/1d 指標）
- [ ] 訊號定義與儲存（訊號類型、方向、強度、進出場位）
- [ ] 回測引擎（VectorBT 整合）
- [ ] 回測報告（總報酬、Sharpe、最大回撤、勝率、獲利因子）
- [ ] Walk-forward 驗證
- [ ] 訊號歷史查詢 API

**完成條件：**
- 至少一個策略完成回測並有可接受的績效指標
- Sharpe Ratio > 1.0，最大回撤 < 20%

---

### Period 3：即時交易期（Period 2 完成後）

**目標：** 接入即時數據，執行驗證過的策略

**功能需求：**
- [ ] IBKR TWS API 即時 1m 數據接收
- [ ] 即時訊號偵測（WebSocket 推送）
- [ ] 自動下單模組（市價單、限價單、止損單）
- [ ] 倉位管理與風險控管
- [ ] 即時 P&L 追蹤
- [ ] Paper Trading 模式（測試用）
- [ ] 緊急停止機制（Kill Switch）

**完成條件：**
- Paper Trading 穩定運行 30 天，訊號與實際執行一致

---

## 4. 非功能性需求

| 需求 | 規格 |
|------|------|
| 數據延遲（Period 1-2）| 每日更新，T+0 日 18:00 EST 後完成 |
| 數據延遲（Period 3）| < 500ms（即時訊號） |
| 資料庫查詢效能 | 單商品 1 年 1m 數據查詢 < 2 秒 |
| 系統可用性 | 99%（Railway Pro SLA） |
| 數據完整性 | 缺口 < 0.1%（期貨正常交易時段） |
| 部署環境 | Railway Pro（已有帳號） |

## 5. 多時間框架分析規格

```
分析層級          時間框架      用途
─────────────────────────────────────────
環境判斷          Weekly, Daily  市場趨勢、多空環境
方向確認          4H, 1H         主要趨勢方向、關鍵結構位
訊號觸發          15m, 5m        進場形態確認
精確執行          1m             精確進出場位置
```

**查詢方式：** 所有時間框架由 1m 原始數據推導，不單獨儲存（TimescaleDB Continuous Aggregates）

## 6. API 端點規格

### Period 1 API

```
GET /api/kbars
  ?instrument=NQ
  ?timeframe=1m|5m|15m|1h|4h|1d|1w
  ?start=2024-01-01T00:00:00Z
  ?end=2024-12-31T23:59:59Z
  ?adjustment=raw|ratio|absolute   (預設 ratio)
  回傳：[{ts, open, high, low, close, volume}]

GET /api/coverage
  ?instrument=NQ|ES|YM|RTY|all
  回傳：{instrument, earliest, latest, bar_count, gaps}

GET /api/coverage/gaps
  ?instrument=NQ
  ?start=2024-01-01
  ?end=2024-12-31
  回傳：[{gap_start, gap_end, missing_bars}]

GET /api/roll_calendar
  ?instrument=NQ
  ?year=2024
  回傳：[{old_contract, new_contract, roll_date, price_diff, ratio}]
```

### Period 2 追加 API

```
GET /api/indicators
  ?instrument=NQ&timeframe=1h
  ?start=...&end=...
  ?indicators=ema20,ema60,rsi14,macd,atr14

GET /api/signals
  ?instrument=NQ&strategy=trend_follow
  ?start=...&end=...

POST /api/backtest
  body: {strategy, instrument, params, start, end}
  回傳：{report_id}

GET /api/backtest/{report_id}
  回傳：{total_return, sharpe, max_drawdown, win_rate, trades}
```

## 7. 數據品質標準

```
有效的期貨交易時段（CME Globex）：
  週日 18:00 ~ 週五 17:00 ET
  每天 17:00 ~ 18:00 ET 為每日結算休市（不計入缺口）

異常值判斷：
  單根 K 棒漲跌超過 5% → 標記為疑似異常，人工確認
  Volume = 0 → 非交易時段，正常

缺口定義：
  正常交易時段內連續缺少 2 根以上 1m K 棒
```
