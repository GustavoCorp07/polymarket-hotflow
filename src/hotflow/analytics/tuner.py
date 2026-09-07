"""Offline auto-tuner. Suggests bounded changes. Never writes production.

Flow: hypothesis → backtest → OOS / walk-forward stub → suggestion only.
Never promote to LIVE. Never select by max absolute PnL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hotflow.analytics.experiments import git_commit
from hotflow.reason_codes import ReasonCode

TUNER_BOUNDS: dict[str, tuple[float, float]] = {
    "trading.min_required_edge": (0.006, 0.040),
    "hot_market.min_score_to_trade": (40.0, 80.0),
    "risk.max_spread": (0.050, 0.150),
    "fair_value.latency_haircut": (0.0005, 0.0040),
    "scanner.max_spread": (0.060, 0.200),
}

ALLOWED_OBJECTIVES = frozenset({"expectancy", "max_drawdown", "skip_rate", "stability"})


def _refuse_abs_pnl(objective: str) -> dict[str, Any] | None:
    """Local copy so analytics does not import the backtest package (cycle)."""
    key = objective.strip().lower().replace("-", "_")
    if key in {"abs_pnl", "pnl", "absolute_pnl", "max_pnl", "best_pnl"}:
        return {"refused": True, "reason": ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED}
    return None


@dataclass
class TuneProposal:
    name: str
    suggested: dict[str, float]
    applied: bool = False


@dataclass
class TuneReport:
    applied: bool = False
    production_write: bool = False
    refused: bool = False
    reason: str | None = None
    objective: str = "expectancy"
    hypothesis: str = ""
    suggested: dict[str, float] = field(default_factory=dict)
    bounds: dict[str, dict[str, float]] = field(default_factory=dict)
    metrics_used: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    flow: str = "hypothesis → backtest → oos/walk-forward stub → suggestion only"
    selection_rule: str = "refuses_max_abs_pnl"
    git_commit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "production_write": self.production_write,
            "refused": self.refused,
            "reason": self.reason,
            "objective": self.objective,
            "hypothesis": self.hypothesis,
            "suggested": self.suggested,
            "bounds": self.bounds,
            "metrics_used": self.metrics_used,
            "notes": self.notes,
            "flow": self.flow,
            "selection_rule": self.selection_rule,
            "git_commit": self.git_commit,
        }


class AutoTunerStub:
    def propose(self, metric_name: str, history: list[float]) -> TuneProposal:
        if not history:
            return TuneProposal(name=metric_name, suggested={})
        mean = sum(history) / len(history)
        return TuneProposal(name=metric_name, suggested={"mean_observed": mean}, applied=False)

    def apply(self, proposal: TuneProposal) -> TuneProposal:
        proposal.applied = False
        return proposal


def clip_bound(path: str, value: float) -> float:
    lo, hi = TUNER_BOUNDS[path]
    return max(lo, min(hi, value))


def suggestion_path_allowed(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    parts = {item.lower() for item in resolved.parts}
    if "configs" in parts or resolved.name in {".env", "default.yaml"}:
        return False
    if resolved.suffix in {".env", ".pem"}:
        return False
    return "reports" in parts


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _metrics_from_report(report: dict[str, Any]) -> dict[str, Any]:
    raw = report.get("metrics")
    return raw if isinstance(raw, dict) else {}


class OfflineTuner:
    """Bounded suggestions from backtest reports. applied is always False."""

    def propose_from_reports(
        self,
        reports: list[dict[str, Any]],
        *,
        objective: str = "expectancy",
        hypothesis: str = "",
        current: dict[str, float] | None = None,
    ) -> TuneReport:
        blocked = _refuse_abs_pnl(objective)
        bounds = {key: {"lo": lo, "hi": hi} for key, (lo, hi) in TUNER_BOUNDS.items()}
        base = TuneReport(
            applied=False,
            production_write=False,
            objective=objective,
            hypothesis=hypothesis,
            bounds=bounds,
            git_commit=git_commit(),
        )
        if blocked:
            base.refused = True
            base.reason = ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
            base.notes.append("refused abs-PnL objective")
            return base
        if objective not in ALLOWED_OBJECTIVES:
            base.refused = True
            base.reason = ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
            base.notes.append(f"objective {objective!r} is not allowed")
            return base

        metrics_rows = [_metrics_from_report(item) for item in reports]
        expectancy = _mean([float(row.get("expectancy") or 0.0) for row in metrics_rows])
        drawdown = _mean([float(row.get("max_drawdown") or 0.0) for row in metrics_rows])
        trades = sum(int(row.get("trade_count") or 0) for row in metrics_rows)
        skip_counts: dict[str, int] = {}
        for row in metrics_rows:
            raw = row.get("skip_counts")
            if isinstance(raw, dict):
                for key, value in raw.items():
                    skip_counts[str(key)] = skip_counts.get(str(key), 0) + int(value or 0)
        splits_ok = any(isinstance(item.get("splits"), dict) for item in reports)
        walk_ok = any(
            isinstance(item.get("walk_forward"), dict) for item in reports
        )
        current_vals = current or {
            "trading.min_required_edge": 0.012,
            "hot_market.min_score_to_trade": 55.0,
            "risk.max_spread": 0.10,
            "fair_value.latency_haircut": 0.0015,
            "scanner.max_spread": 0.12,
        }
        suggested: dict[str, float] = {}
        notes: list[str] = []
        if drawdown >= 0.08:
            path = "trading.min_required_edge"
            suggested[path] = clip_bound(path, current_vals[path] + 0.004)
            notes.append("high_drawdown_raise_min_edge")
        if skip_counts.get("MARKET_NOT_HOT", 0) >= 2:
            path = "hot_market.min_score_to_trade"
            suggested[path] = clip_bound(path, current_vals[path] - 5.0)
            notes.append("many_not_hot_lower_hms_gate")
        if skip_counts.get("EDGE_TOO_SMALL", 0) >= 2 and expectancy <= 0:
            path = "trading.min_required_edge"
            suggested[path] = clip_bound(path, current_vals[path] - 0.002)
            notes.append("low_expectancy_many_edge_skips")
        if skip_counts.get("SPREAD_TOO_LARGE", 0) >= 1:
            path = "risk.max_spread"
            suggested[path] = clip_bound(path, current_vals[path] + 0.01)
            notes.append("spread_skips_widen_risk_cap")
        if not suggested:
            notes.append("no_bounded_change")
        if not splits_ok:
            notes.append("split_metrics_missing")
        if not walk_ok:
            notes.append("walk_forward_stub_missing")

        base.suggested = suggested
        base.notes = notes
        base.metrics_used = {
            "expectancy": expectancy,
            "max_drawdown": drawdown,
            "trade_count": trades,
            "skip_counts": skip_counts,
            "abs_pnl_ignored": True,
        }
        return base

    def apply(self, report: TuneReport) -> TuneReport:
        report.applied = False
        report.production_write = False
        return report


def write_suggestion(path: Path, report: TuneReport) -> Path:
    if not suggestion_path_allowed(path):
        raise ValueError(ReasonCode.TUNER_PRODUCTION_WRITE_REFUSED)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.as_dict()
    payload["applied"] = False
    payload["production_write"] = False
    if path.suffix in {".yaml", ".yml"}:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    else:
        import json

        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
