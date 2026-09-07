"""Parte 24 — rank and propose sizes. Risk VETO remains absolute.

The allocator never places orders. It ranks simultaneous candidates by
opportunity / risk-adjusted PnL velocity (not velocity alone) and clips or
skips against explicit correlation buckets plus risk concentration caps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from hotflow.config import PortfolioConfig, RiskConfig
from hotflow.portfolio.correlation import (
    ExposureIdentity,
    OpenExposure,
    correlation_hits,
    extract_identity,
    group_buckets,
)
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord, Opportunity

AllocationAction = Literal["TAKE", "DOWNSIZE", "SKIP"]


@dataclass
class AllocationCandidate:
    market_id: str
    category: str
    intended_notional: float
    opportunity_score: float
    pnl_velocity: float
    net_edge: float
    liquidity: float
    identity: ExposureIdentity
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_opportunity(
        cls,
        opp: Opportunity,
        *,
        market: MarketRecord,
        category: str,
        identity: ExposureIdentity | None = None,
    ) -> AllocationCandidate:
        return cls(
            market_id=opp.market_id,
            category=category,
            intended_notional=float(opp.intended_notional),
            opportunity_score=float(opp.score),
            pnl_velocity=float(opp.pnl_velocity),
            net_edge=float(opp.edge.net_expected_edge),
            liquidity=float(market.liquidity or 0.0),
            identity=identity or extract_identity(market, category=category),
        )


@dataclass
class AllocationDecision:
    market_id: str
    action: AllocationAction
    intended_notional: float
    allocated_notional: float
    rank_score: float
    reason: str
    detail: str = ""
    groups: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "action": self.action,
            "intended_notional": self.intended_notional,
            "allocated_notional": self.allocated_notional,
            "rank_score": self.rank_score,
            "reason": self.reason,
            "detail": self.detail,
            "groups": list(self.groups),
            "assumptions": list(self.assumptions),
            "hits": list(self.hits),
        }


def _unit(value: float, lo: float, hi: float) -> float:
    if hi - lo <= 1e-12:
        return 1.0 if value > 0 else 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def rank_score(
    candidate: AllocationCandidate, config: PortfolioConfig, *, norms: dict[str, tuple[float, float]]
) -> float:
    w = config.rank
    opp = _unit(candidate.opportunity_score, *norms["opportunity"])
    vel = _unit(max(0.0, candidate.pnl_velocity), *norms["pnl_velocity"])
    edge = _unit(max(0.0, candidate.net_edge), *norms["net_edge"])
    liq = _unit(max(0.0, candidate.liquidity), *norms["liquidity"])
    return w.opportunity * opp + w.pnl_velocity * vel + w.net_edge * edge + w.liquidity * liq


def _norms(candidates: list[AllocationCandidate]) -> dict[str, tuple[float, float]]:
    def span(values: list[float]) -> tuple[float, float]:
        return (min(values), max(values)) if values else (0.0, 1.0)

    return {
        "opportunity": span([item.opportunity_score for item in candidates]),
        "pnl_velocity": span([max(0.0, item.pnl_velocity) for item in candidates]),
        "net_edge": span([max(0.0, item.net_edge) for item in candidates]),
        "liquidity": span([max(0.0, item.liquidity) for item in candidates]),
    }


def _group_cap(
    group_id: str,
    config: PortfolioConfig,
    risk: RiskConfig,
    *,
    regime_labels: set[str],
) -> tuple[float, int, str]:
    group = next((item for item in config.groups if item.id == group_id), None)
    if group is None:
        return risk.max_correlated_exposure, 1, "missing_group"
    cap = group.max_exposure if group.max_exposure is not None else risk.max_correlated_exposure
    assumption = group.assumption.strip()
    for regime in config.regimes:
        if regime.id not in regime_labels:
            continue
        scale = regime.group_scales.get(group_id)
        if scale is None:
            continue
        cap *= scale
        assumption = f"{assumption} Regime {regime.id}: {regime.assumption.strip()} scale={scale}."
    return cap, group.max_markets, assumption


class PortfolioAllocator:
    def __init__(self, config: PortfolioConfig, risk: RiskConfig) -> None:
        self.config = config
        self.risk = risk

    def allocate(
        self,
        candidates: list[AllocationCandidate],
        *,
        existing: list[OpenExposure] | None = None,
        category_exposure: dict[str, float] | None = None,
        total_exposure: float = 0.0,
        concurrent_markets: set[str] | None = None,
    ) -> list[AllocationDecision]:
        if not candidates:
            return []
        if not self.config.enabled:
            return [
                AllocationDecision(
                    market_id=item.market_id,
                    action="TAKE",
                    intended_notional=item.intended_notional,
                    allocated_notional=item.intended_notional,
                    rank_score=0.0,
                    reason=ReasonCode.OK,
                    detail="portfolio_disabled",
                )
                for item in candidates
            ]

        open_rows = list(existing or [])
        cat_exp = dict(category_exposure or {})
        total = float(total_exposure)
        open_ids = set(concurrent_markets or {row.market_id for row in open_rows})
        reserved: list[OpenExposure] = []
        norms = _norms(candidates)
        ranked = sorted(
            candidates,
            key=lambda item: (
                -rank_score(item, self.config, norms=norms),
                -item.opportunity_score,
                item.market_id,
            ),
        )
        by_id: dict[str, AllocationDecision] = {}
        for item in ranked:
            by_id[item.market_id] = self._place(
                item,
                existing=open_rows + reserved,
                category_exposure=cat_exp,
                total_exposure=total,
                concurrent_markets=open_ids,
                rank=rank_score(item, self.config, norms=norms),
            )
            decision = by_id[item.market_id]
            if decision.action != "SKIP" and decision.allocated_notional > 0:
                reserved.append(
                    OpenExposure(
                        market_id=item.market_id,
                        category=item.category,
                        notional=decision.allocated_notional,
                        identity=item.identity,
                    )
                )
                cat_exp[item.category] = cat_exp.get(item.category, 0.0) + decision.allocated_notional
                total += decision.allocated_notional
                open_ids.add(item.market_id)
        return [by_id[item.market_id] for item in candidates]

    def _place(
        self,
        item: AllocationCandidate,
        *,
        existing: list[OpenExposure],
        category_exposure: dict[str, float],
        total_exposure: float,
        concurrent_markets: set[str],
        rank: float,
    ) -> AllocationDecision:
        intended = max(0.0, item.intended_notional)
        groups = [bucket for _, bucket in group_buckets(item.identity, self.config.groups)]
        assumptions = list(item.identity.source_notes)
        hits: list[str] = []
        if intended <= 0:
            return AllocationDecision(
                market_id=item.market_id,
                action="SKIP",
                intended_notional=intended,
                allocated_notional=0.0,
                rank_score=rank,
                reason=ReasonCode.BELOW_MIN_SIZE,
                detail="zero_intended",
                groups=groups,
                assumptions=assumptions,
            )

        room = intended
        skip_reason = ReasonCode.OK
        skip_detail = ""

        extra_market = item.market_id not in concurrent_markets
        max_open = self.risk.max_concurrent_markets
        if extra_market and len(concurrent_markets) >= max_open:
            room = 0.0
            skip_reason = ReasonCode.PORTFOLIO_CONCENTRATION
            skip_detail = "max_concurrent_markets"

        cat_room = max(0.0, self.risk.max_category_exposure - category_exposure.get(item.category, 0.0))
        total_room = max(0.0, self.risk.max_total_exposure - total_exposure)
        order_room = self.risk.max_order_notional
        if room > 0 and cat_room <= 1e-12:
            room = 0.0
            skip_reason = ReasonCode.PORTFOLIO_CONCENTRATION
            skip_detail = "max_category_exposure"
        if room > 0 and total_room <= 1e-12:
            room = 0.0
            skip_reason = ReasonCode.PORTFOLIO_CONCENTRATION
            skip_detail = "max_total_exposure"
        room = min(room, cat_room, total_room, order_room)

        for other in existing:
            pair_hits = correlation_hits(item.identity, other.identity, self.config)
            if not pair_hits:
                continue
            for hit in pair_hits:
                hits.append(f"{hit.rule}:{hit.bucket}")
                assumptions.append(hit.assumption)

        correlated_notional = sum(
            other.notional
            for other in existing
            if other.market_id != item.market_id and correlation_hits(item.identity, other.identity, self.config)
        )
        corr_room = max(0.0, self.risk.max_correlated_exposure - correlated_notional)
        if room > 0 and corr_room <= 1e-12 and correlated_notional > 0:
            room = 0.0
            skip_reason = ReasonCode.CORRELATED_EXPOSURE
            skip_detail = "max_correlated_exposure"
        elif correlated_notional > 0:
            room = min(room, corr_room)

        for group_id, bucket in group_buckets(item.identity, self.config.groups):
            members = [
                other
                for other in existing
                if other.market_id != item.market_id
                and any(b == bucket for _, b in group_buckets(other.identity, self.config.groups))
            ]
            group_labels = set(item.identity.regime_labels)
            if item.identity.regime_label:
                group_labels.add(item.identity.regime_label)
            for other in members:
                group_labels.update(other.identity.regime_labels)
                if other.identity.regime_label:
                    group_labels.add(other.identity.regime_label)
            cap, max_markets, assumption = _group_cap(
                group_id, self.config, self.risk, regime_labels=group_labels
            )
            assumptions.append(assumption)
            used = sum(other.notional for other in members)
            names = {other.market_id for other in members}
            if item.market_id not in names and len(names) >= max_markets:
                room = 0.0
                skip_reason = ReasonCode.CORRELATED_EXPOSURE
                skip_detail = f"group:{group_id}:max_markets"
                hits.append(f"yaml_group:{bucket}")
                break
            group_room = max(0.0, cap - used)
            if group_room <= 1e-12 and (used > 0 or names):
                room = 0.0
                skip_reason = ReasonCode.CORRELATED_EXPOSURE
                skip_detail = f"group:{group_id}:max_exposure"
                hits.append(f"yaml_group:{bucket}")
                break
            room = min(room, group_room)

        unique_assumptions = list(dict.fromkeys(item for item in assumptions if item))
        unique_hits = list(dict.fromkeys(hits))
        unique_groups = list(dict.fromkeys(groups))

        if room <= 1e-12:
            return AllocationDecision(
                market_id=item.market_id,
                action="SKIP",
                intended_notional=intended,
                allocated_notional=0.0,
                rank_score=rank,
                reason=skip_reason if skip_reason != ReasonCode.OK else ReasonCode.CORRELATED_EXPOSURE,
                detail=skip_detail or "no_room",
                groups=unique_groups,
                assumptions=unique_assumptions,
                hits=unique_hits,
            )

        min_keep = intended * self.config.min_allocate_fraction
        if room + 1e-12 < min_keep:
            return AllocationDecision(
                market_id=item.market_id,
                action="SKIP",
                intended_notional=intended,
                allocated_notional=0.0,
                rank_score=rank,
                reason=skip_reason if skip_reason != ReasonCode.OK else ReasonCode.CORRELATED_EXPOSURE,
                detail=skip_detail or "below_min_allocate_fraction",
                groups=unique_groups,
                assumptions=unique_assumptions,
                hits=unique_hits,
            )

        allocated = min(intended, room)
        if allocated + 1e-9 < intended:
            return AllocationDecision(
                market_id=item.market_id,
                action="DOWNSIZE",
                intended_notional=intended,
                allocated_notional=allocated,
                rank_score=rank,
                reason=ReasonCode.PORTFOLIO_DOWNSIZED,
                detail=skip_detail or "partial_room",
                groups=unique_groups,
                assumptions=unique_assumptions,
                hits=unique_hits,
            )
        return AllocationDecision(
            market_id=item.market_id,
            action="TAKE",
            intended_notional=intended,
            allocated_notional=allocated,
            rank_score=rank,
            reason=ReasonCode.OK,
            groups=unique_groups,
            assumptions=unique_assumptions,
            hits=unique_hits,
        )
