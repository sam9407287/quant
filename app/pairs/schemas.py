"""Pydantic contracts for the pairs lab: scan / backtest configs and responses.

Configs are the reproducibility unit — a scan or run can be replayed from
its stored JSON alone — so every knob is explicit, bounded and defaulted
to the values in the brief (ADR-010 §2.3–2.5).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

HedgeMethod = Literal["ols", "tls"]
ExitRule = Literal["threshold", "cross_zero"]
FillMode = Literal["next_open", "next_close"]
SizingMode = Literal["fractional", "integer"]
WeightScheme = Literal["equal", "inverse_vol"]
PriceSource = Literal["settlement", "snapshot_1m"]
Side = Literal["flat", "long_spread", "short_spread"]
Event = Literal["entry", "exit", "stop", "time_stop", "breakdown", "none"]


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

class QualificationRules(BaseModel):
    """Thresholds a pair must clear to be tradeable (ADR-010 §2.3)."""

    eg_pvalue_max: float = Field(default=0.05, gt=0, le=1)
    half_life_min: float = Field(default=3.0, gt=0)
    half_life_max: float = Field(default=40.0, gt=0)
    stability_lookback: int = Field(default=60, ge=10, le=252)
    stability_min_ratio: float = Field(default=0.8, ge=0, le=1)
    beta_cv_max: float = Field(default=0.5, gt=0)
    require_positive_beta: bool = True
    require_johansen: bool = False

    @model_validator(mode="after")
    def _ordered(self) -> QualificationRules:
        if self.half_life_max <= self.half_life_min:
            raise ValueError("half_life_max must exceed half_life_min")
        return self


class ScanConfig(BaseModel):
    """One screening pass over a set of pairs as of a date."""

    # Which pairs: explicit list, the watchlist, or every ordered pair in the universe.
    mode: Literal["watchlist", "universe", "explicit"] = "watchlist"
    pairs: list[tuple[str, str]] = Field(default_factory=list)  # (y, x) when explicit
    tickers: list[str] = Field(default_factory=list)            # subset for universe mode
    as_of: date | None = None
    formation_window: int = Field(default=504, ge=60, le=2520)
    hedge_method: HedgeMethod = "ols"
    # z window = clip(round(z_window_multiple · HL), min, max). See stats.zscore_window
    # for why the default is 4·HL / 20 rather than the brief's 2·HL / 10.
    z_window_min: int = Field(default=20, ge=5)
    z_window_max: int = Field(default=120, ge=10)
    z_window_multiple: float = Field(default=4.0, gt=0, le=20)
    rules: QualificationRules = Field(default_factory=QualificationRules)
    price_source: PriceSource = "settlement"
    snapshot_time_et: str = "15:00"
    # Rolling stability is the expensive part; it only runs for pairs that
    # pass the point-in-time filters, and may be stepped to save time.
    stability_step: int = Field(default=1, ge=1, le=10)
    max_pairs: int = Field(default=2500, ge=1, le=5000)

    @model_validator(mode="after")
    def _validate(self) -> ScanConfig:
        if self.z_window_max < self.z_window_min:
            raise ValueError("z_window_max must be >= z_window_min")
        if self.mode == "explicit" and not self.pairs:
            raise ValueError("explicit mode needs at least one (y, x) pair")
        for y, x in self.pairs:
            if y == x:
                raise ValueError(f"pair legs must differ: {y}")
        return self


class PairStatsModel(BaseModel):
    """Everything the scan learned about one ordered pair."""

    pair_name: str
    y_ticker: str
    x_ticker: str
    as_of: date
    n_obs: int
    alpha: float
    beta: float
    beta_tls: float | None = None
    beta_johansen: float | None = None
    eg_pvalue: float
    eg_pvalue_reverse: float
    eg_qvalue: float | None = None
    adf_pvalue: float | None = None
    johansen_trace: float
    johansen_crit_95: float
    johansen_pass: bool
    hurst: float | None = None
    half_life: float | None = None
    half_life_ci_low: float | None = None
    half_life_ci_high: float | None = None
    z_window: int
    z: float | None = None
    spread_last: float | None = None
    spread_mean: float | None = None
    spread_std: float | None = None
    stability_ratio: float | None = None
    beta_cv: float | None = None
    corr_returns_60d: float | None = None
    qualified: bool
    reasons: list[str] = Field(default_factory=list)
    roll_gap_days: int = 0
    quality_flags: list[str] = Field(default_factory=list)


class ScanRequest(BaseModel):
    config: ScanConfig = Field(default_factory=ScanConfig)
    notes: str | None = None


class ScanSummary(BaseModel):
    id: str
    created_at: datetime
    as_of: date
    trigger: str
    universe_size: int
    pair_count: int
    qualified_count: int
    runtime_ms: int
    config: dict[str, Any]


class ScanResponse(ScanSummary):
    results: list[PairStatsModel]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class ForwardBucket(BaseModel):
    """Distribution of future spread change conditional on today's z bucket."""

    bucket: str
    z_low: float
    z_high: float
    horizon: int
    count: int
    mean: float
    median: float
    p25: float
    p75: float
    hit_rate: float  # share of cases where the spread moved toward zero


