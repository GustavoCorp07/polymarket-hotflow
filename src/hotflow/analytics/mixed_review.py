"""Detected-regime review for mixed PAPER soak JSON.

Primary analysis unit is the evaluate_markets **proposal** (cycle_audits.rows):
that is where Parte 25 detectors attach extras.regime. Closed-fill PnL is a
secondary join (market_id + flatten recipe) and is almost always a tiny sample
on a 5-cycle fixture. This path never treats --long `regime=` notes as detected
labels and never invents rho or significance.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from hotflow.analytics.decay import decay_report
from hotflow.analytics.performance import sample_caveat
from hotflow.analytics.trades import NormalizedTrade, extract_trades
from hotflow.analytics.walkforward import fold_metrics

ORIGIN = "mixed_fixture_book"
NA = "N/A"

ANALYSIS_UNIT = (
    "Primary unit = evaluate_markets proposals (detected extras.regime). "
    "Closed-fill PnL is joined by market_id + flatten recipe when present. "
    "Not the --long synthetic regime= split. Tiny n is descriptive only."
)


def is_mixed_soak(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    if report.get("mixed_soak") is True:
        return True
    return str(report.get("origin") or "") == ORIGIN


@dataclass
class ProposalRow:
    cycle: int
    recipe: str
    market_id: str
    accepted: bool
    reason: str
    portfolio: str | None
    regime: str
    overlay_applied: list[str] = field(default_factory=list)
    overlay_labeled: list[str] = field(default_factory=list)
    allocated_notional: float | None = None


def extract_proposals(report: dict[str, Any] | None) -> list[ProposalRow]:
    if not report:
        return []
    out: list[ProposalRow] = []
    for index, audit in enumerate(report.get("cycle_audits") or []):
        if not isinstance(audit, dict):
            continue
        recipe = str(audit.get("recipe") or f"cycle_{index}")
        for raw in audit.get("rows") or []:
            if not isinstance(raw, dict):
                continue
            market_id = str(raw.get("market_id") or "")
            if not market_id:
                continue
            primary = raw.get("regime")
            regime = str(primary) if primary else NA
            applied = [str(item) for item in (raw.get("overlay_applied") or [])]
            labeled = [str(item) for item in (raw.get("overlay_labeled") or [])]
            allocated = raw.get("allocated_notional")
            out.append(
                ProposalRow(
                    cycle=index,
                    recipe=recipe,
                    market_id=market_id,
                    accepted=bool(raw.get("accepted")),
                    reason=str(raw.get("reason") or "NO_TRADE"),
                    portfolio=str(raw["portfolio"]) if raw.get("portfolio") else None,
                    regime=regime,
                    overlay_applied=applied,
                    overlay_labeled=labeled,
                    allocated_notional=float(allocated) if allocated is not None else None,
                )
            )
    return out


def _proposal_metrics(rows: list[ProposalRow]) -> dict[str, Any]:
    n = len(rows)
    accepted = sum(1 for row in rows if row.accepted)
    return {
        "n_proposals": n,
        "accepted": accepted,
        "skipped": n - accepted,
        "accept_rate": (accepted / n) if n else None,
        "reasons": dict(Counter(row.reason for row in rows)),
        "portfolio_actions": dict(Counter(row.portfolio for row in rows if row.portfolio)),
        "overlay_applied": dict(Counter(item for row in rows for item in row.overlay_applied)),
        "overlay_labeled": dict(Counter(item for row in rows for item in row.overlay_labeled)),
        "sample": sample_caveat(n),
        "realized_pnl": None,
        "pnl_note": "proposals do not carry realized PnL; see close_pnl_by_detected_label",
    }


def detected_regime_split(proposals: list[ProposalRow]) -> dict[str, Any]:
    if not proposals:
        return {
            "status": "N/A",
            "origin": "detected",
            "detail": "no mixed-soak proposals; not invented",
            "regimes": {},
        }
    groups: dict[str, list[ProposalRow]] = {}
    for row in proposals:
        groups.setdefault(row.regime, []).append(row)
    return {
        "status": "detected",
        "origin": "detected",
        "detail": (
            "Labels from cycle_audits extras.regime (Parte 25 detectors). "
            "Not --long synthetic fixture notes."
        ),
        "n_proposals": len(proposals),
        "n_labeled": sum(1 for row in proposals if row.regime != NA),
        "n_unavailable": sum(1 for row in proposals if row.regime == NA),
        "regimes": {name: _proposal_metrics(items) for name, items in sorted(groups.items())},
        "sample": sample_caveat(len(proposals)),
        "strong_conclusion": False,
    }


def allocator_outcome_split(proposals: list[ProposalRow]) -> dict[str, Any]:
    groups: dict[str, list[ProposalRow]] = {}
    for row in proposals:
        key = row.portfolio or row.reason
        groups.setdefault(key, []).append(row)
    return {
        "status": "allocator_outcomes",
        "detail": "TAKE / DOWNSIZE / SKIP (or reason if action missing). Not a PnL ranking.",
        "n_proposals": len(proposals),
        "outcomes": {name: _proposal_metrics(items) for name, items in sorted(groups.items())},
        "sample": sample_caveat(len(proposals)),
    }


def _flatten_recipe(note: str | None) -> str | None:
    text = str(note or "")
    prefix = "mixed_soak_flatten:"
    if prefix in text:
        return text.split(prefix, 1)[1].split()[0] or None
    return None


def join_closes_to_detected(report: dict[str, Any] | None) -> list[NormalizedTrade]:
    """Attach detected labels to existing ledger closes. Does not invent PnL."""
    if not report:
        return []
    proposals = extract_proposals(report)
    by_key: dict[tuple[str, str], str] = {}
    latest: dict[str, str] = {}
    for row in proposals:
        latest[row.market_id] = row.regime
        by_key[(row.recipe, row.market_id)] = row.regime
    extract = extract_trades(report)
    events = [item for item in (report.get("events") or []) if isinstance(item, dict)]
    closes = [item for item in events if item.get("kind") in {"FILL", "FLATTEN"} and item.get("closed")]
    joined: list[NormalizedTrade] = []
    for trade, event in zip(extract.trades, closes, strict=False):
        market_id = str(event.get("market_id") or "")
        recipe = _flatten_recipe(event.get("note") if isinstance(event.get("note"), str) else None)
        regime = by_key.get((recipe or "", market_id)) or latest.get(market_id)
        joined.append(
            NormalizedTrade(
                pnl=trade.pnl,
                fee=trade.fee,
                slippage=trade.slippage,
                style=trade.style,
                ts=trade.ts,
                open_ts=trade.open_ts,
                holding_s=trade.holding_s,
                mae=trade.mae,
                mfe=trade.mfe,
                source="mixed_soak_joined",
                regime=regime or NA,
            )
        )
    return joined


def close_pnl_by_detected_label(closes: list[NormalizedTrade]) -> dict[str, Any]:
    if not closes:
        return {
            "status": "N/A",
            "detail": "no joined closes; not invented",
            "regimes": {},
            "sample": sample_caveat(0),
        }
    groups: dict[str, list[NormalizedTrade]] = {}
    for row in closes:
        groups.setdefault(str(row.regime or NA), []).append(row)
    return {
        "status": "detected_join",
        "detail": "PnL from ledger closes joined to detected proposal labels. Tiny n is not significance.",
        "n_closes": len(closes),
        "regimes": {name: fold_metrics(rows) for name, rows in sorted(groups.items())},
        "sample": sample_caveat(len(closes)),
        "strong_conclusion": False,
    }


def decay_by_detected_label(closes: list[NormalizedTrade]) -> dict[str, Any]:
    groups: dict[str, list[float]] = {}
    for row in closes:
        groups.setdefault(str(row.regime or NA), []).append(row.pnl)
    buckets = {name: decay_report(pnls) for name, pnls in sorted(groups.items())}
    return {
        "status": "detected_join" if buckets else "N/A",
        "auto_disable": False,
        "suggestion_only": True,
        "production_change": False,
        "note": (
            "Per-label decay uses joined close PnL only. Default windows 50/100/500 "
            "will clip on a 5-cycle fixture and stay insufficient_sample."
        ),
        "labels": buckets,
        "sample": sample_caveat(len(closes)),
    }


def build_mixed_detected_review(report: dict[str, Any] | None) -> dict[str, Any]:
    proposals = extract_proposals(report)
    closes = join_closes_to_detected(report)
    return {
        "mixed_soak": True,
        "live": False,
        "auto_disable": False,
        "suggestion_only": True,
        "analysis_unit": ANALYSIS_UNIT,
        "n_proposals": len(proposals),
        "n_closes_joined": len(closes),
        "detected_regime_split": detected_regime_split(proposals),
        "allocator_outcomes": allocator_outcome_split(proposals),
        "close_pnl_by_detected_label": close_pnl_by_detected_label(closes),
        "decay_by_detected_label": decay_by_detected_label(closes),
        "synthetic_regime_unused": True,
        "note": (
            "PAPER fixture analysis. Not live edge. --long walk-forward remains the "
            "≥50-close synthetic-label path."
        ),
    }
