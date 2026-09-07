"""YAML-first configuration. No scattered magic numbers in strategies."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class LiveGates(BaseModel):
    accept_live_trading: bool = False
    accept_capital_at_risk: bool = False
    i_understand_orders_are_real: bool = False


class CategoryToggles(BaseModel):
    crypto: bool = True
    weather: bool = True
    sports: bool = True
    esports: bool = True
    other: bool = True


class TradingConfig(BaseModel):
    mode: str = "paper"  # backtest | paper | shadow | live
    shadow: bool = False
    session_id: str = "local-paper"
    paper_starting_cash: float = 10_000.0
    paper_fill_ratio: float = 0.55
    min_required_edge: float = 0.012
    min_confidence: float = 0.35
    signal_half_life_ms: float = 2_000.0
    categories: CategoryToggles = Field(default_factory=CategoryToggles)


class ScannerConfig(BaseModel):
    gamma_limit: int = 50
    gamma_offset: int = 0
    max_markets: int = 40
    require_accepting_orders: bool = True
    require_enable_order_book: bool = True
    min_liquidity: float = 200.0
    min_volume_24h: float = 50.0
    max_spread: float = 0.12
    fetch_clob_books: bool = True
    fetch_clob_fees: bool = True
    closed: bool = False
    include_tags: list[str] = Field(default_factory=list)
    exclude_closed: bool = True


class HotMarketWeights(BaseModel):
    liquidity: float = 0.26
    volume: float = 0.20
    spread: float = 0.18
    book_open: float = 0.12
    competitive: float = 0.08
    persistence: float = 0.10
    urgency: float = 0.06


class HotMarketTiers(BaseModel):
    # Mission example (Parte 9): 0–30 COLD, 30–55 WARM, 55–75 HOT, 75–100 ULTRA-HOT
    cold: float = 0.0
    warm: float = 30.0
    hot: float = 55.0
    ultra_hot: float = 75.0


class HotMarketConfig(BaseModel):
    min_score_to_trade: float = 55.0
    weights: HotMarketWeights = Field(default_factory=HotMarketWeights)
    liquidity_ref: float = 10_000.0
    volume_ref: float = 5_000.0
    max_spread_for_full_score: float = 0.08
    tiers: HotMarketTiers = Field(default_factory=HotMarketTiers)


class OpportunityWeights(BaseModel):
    expected_net_edge: float = 1.0
    confidence: float = 1.0
    liquidity: float = 1.0
    persistence: float = 1.0
    execution_probability: float = 1.0


class OpportunityConfig(BaseModel):
    weights: OpportunityWeights = Field(default_factory=OpportunityWeights)
    min_score: float = 0.0


class TwapFairValueConfig(BaseModel):
    """Paper TWAP path. Window is never defaulted — it must be parsed as 30 or 60."""

    enabled: bool = True
    require_parsed_window: bool = True
    # Paper heuristic only — official docs do not publish a settlement vol.
    paper_annualized_vol: float = 0.80
    min_time_remaining_s: float = 1.0


class CryptoFairValueConfig(BaseModel):
    enabled: bool = True
    prior_blend: float = 0.35
    twap: TwapFairValueConfig = Field(default_factory=TwapFairValueConfig)


class WeatherEngineConfig(BaseModel):
    enabled: bool = True
    min_parse_confidence: float = 0.5
    prior_blend: float = 0.35


class SportsEngineConfig(BaseModel):
    enabled: bool = True
    min_parse_confidence: float = 0.5
    prior_blend: float = 0.35
    live_public_client: bool = False


class EsportsEngineConfig(BaseModel):
    """PAPER esports. Live Sports WS unused — official score grammar is too thin."""

    enabled: bool = True
    min_parse_confidence: float = 0.5
    prior_blend: float = 0.35
    live_public_client: bool = False


class BacktestSplitConfig(BaseModel):
    train_end: str | None = None
    validation_end: str | None = None
    oos_start: str | None = None


class WalkForwardConfig(BaseModel):
    enabled: bool = True
    train_seconds: float = 600.0
    test_seconds: float = 300.0
    step_seconds: float = 300.0


class BacktestEngineConfig(BaseModel):
    """PAPER/BACKTEST replay. Assumptions are documented; fees stay dated fixtures."""

    latency_ms: float = 50.0
    taker_delay_ms: float = 80.0
    queue_penalty: float = 0.15
    reject_on_gap: bool = True
    refuse_candle_only: bool = True
    split: BacktestSplitConfig = Field(default_factory=BacktestSplitConfig)
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)


class RecorderConfig(BaseModel):
    """Optional public CLOB/RTDS collect. Default-off live; pytest never opens sockets."""

    default_seconds: float = 20.0
    max_seconds: float = 180.0
    poll_interval_s: float = 2.0
    max_events: int = 400


class TunerConfig(BaseModel):
    """Offline suggestions only. auto_apply cannot write production configs."""

    auto_apply: bool = False


class FairValueConfig(BaseModel):
    latency_haircut: float = 0.0015
    adverse_selection_haircut: float = 0.0020
    fill_penalty: float = 0.0010
    default_confidence: float = 0.55
    crypto: CryptoFairValueConfig = Field(default_factory=CryptoFairValueConfig)


class SizingConfig(BaseModel):
    kelly_fraction: float = 0.10
    max_kelly: float = 0.05
    variance_floor: float = 0.04
    book_frac: float = 0.15


class MakerTakerConfig(BaseModel):
    maker_fill_probability: float = 0.35
    maker_adverse_mult: float = 1.30


class ExperimentConfig(BaseModel):
    strategy_id: str = "crypto_updown"
    version: str = "0.1.0"
    feature_set_version: str = "v1"


class RiskConfig(BaseModel):
    max_order_notional: float = 250.0
    max_market_exposure: float = 750.0
    max_category_exposure: float = 2_000.0
    max_total_exposure: float = 5_000.0
    max_daily_loss: float = 400.0
    max_session_loss: float = 250.0
    max_drawdown: float = 0.12
    max_open_orders: int = 8
    max_concurrent_markets: int = 6
    max_slippage: float = 0.03
    max_spread: float = 0.10
    max_data_age_ms: int = 30_000
    max_latency_ms: int = 1_500
    cooldown_ms: int = 1_500
    cooldown_after_losses_ms: int = 5_000
    runaway_reject_count: int = 5
    no_martingale: bool = True
    max_correlated_exposure: float = 1_500.0
    min_liquidity: float = 200.0
    min_confidence: float = 0.35


class FeedConfig(BaseModel):
    max_data_age_ms: int = 8_000
    critical: bool = False
    ping_interval_s: float | None = None
    # rtds only: optional unauthenticated public RTDS reader (off by default).
    live_public_client: bool = False


class RtdsFeedConfig(FeedConfig):
    """Public RTDS TWAP cache. Subscriber is off unless explicitly enabled."""

    subscriber_enabled: bool = False
    reconnect_max_backoff_s: float = 30.0
    persist_cache: bool = False
    cache_path: str = "data/rtds_twap_cache.json"
    collect_seconds: float = 12.0
    # Empty symbols = official "omit filters", then keep only documented symbols.
    subscribe_symbols: list[str] = Field(default_factory=list)
    subscribe_windows: list[int] = Field(default_factory=lambda: [30, 60])

    @field_validator("subscribe_windows")
    @classmethod
    def _official_windows_only(cls, value: list[int]) -> list[int]:
        from hotflow.official import RTDS_TWAP_WINDOWS

        illegal = [item for item in value if item not in RTDS_TWAP_WINDOWS]
        if illegal:
            raise ValueError(f"subscribe_windows must be official 30/60 only; got {illegal}")
        return value

    @field_validator("subscribe_symbols")
    @classmethod
    def _documented_symbols_only(cls, value: list[str]) -> list[str]:
        from hotflow.official import RTDS_CHAINLINK_SYMBOLS

        lowered = [item.lower() for item in value]
        illegal = [item for item in lowered if item not in RTDS_CHAINLINK_SYMBOLS]
        if illegal:
            raise ValueError(f"subscribe_symbols must be documented Chainlink symbols; got {illegal}")
        return lowered


class SportsWsFeedConfig(FeedConfig):
    """Public Sports WS cache. Subscriber is off unless explicitly enabled."""

    subscriber_enabled: bool = False
    reconnect_max_backoff_s: float = 30.0
    persist_cache: bool = False
    cache_path: str = "data/sports_ws_cache.json"
    collect_seconds: float = 12.0


class FeedsConfig(BaseModel):
    gamma: FeedConfig = Field(default_factory=lambda: FeedConfig(max_data_age_ms=30_000))
    clob_book: FeedConfig = Field(
        default_factory=lambda: FeedConfig(max_data_age_ms=30_000, critical=True)
    )
    clob_fees: FeedConfig = Field(
        default_factory=lambda: FeedConfig(max_data_age_ms=60_000, critical=True)
    )
    market_ws: FeedConfig = Field(
        default_factory=lambda: FeedConfig(max_data_age_ms=15_000, critical=True, ping_interval_s=10)
    )
    user_ws: FeedConfig = Field(
        default_factory=lambda: FeedConfig(max_data_age_ms=15_000, critical=True, ping_interval_s=10)
    )
    rtds: RtdsFeedConfig = Field(
        default_factory=lambda: RtdsFeedConfig(max_data_age_ms=10_000, ping_interval_s=5)
    )
    sports_ws: SportsWsFeedConfig = Field(
        default_factory=lambda: SportsWsFeedConfig(max_data_age_ms=15_000, ping_interval_s=5)
    )


class AIResearchConfig(BaseModel):
    base_url: str = "https://api.moonshot.ai/v1"
    model: str = "kimi-k3"
    reasoning_effort: str = "high"
    hard_task_reasoning_effort: str = "max"
    timeout_s: int = 120


class StorageConfig(BaseModel):
    sqlite_path: str = "data/hotflow.sqlite"
    parquet_dir: str = "data/parquet"
    reports_dir: str = "reports"


class MonitoringConfig(BaseModel):
    prometheus_port: int = 9108
    json_logs: bool = True
    http_enabled: bool = False
    http_bind: str = "127.0.0.1"
    alert_drawdown: float = 0.08
    alert_latency_ms: float = 800.0
    alert_slippage: float = 0.02


class HotflowConfig(BaseModel):
    trading: TradingConfig = Field(default_factory=TradingConfig)
    live: LiveGates = Field(default_factory=LiveGates)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    hot_market: HotMarketConfig = Field(default_factory=HotMarketConfig)
    opportunity: OpportunityConfig = Field(default_factory=OpportunityConfig)
    fair_value: FairValueConfig = Field(default_factory=FairValueConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    feeds: FeedsConfig = Field(default_factory=FeedsConfig)
    ai_research: AIResearchConfig = Field(default_factory=AIResearchConfig)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    maker_taker: MakerTakerConfig = Field(default_factory=MakerTakerConfig)
    experiment: ExperimentConfig = Field(default_factory=ExperimentConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    weather: WeatherEngineConfig = Field(default_factory=WeatherEngineConfig)
    sports: SportsEngineConfig = Field(default_factory=SportsEngineConfig)
    esports: EsportsEngineConfig = Field(default_factory=EsportsEngineConfig)
    backtest: BacktestEngineConfig = Field(default_factory=BacktestEngineConfig)
    recorder: RecorderConfig = Field(default_factory=RecorderConfig)
    tuner: TunerConfig = Field(default_factory=TunerConfig)

    @property
    def is_paper(self) -> bool:
        return self.trading.mode.lower() not in {"live"}

    @property
    def is_shadow(self) -> bool:
        return self.trading.shadow or self.trading.mode.lower() == "shadow"

    @property
    def is_backtest(self) -> bool:
        return self.trading.mode.lower() == "backtest"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def default_config_path() -> Path:
    env = os.environ.get("HOTFLOW_CONFIG")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parents[2]
    return here / "configs" / "default.yaml"


def load_config(path: str | Path | None = None) -> HotflowConfig:
    target = Path(path) if path else default_config_path()
    raw: dict[str, Any] = {}
    if target.exists():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config {target} must be a mapping")
        raw = loaded
    mode = os.environ.get("HOTFLOW_TRADING_MODE")
    if mode:
        raw = _deep_merge(raw, {"trading": {"mode": mode}})
    return HotflowConfig.model_validate(raw)