class AnalysisResponse(BaseModel):
    pair_name: str
    y_ticker: str
    x_ticker: str
    stats: PairStatsModel
    dates: list[date]
    log_y: list[float]
    log_x: list[float]
    spread: list[float | None]
    zscore: list[float | None]
    rolling_beta: list[float | None]
    rolling_pvalue: list[float | None]
    forward: list[ForwardBucket]
    roll_dates: list[date]
    settlement_note: str | None = None


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

class SignalRules(BaseModel):
    """Entry / exit / risk rules of the state machine (ADR-010 §2.4)."""

    entry_z: float = Field(default=2.0, gt=0)
    exit_z: float = Field(default=0.5, ge=0)
    exit_rule: ExitRule = "threshold"
    stop_z: float = Field(default=3.5, gt=0)
    time_stop_half_lives: float = Field(default=3.0, gt=0)
    breakdown_pvalue: float = Field(default=0.10, gt=0, le=1)
    breakdown_days: int = Field(default=5, ge=1)
    cooldown_days: int = Field(default=5, ge=0)
    freeze_params: bool = True
    require_qualified: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> SignalRules:
        if self.stop_z <= self.entry_z:
            raise ValueError("stop_z must exceed entry_z")
        if self.exit_z >= self.entry_z:
            raise ValueError("exit_z must be below entry_z")
        return self


class CostModel(BaseModel):
    """Per-contract commission, per-leg slippage in ticks, roll cost."""

    commission_per_contract: float = Field(default=1.25, ge=0)  # per side
    slippage_ticks: float = Field(default=1.0, ge=0)             # per leg per fill
    roll_cost_per_contract: float = Field(default=2.5, ge=0)     # per leg per roll


class PortfolioConfig(BaseModel):
    """Capital allocation across concurrently traded pairs."""

    capital: float = Field(default=1_000_000.0, gt=0)
    gross_leverage: float = Field(default=1.0, gt=0, le=10)
    weight_scheme: WeightScheme = "equal"
    max_concurrent: int = Field(default=10, ge=1, le=100)
    sizing: SizingMode = "fractional"
    prefer_micro: bool = True


class BacktestConfig(BaseModel):
    """One walk-forward run over one or many pairs."""

    pairs: list[tuple[str, str]] = Field(min_length=1)
    start: date | None = None
    end: date | None = None
    formation_window: int = Field(default=504, ge=60, le=2520)
    hedge_method: HedgeMethod = "ols"
    z_window_min: int = Field(default=20, ge=5)
    z_window_max: int = Field(default=120, ge=10)
    z_window_multiple: float = Field(default=4.0, gt=0, le=20)
    fill: FillMode = "next_open"
    rules: SignalRules = Field(default_factory=SignalRules)
    qualification: QualificationRules = Field(default_factory=QualificationRules)
    costs: CostModel = Field(default_factory=CostModel)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    # Sensitivity grid is opt-in: it multiplies runtime by the grid size.
    sensitivity: bool = False
    sensitivity_entry_z: list[float] = Field(default_factory=lambda: [1.5, 2.0, 2.5])
    sensitivity_formation: list[int] = Field(default_factory=lambda: [252, 504])
    # Rolling stability inside a backtest is too slow per day; the gate uses
    # the point-in-time p-value and half-life only, re-checked daily.
    price_source: PriceSource = "settlement"

    @model_validator(mode="after")
    def _validate(self) -> BacktestConfig:
        if self.start and self.end and self.end <= self.start:
            raise ValueError("end must be after start")
        if self.z_window_max < self.z_window_min:
            raise ValueError("z_window_max must be >= z_window_min")
        for y, x in self.pairs:
            if y == x:
                raise ValueError(f"pair legs must differ: {y}")
        return self


