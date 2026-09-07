"""Collect readiness inputs by running lightweight soaks or loading reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hotflow.config import HotflowConfig
from hotflow.execution.live_gate import inspect_live_gates
from hotflow.failure.soak import run_failure_soak
from hotflow.readiness.rollup import latest_report, load_json


def collect_from_reports(directory: Path) -> dict[str, Any]:
    paper_path = latest_report(directory, ("paper-soak", "paper-run"))
    shadow_path = latest_report(directory, ("shadow-soak", "shadow-"))
    failure_path = latest_report(directory, ("failure-soak",))
    live_path = latest_report(directory, ("live-gates",))
    return {
        "paper": load_json(paper_path),
        "shadow": load_json(shadow_path),
        "failure": load_json(failure_path),
        "live_gates": load_json(live_path),
        "sources": {
            "paper": str(paper_path) if paper_path else None,
            "shadow": str(shadow_path) if shadow_path else None,
            "failure": str(failure_path) if failure_path else None,
            "live_gates": str(live_path) if live_path else None,
        },
    }


def collect_live(config: HotflowConfig) -> dict[str, Any]:
    return inspect_live_gates(config).as_dict()


def collect_paper_lightweight(config: HotflowConfig) -> dict[str, Any]:
    from hotflow.portfolio.session import PaperSession, mock_markets

    cfg = config.model_copy(deep=True)
    cfg.trading.mode = "paper"
    cfg.trading.shadow = False
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    session = PaperSession(cfg, use_twap_fixtures=True)
    session.run_markets(mock_markets())
    session.flatten()
    return session.report()


def collect_shadow_lightweight(config: HotflowConfig) -> dict[str, Any]:
    from hotflow.backtest.shadow import ShadowSession, run_stale_probe
    from hotflow.portfolio.session import mock_markets

    cfg = config.model_copy(deep=True)
    cfg.trading.mode = "shadow"
    cfg.trading.shadow = True
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    session = ShadowSession(cfg, use_twap_fixtures=True)
    session.run_cycle(mock_markets())
    run_stale_probe(session)
    return session.report()


def collect_by_running(config: HotflowConfig) -> dict[str, Any]:
    return {
        "paper": collect_paper_lightweight(config),
        "shadow": collect_shadow_lightweight(config),
        "failure": run_failure_soak(),
        "live_gates": collect_live(config),
        "sources": {
            "paper": "run:paper-lightweight",
            "shadow": "run:shadow-lightweight",
            "failure": "run:failure-soak",
            "live_gates": "run:live-gates",
        },
    }
