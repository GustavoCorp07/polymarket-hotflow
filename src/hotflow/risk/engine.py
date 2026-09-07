"""Risk engine: absolute VETO. NO TRADE is valid. No martingale."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hotflow.config import RiskConfig
from hotflow.reason_codes import ReasonCode
from hotflow.risk.kill_switch import KillSwitchBoard
from hotflow.types import KillSwitchReason, Opportunity, RiskDecision


@dataclass
class RiskState:
    market_exposure: dict[str, float] = field(default_factory=dict)
    category_exposure: dict[str, float] = field(default_factory=dict)
    total_exposure: float = 0.0
    daily_pnl: float = 0.0
    session_pnl: float = 0.0
    peak_equity: float = 0.0
    equity: float = 0.0
    open_orders: int = 0
    concurrent_markets: set[str] = field(default_factory=set)
    last_order_at: datetime | None = None
    reject_streak: int = 0
    last_order_notional: float = 0.0
    last_was_loss: bool = False


class RiskEngine:
    def __init__(self, config: RiskConfig, kills: KillSwitchBoard | None = None) -> None:
        self.config = config
        self.kills = kills or KillSwitchBoard()
        self.state = RiskState()

    def note_reject(self) -> None:
        self.state.reject_streak += 1
        if self.state.reject_streak >= self.config.runaway_reject_count:
            self.kills.trip(KillSwitchReason.RUNAWAY_REJECTS, "reject streak")

    def note_fill(self, *, market_id: str, category: str, notional: float, pnl_delta: float = 0.0) -> None:
        self.state.reject_streak = 0
        self.state.market_exposure[market_id] = self.state.market_exposure.get(market_id, 0.0) + notional
        self.state.category_exposure[category] = self.state.category_exposure.get(category, 0.0) + notional
        self.state.total_exposure += notional
        self.state.session_pnl += pnl_delta
        self.state.daily_pnl += pnl_delta
        self.state.equity += pnl_delta
        self.state.peak_equity = max(self.state.peak_equity, self.state.equity)
        self.state.concurrent_markets.add(market_id)
        self.state.last_order_notional = notional
        self.state.last_was_loss = pnl_delta < 0

    def sync_from_ledger(self, snap: Any) -> None:
        """Copy paper-ledger equity / PnL / exposure. Does not invent venue balances."""
        self.state.equity = float(snap.equity)
        self.state.peak_equity = float(snap.peak_equity)
        self.state.session_pnl = float(snap.session_pnl)
        self.state.daily_pnl = float(snap.realized_pnl)
        exposure: dict[str, float] = {}
        total = 0.0
        for token, row in (snap.positions or {}).items():
            notional = abs(float(row.get("qty") or 0.0) * float(row.get("mark") or row.get("avg_cost") or 0.0))
            exposure[str(token)] = notional
            total += notional
        if exposure:
            self.state.market_exposure = exposure
            self.state.total_exposure = total

    def enforce_session_limits(self) -> RiskDecision | None:
        """Trip kill switch after fills if daily loss or drawdown is breached."""
        cfg = self.config
        if self.state.daily_pnl <= -abs(cfg.max_daily_loss):
            self.kills.trip(KillSwitchReason.DAILY_LOSS_EXCEEDED, "max_daily_loss")
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_daily_loss")
        if self.state.session_pnl <= -abs(cfg.max_session_loss):
            self.kills.trip(KillSwitchReason.DAILY_LOSS_EXCEEDED, "max_session_loss")
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_session_loss")
        if self.state.peak_equity > 0:
            dd = (self.state.peak_equity - self.state.equity) / self.state.peak_equity
            if dd >= cfg.max_drawdown:
                self.kills.trip(KillSwitchReason.DRAWDOWN_EXCEEDED, "max_drawdown")
                return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_drawdown")
        return None

    def decide(
        self,
        opp: Opportunity,
        *,
        category: str,
        spread: float | None,
        data_age_ms: float | None,
        latency_ms: float | None,
        now: datetime | None = None,
        requested_notional: float | None = None,
        enforce_cooldown: bool = True,
    ) -> RiskDecision:
        if self.kills.tripped:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.KILL_SWITCH, detail=str(self.kills.reason))

        notional = requested_notional if requested_notional is not None else opp.intended_notional
        cfg = self.config

        if cfg.no_martingale and self.state.last_was_loss and notional > self.state.last_order_notional + 1e-9:
            return RiskDecision(
                allowed=False,
                veto=True,
                reason=ReasonCode.MARTINGALE_BLOCKED,
                detail="no auto risk-up after losses",
            )

        if notional > cfg.max_order_notional + 1e-9:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_order_notional")

        market_exp = self.state.market_exposure.get(opp.market_id, 0.0) + notional
        if market_exp > cfg.max_market_exposure:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_market_exposure")

        cat_exp = self.state.category_exposure.get(category, 0.0) + notional
        if cat_exp > cfg.max_category_exposure:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_category_exposure")

        if self.state.total_exposure + notional > cfg.max_total_exposure:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_total_exposure")

        if self.state.daily_pnl <= -abs(cfg.max_daily_loss):
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_daily_loss")

        if self.state.session_pnl <= -abs(cfg.max_session_loss):
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_session_loss")

        if self.state.peak_equity > 0:
            dd = (self.state.peak_equity - self.state.equity) / self.state.peak_equity
            if dd >= cfg.max_drawdown:
                self.kills.trip(KillSwitchReason.DRAWDOWN_EXCEEDED, "max_drawdown")
                return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_drawdown")

        if self.state.open_orders >= cfg.max_open_orders:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_open_orders")

        extra_market = opp.market_id not in self.state.concurrent_markets
        if extra_market and len(self.state.concurrent_markets) >= cfg.max_concurrent_markets:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.RISK_LIMIT, detail="max_concurrent_markets")

        if opp.edge.confidence < cfg.min_confidence:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.LOW_CONFIDENCE, detail="min_confidence")

        if spread is not None and spread > cfg.max_spread:
            return RiskDecision(
                allowed=False, veto=True, reason=ReasonCode.SPREAD_TOO_LARGE, detail="max_spread"
            )

        other_cat = self.state.category_exposure.get(category, 0.0)
        if other_cat + notional > cfg.max_correlated_exposure and extra_market:
            return RiskDecision(
                allowed=False, veto=True, reason=ReasonCode.CORRELATED_EXPOSURE, detail="max_correlated_exposure"
            )

        if opp.edge.slippage > cfg.max_slippage:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.SLIPPAGE_TOO_HIGH, detail="max_slippage")

        if data_age_ms is not None and data_age_ms > cfg.max_data_age_ms:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.STALE_DATA, detail="max_data_age")

        if latency_ms is not None and latency_ms > cfg.max_latency_ms:
            return RiskDecision(allowed=False, veto=True, reason=ReasonCode.LATENCY, detail="max_latency")

        current = now or datetime.now(UTC)
        if enforce_cooldown and self.state.last_order_at is not None:
            elapsed_ms = (current - self.state.last_order_at).total_seconds() * 1000.0
            needed = cfg.cooldown_after_losses_ms if self.state.last_was_loss else cfg.cooldown_ms
            if elapsed_ms < needed:
                return RiskDecision(allowed=False, veto=True, reason=ReasonCode.COOLDOWN, detail="cooldown")

        return RiskDecision(allowed=True, veto=False, reason=ReasonCode.OK)