class TradeModel(BaseModel):
    pair_name: str
    side: Side
    entry_date: date
    exit_date: date | None
    entry_z: float
    exit_z: float | None
    exit_reason: Event | None
    beta: float
    half_life: float | None
    days_held: int
    y_qty: float
    x_qty: float
    y_contract: str
    x_contract: str
    gross_pnl: float
    costs: float
    net_pnl: float
    notional: float
    rounding_error_pct: float | None = None


class BacktestMetrics(BaseModel):
    total_return: float
    annual_return: float
    annual_vol: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float
    max_drawdown_days: int
    cvar_95: float
    trade_count: int
    win_rate: float | None
    profit_factor: float | None
    avg_hold_days: float | None
    avg_win: float | None
    avg_loss: float | None
    exit_mix: dict[str, int]
    time_in_market: float
    sharpe_ci_low: float | None = None
    sharpe_ci_high: float | None = None
    deflated_sharpe_p: float | None = None
    trials: int = 1
    benchmark_return: float | None = None
    benchmark_max_drawdown: float | None = None
    tradeability_tax: float | None = None  # fractional − integer total return


class PairAttribution(BaseModel):
    pair_name: str
    net_pnl: float
    trade_count: int
    win_rate: float | None
    sharpe: float | None
    max_drawdown: float
    qualified_days: int
    total_days: int


class SensitivityCell(BaseModel):
    entry_z: float
    formation_window: int
    exit_rule: ExitRule
    sharpe: float | None
    total_return: float
    trade_count: int
    max_drawdown: float


class EquityPointModel(BaseModel):
    date: date
    equity: float
    drawdown: float
    positions: int


class BacktestResult(BaseModel):
    metrics: BacktestMetrics
    equity: list[EquityPointModel]
    trades: list[TradeModel]
    attribution: list[PairAttribution]
    correlation: dict[str, Any]
    sensitivity: list[SensitivityCell]
    daily_pnl_by_pair: dict[str, list[float]] | None = None


class BacktestRequest(BaseModel):
    config: BacktestConfig
    notes: str | None = None


class BacktestRunRecord(BaseModel):
    id: str
    created_at: datetime
    config: dict[str, Any]
    metrics: dict[str, Any]
    runtime_ms: int
    notes: str | None = None


class BacktestRunDetail(BacktestRunRecord):
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Watchlist / state / signals
# ---------------------------------------------------------------------------

class WatchlistItem(BaseModel):
    id: str
    name: str
    y_ticker: str
    x_ticker: str
    enabled: bool
    overrides: dict[str, Any]
    rationale: str | None
    created_at: datetime


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    y_ticker: str
    x_ticker: str
    rationale: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _legs(self) -> WatchlistCreate:
        if self.y_ticker == self.x_ticker:
            raise ValueError("pair legs must differ")
        return self


class PairStateModel(BaseModel):
    pair_name: str
    y_ticker: str
    x_ticker: str
    side: Side
    entered_on: date | None
    entry_params: dict[str, Any] | None
    days_held: int
    breakdown_days: int
    cooldown_until: date | None
    last_z: float | None
    as_of: date | None
    updated_at: datetime


class SignalModel(BaseModel):
    id: str
    signal_date: date
    pair_name: str
    event: str
    side: str
    payload: dict[str, Any]
    notified_at: datetime | None
    created_at: datetime


class JobRunModel(BaseModel):
    id: str
    run_date: date
    started_at: datetime
    finished_at: datetime | None
    status: str
    dry_run: bool
    summary: dict[str, Any] | None


class CoverageItem(BaseModel):
    ticker: str
    name: str | None = None
    kind: str | None = None
    first_date: date
    last_date: date
    bar_count: int
    last_fetch: datetime | None = None


class RefreshRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)  # empty = whole universe
    years: int = Field(default=10, ge=1, le=30)
    full: bool = False  # True re-downloads the whole span instead of the overlap


class RefreshResponse(BaseModel):
    tickers: int
    rows_written: int
    issues: list[dict[str, Any]]
    latest_date: date | None
    runtime_ms: int


class UniverseItem(BaseModel):
    ticker: str
    name: str
    group: str
    kind: str
    exchange: str
    settlement_et: str
    registry_symbol: str | None
    contracts: list[dict[str, Any]]
