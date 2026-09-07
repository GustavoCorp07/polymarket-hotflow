"""Shared domain types. Prices and sizes use float for paper math; venue
strings stay strings. Exchange parameters (fees, tick, min size) are always
carried from API payloads — never invented here."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TradingMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class LiquidityStyle(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


class ResourceTier(StrEnum):
    COLD = "COLD"
    WARM = "WARM"
    HOT = "HOT"
    ULTRA_HOT = "ULTRA-HOT"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class KillSwitchReason(StrEnum):
    STALE_WS = "STALE_WS"
    AUTH_FAIL = "AUTH_FAIL"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    RUNAWAY_REJECTS = "RUNAWAY_REJECTS"
    MANUAL = "MANUAL"
    DATA_FEED_DEAD = "DATA_FEED_DEAD"
    STALE_CRITICAL_DATA = "STALE_CRITICAL_DATA"
    IMPOSSIBLE_PNL = "IMPOSSIBLE_PNL"
    EXCESSIVE_LATENCY = "EXCESSIVE_LATENCY"
    ABNORMAL_SLIPPAGE = "ABNORMAL_SLIPPAGE"
    DUPLICATED_ORDERS = "DUPLICATED_ORDERS"
    DRAWDOWN_EXCEEDED = "DRAWDOWN_EXCEEDED"
    DAILY_LOSS_EXCEEDED = "DAILY_LOSS_EXCEEDED"


class BookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    token_id: str
    condition_id: str | None = None
    bids: list[BookLevel] = Field(default_factory=list)
    asks: list[BookLevel] = Field(default_factory=list)
    min_order_size: float | None = None
    tick_size: float | None = None
    timestamp_ms: int | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "clob_book"

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return max(0.0, self.best_ask - self.best_bid)

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0


class FeeSchedule(BaseModel):
    """Copied from official Gamma/CLOB payloads — not a category default."""

    enabled: bool | None = None
    rate: float | None = None
    exponent: float | None = None
    taker_only: bool | None = True
    rebate_rate: float | None = None
    maker_base_fee_bp: int | None = None
    taker_base_fee_bp: int | None = None
    clob_base_fee_bp: int | None = None
    source: str = "unknown"
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def known(self) -> bool:
        return self.enabled is not None


class TwapResolutionSpec(BaseModel):
    """Parsed official TWAP identity. Incomplete specs must not be filled in."""

    is_twap_market: bool = False
    feed: str | None = None
    window_seconds: int | None = None
    symbol: str | None = None
    opening_reference: float | None = None
    strike: float | None = None
    final_calculation_rule: str = ""
    official_settlement_formula_published: bool = False
    skip_reason: str | None = None
    complete: bool = False
    source_text: str = ""


class OfficialTwapObservation(BaseModel):
    """One official Chainlink TWAP print (RTDS payload or fixture of that shape)."""

    symbol: str
    window_seconds: int
    value: float
    full_accuracy_value: str | None = None
    payload_timestamp_ms: int | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "fixture"
    topic: str | None = None


class TwapSnapshot(BaseModel):
    current_twap: float
    projected_twap: float
    distance_to_strike: float
    time_remaining_s: float
    required_future_price: float
    probability_of_finish_above: float
    probability_of_finish_below: float
    window_seconds: int
    symbol: str
    opening_reference: float | None = None
    strike: float
    feed: str | None = None
    source: str = "fixture"
    final_calculation_rule: str = ""
    skip_reason: str | None = None


class WeatherResolutionSpec(BaseModel):
    city: str | None = None
    station: str | None = None
    metric: str | None = None
    unit: str | None = None
    time_window: str | None = None
    timezone: str | None = None
    rounding_rule: str | None = None
    threshold: float | None = None
    comparison: str | None = None
    source: str | None = None
    parse_confidence: float = 0.0
    complete: bool = False
    skip_reason: str | None = None
    source_text: str = ""


class WeatherForecast(BaseModel):
    """External forecast features only — never a substitute for resolution source."""

    mean: float | None = None
    median: float | None = None
    std: float | None = None
    p_above_threshold: float | None = None
    p_yes: float | None = None
    ensemble_spread: float | None = None
    source: str = "fixture"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SportsResolutionSpec(BaseModel):
    league: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    period: str | None = None
    live: bool | None = None
    ended: bool | None = None
    score: str | None = None
    sports_market_type: str | None = None
    game_start: str | None = None
    source: str | None = None
    parse_confidence: float = 0.0
    complete: bool = False
    skip_reason: str | None = None
    source_text: str = ""


class EsportsResolutionSpec(BaseModel):
    """Parsed esports identity from public Gamma text. Incomplete specs must skip."""

    game: str | None = None
    tournament: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    match_format: str | None = None
    best_of: int | None = None
    map_or_game_index: int | None = None
    sports_market_type: str | None = None
    source: str | None = None
    parse_confidence: float = 0.0
    complete: bool = False
    skip_reason: str | None = None
    source_text: str = ""


class SportsGameState(BaseModel):
    """Official Sports WS game object fields only (raw or SDK payload)."""

    game_id: int | None = None
    league_abbreviation: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    status: str | None = None
    live: bool | None = None
    ended: bool | None = None
    score: str | None = None
    period: str | None = None
    elapsed: str | None = None
    slug: str | None = None
    turn: str | None = None
    finished_at: str | None = None
    last_update: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "fixture"


class ResolutionMeta(BaseModel):
    source: str | None = None
    uma_status: str | None = None
    end_date: str | None = None
    resolved_by: str | None = None
    automatically_resolved: bool | None = None
    metric: str | None = None
    threshold: str | None = None
    time_window: str | None = None
    timezone: str | None = None
    rounding_rule: str | None = None
    special_conditions: list[str] = Field(default_factory=list)
    parse_confidence: float = 0.0
    tradeable: bool = False


class MarketRecord(BaseModel):
    market_id: str
    condition_id: str | None = None
    slug: str | None = None
    question: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    token_ids: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    enable_order_book: bool | None = None
    accepting_orders: bool | None = None
    liquidity: float | None = None
    volume: float | None = None
    volume_24hr: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    last_trade_price: float | None = None
    competitive: float | None = None
    order_min_size: float | None = None
    tick_size: float | None = None
    fees: FeeSchedule = Field(default_factory=FeeSchedule)
    resolution: ResolutionMeta = Field(default_factory=ResolutionMeta)
    book: OrderBook | None = None
    raw_gamma: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HotMarketResult(BaseModel):
    market_id: str
    score: float
    tier: ResourceTier
    components: dict[str, float] = Field(default_factory=dict)


class EdgeBreakdown(BaseModel):
    p_fair: float
    market_price: float
    raw_edge: float
    fee_per_share: float
    spread_cost: float
    slippage: float
    latency_haircut: float
    adverse_selection: float
    fill_penalty: float = 0.0
    net_expected_edge: float
    confidence: float
    fee_rate_used: float | None = None
    skip: bool = False
    reason: str | None = None
    current_twap: float | None = None
    projected_twap: float | None = None
    distance_to_strike: float | None = None
    time_remaining_s: float | None = None
    required_future_price: float | None = None
    probability_of_finish_above: float | None = None
    probability_of_finish_below: float | None = None
    twap_window_seconds: int | None = None
    twap_symbol: str | None = None
    twap_source: str | None = None


class Opportunity(BaseModel):
    market_id: str
    token_id: str
    side: Side
    score: float
    hms: HotMarketResult
    edge: EdgeBreakdown
    liquidity_factor: float
    persistence: float
    execution_probability: float
    intended_shares: float
    intended_notional: float
    style: LiquidityStyle = LiquidityStyle.TAKER
    ev_maker: float = 0.0
    ev_taker: float = 0.0
    pnl_velocity: float = 0.0
    signal_half_life_ms: float = 0.0


class SignalAudit(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    market_id: str
    accepted: bool
    reason: str
    detail: str = ""
    hms: float | None = None
    tier: str | None = None
    net_edge: float | None = None
    opportunity_score: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RiskDecision(BaseModel):
    allowed: bool
    reason: str
    detail: str = ""
    veto: bool = False


class OrderRecord(BaseModel):
    client_order_id: str
    status: OrderStatus
    market_id: str
    token_id: str
    side: Side
    price: float
    size: float
    filled_size: float = 0.0
    avg_fill_price: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reject_reason: str | None = None
    venue_order_id: str | None = None
    mode: TradingMode = TradingMode.PAPER
