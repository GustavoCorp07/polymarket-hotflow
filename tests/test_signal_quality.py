"""Parte 46 signal JSON + Parte 47 skip tagging. PAPER only; no new vetoes."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hotflow.analytics.signal_quality import (
    PARTE46_REQUIRED_KEYS,
    impact_exhausted,
    signal_quality,
    spread_regime_label,
    tag_skip_reasons,
)
from hotflow.analytics.skip_audit import rollup_skip_audit
from hotflow.cli import app
from hotflow.config import HotMarketConfig, OpportunityConfig, load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.features.microstructure import microstructure_features
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.storage.sqlite_store import SqliteStore
from hotflow.types import BookLevel, EdgeBreakdown, OrderBook, Side


def _edge(**overrides: float) -> EdgeBreakdown:
    base = dict(
        p_fair=0.62,
        market_price=0.55,
        raw_edge=0.07,
        fee_per_share=0.01,
        spread_cost=0.01,
        slippage=0.0,
        latency_haircut=0.0,
        adverse_selection=0.0,
        net_expected_edge=0.05,
        confidence=0.6,
    )
    base.update(overrides)
    return EdgeBreakdown(**base)


def _opp(market=None):
    market = market or demo_market(hot=True)
    hms = score_hot_market(market, HotMarketConfig())
    return score_opportunity(
        market=market,
        hms=hms,
        edge=_edge(),
        side=Side.BUY,
        token_id="t",
        shares=5,
        cfg=OpportunityConfig(),
    )


def test_parte46_required_keys_and_honest_nulls() -> None:
    payload = signal_quality(
        None,
        decision="SKIP",
        reason_codes=[ReasonCode.UNKNOWN_RESOLUTION],
        strategy="crypto_updown",
        market_id="m-1",
    )
    for key in PARTE46_REQUIRED_KEYS:
        assert key in payload
    assert payload["market"] == "m-1"
    assert payload["decision"] == "SKIP"
    assert payload["fair_probability"] is None
    assert payload["execution_price"] is None
    assert payload["gross_edge"] is None
    assert payload["net_edge"] is None
    assert "microstructure" not in payload
    assert "style" not in payload


def test_signal_quality_from_opportunity_keeps_costs() -> None:
    payload = signal_quality(
        _opp(),
        decision="TRADE",
        reason_codes=[ReasonCode.OK],
        strategy="crypto_updown",
        extras={"microstructure": microstructure_features(demo_market(hot=True))},
    )
    assert payload["fair_probability"] == 0.62
    assert payload["execution_price"] == 0.55
    assert payload["expected_fee"] == 0.01
    assert payload["latency_penalty"] == 0.0
    assert payload["decision"] == "TRADE"
    assert payload["microstructure"]["invented"] is False
    assert payload["spread_regime"] == "normal"


def test_tag_skip_reasons_wide_and_exhausted_book() -> None:
    wide = demo_market(hot=False)
    feats = microstructure_features(wide)
    extras = {"microstructure": feats}
    assert spread_regime_label(extras) == "wide"
    assert impact_exhausted(extras) is True
    codes = tag_skip_reasons(ReasonCode.MARKET_NOT_HOT, extras)
    assert codes[0] == ReasonCode.MARKET_NOT_HOT
    assert ReasonCode.SPREAD_TOO_LARGE in codes
    assert ReasonCode.IMPACT_EXHAUSTED in codes
    trade_codes = tag_skip_reasons(ReasonCode.OK, extras, accepted=True)
    assert trade_codes == [ReasonCode.OK]


def test_pipeline_persists_signal_on_trade_and_skip(tmp_path: Path) -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.microstructure.max_impact is None
    assert cfg.microstructure.min_top_depth == 0.0
    store = SqliteStore(tmp_path / "signals.sqlite")
    pipe = PaperPipeline(cfg, store)

    traded = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert traded["accepted"] is True
    trade_signal = traded["signal"]
    for key in PARTE46_REQUIRED_KEYS:
        assert key in trade_signal
    assert trade_signal["decision"] == "TRADE"
    assert trade_signal["fair_probability"] is not None
    assert ReasonCode.OK in trade_signal["reason_codes"]

    skipped = pipe.evaluate_market(demo_market(hot=False), p_info=0.70)
    assert skipped["accepted"] is False
    assert skipped["reason"] == ReasonCode.MARKET_NOT_HOT
    skip_signal = skipped["signal"]
    assert skip_signal["decision"] == "SKIP"
    assert ReasonCode.MARKET_NOT_HOT in skip_signal["reason_codes"]
    assert ReasonCode.SPREAD_TOO_LARGE in skip_signal["reason_codes"]
    assert ReasonCode.IMPACT_EXHAUSTED in skip_signal["reason_codes"]
    assert skip_signal["spread_regime"] == "wide"
    assert skip_signal["impact_exhausted"] is True
    assert skip_signal["microstructure"]["exhausted_buy"] is True

    rows = store.list_signals()
    assert len(rows) >= 2
    persisted_skip = next(row for row in rows if row["reason"] == ReasonCode.MARKET_NOT_HOT)
    assert persisted_skip["accepted"] == 0
    stored = persisted_skip["extra"]["signal"]
    assert stored["decision"] == "SKIP"
    assert ReasonCode.IMPACT_EXHAUSTED in stored["reason_codes"]


def test_rejected_opportunity_stores_edge(tmp_path: Path) -> None:
    cfg = load_config(Path("configs/default.yaml"))
    store = SqliteStore(tmp_path / "edge-skip.sqlite")
    pipe = PaperPipeline(cfg, store)
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.42)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.EDGE_TOO_SMALL
    audit = pipe.audits[-1]
    assert audit.accepted is False
    assert "edge" in audit.extra
    signal = audit.extra["signal"]
    assert signal["decision"] == "SKIP"
    assert signal["net_edge"] is not None
    assert ReasonCode.EDGE_TOO_SMALL in signal["reason_codes"]


def test_spread_too_large_skip_keeps_regime_slice() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.max_spread = 0.01
    pipe = PaperPipeline(cfg)
    market = demo_market(hot=True)
    result = pipe.evaluate_market(market, p_info=0.70)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.SPREAD_TOO_LARGE
    signal = result["signal"]
    assert signal["spread_regime"] in {"normal", "wide", "tight"}
    assert ReasonCode.SPREAD_TOO_LARGE in signal["reason_codes"]
    assert "opportunity" in pipe.audits[-1].extra


def test_thin_book_fixture_tags_exhaustion() -> None:
    market = demo_market(hot=True)
    market.market_id = "thin-l2"
    market.book = OrderBook(
        token_id="demo-yes",
        bids=[BookLevel(price=0.40, size=1.0)],
        asks=[BookLevel(price=0.42, size=1.0)],
        tick_size=0.01,
    )
    extras = {"microstructure": microstructure_features(market)}
    codes = tag_skip_reasons(ReasonCode.LOW_LIQUIDITY, extras)
    assert ReasonCode.LOW_LIQUIDITY in codes
    assert ReasonCode.IMPACT_EXHAUSTED in codes
    payload = signal_quality(
        None,
        decision="SKIP",
        reason_codes=codes,
        strategy="crypto_updown",
        extras=extras,
        market_id=market.market_id,
    )
    assert payload["impact_exhausted"] is True
    blob = json.dumps(payload)
    assert "bids" not in blob


def test_skip_audit_rollup_buckets_reason_and_regime() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg)
    pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    pipe.evaluate_market(demo_market(hot=False), p_info=0.70)
    rows = [
        {
            "accepted": row.accepted,
            "reason": row.reason,
            "extra": row.extra,
        }
        for row in pipe.audits
    ]
    report = rollup_skip_audit(rows, source="memory")
    assert report["production_changed"] is False
    assert report["live"] is False
    assert report["risk_consume"]["max_impact_enabled"] is False
    assert report["skipped"] >= 1
    assert report["by_reason"].get(ReasonCode.MARKET_NOT_HOT, 0) >= 1
    assert any(key.startswith(f"{ReasonCode.MARKET_NOT_HOT}|") for key in report["by_reason_spread_regime"])
    assert report["impact_exhausted_skips"] >= 1


def test_cli_skip_audit_and_live_gates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HOTFLOW_ACCEPT_LIVE", raising=False)
    yaml_path = tmp_path / "cfg.yaml"
    yaml_path.write_text(
        Path("configs/default.yaml")
        .read_text(encoding="utf-8")
        .replace("sqlite_path: data/hotflow.sqlite", f"sqlite_path: {tmp_path / 'hf.sqlite'}")
        .replace("reports_dir: reports", f"reports_dir: {tmp_path / 'reports'}"),
        encoding="utf-8",
    )
    cfg = load_config(yaml_path)
    store = SqliteStore(cfg.storage.sqlite_path)
    pipe = PaperPipeline(cfg, store)
    pipe.evaluate_market(demo_market(hot=False), p_info=0.70)

    runner = CliRunner()
    gates = runner.invoke(app, ["live-gates", "--config", str(yaml_path)])
    assert gates.exit_code == 0, gates.output
    assert "freeze_ok=True" in gates.output
    assert live_gates_open(cfg) is False

    out = tmp_path / "skip-audit.json"
    audit = runner.invoke(app, ["skip-audit", "--config", str(yaml_path), "--out", str(out)])
    assert audit.exit_code == 0, audit.output
    assert "production_changed=False" in audit.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["skipped"] >= 1
    assert body["production_changed"] is False
