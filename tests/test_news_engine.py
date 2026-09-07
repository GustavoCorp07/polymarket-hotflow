"""News engine: classify / validate / impact features. Never BUY/SELL."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from hotflow.cli import app
from hotflow.config import HotflowConfig
from hotflow.news.cold import classify_news_cold
from hotflow.news.engine import NewsEngine, classify, fingerprint, relevance
from hotflow.news.fixtures import labeled_news_items, public_fetch_status
from hotflow.news.item import NewsClass, NewsItem
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import BookLevel, KillSwitchReason


def _item(news_id: str) -> NewsItem:
    return next(item for item in labeled_news_items() if item.news_id == news_id)


def _repriced_market():
    market = demo_market(hot=True)
    market.market_id = "demo-btc-repriced"
    assert market.book is not None
    market.book.asks = [BookLevel(price=0.71, size=80.0)]
    market.book.bids = [BookLevel(price=0.69, size=90.0)]
    market.best_ask = 0.71
    market.best_bid = 0.69
    return market


def test_classification_official_vs_rumor() -> None:
    assert classify(_item("btc-sec-filing")) == NewsClass.OFFICIAL
    assert classify(_item("anon-btc-rumor")) == NewsClass.RUMOR
    unlabeled = NewsItem(
        news_id="wire",
        headline="BTC up/down wire note",
        source_id="reuters",
        published_at=datetime(2026, 9, 7, tzinfo=UTC),
        resolution_terms=["btc"],
    )
    assert classify(unlabeled) == NewsClass.WIRE


def test_duplicate_detection() -> None:
    engine = NewsEngine()
    market = demo_market(hot=True)
    first = engine.evaluate_item(_item("btc-sec-filing"), market, p_base=0.55)
    second = engine.evaluate_item(_item("btc-sec-filing-dup"), market, p_base=0.55)
    assert first.apply is True
    assert fingerprint(_item("btc-sec-filing")) == fingerprint(_item("btc-sec-filing-dup"))
    assert second.apply is False
    assert second.reason == ReasonCode.NEWS_DUPLICATE
    assert second.duplicate is True


def test_already_repriced_skip() -> None:
    engine = NewsEngine()
    impact = engine.evaluate_item(_item("btc-already-repriced"), _repriced_market(), p_base=0.42)
    assert impact.apply is False
    assert impact.reason == ReasonCode.NEWS_ALREADY_REPRICED
    assert impact.already_repriced is True


def test_irrelevant_resolution_skip() -> None:
    engine = NewsEngine()
    market = demo_market(hot=True)
    item = _item("chicago-heat-on-btc")
    assert relevance(item, market) < 0.4
    impact = engine.evaluate_item(item, market, p_base=0.55)
    assert impact.apply is False
    assert impact.reason == ReasonCode.NEWS_IRRELEVANT_RESOLUTION


def test_unvalidated_and_low_confidence() -> None:
    engine = NewsEngine()
    market = demo_market(hot=True)
    bad = engine.evaluate_item(_item("anon-btc-rumor"), market, p_base=0.55)
    assert bad.apply is False
    assert bad.reason == ReasonCode.NEWS_UNVALIDATED
    aged = engine.evaluate_item(_item("old-commentary"), market, p_base=0.55)
    assert aged.apply is False
    assert aged.reason == ReasonCode.NEWS_LOW_CONFIDENCE


def test_news_never_bypasses_min_edge() -> None:
    cfg = HotflowConfig()
    cfg.trading.min_required_edge = 0.99
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    engine = NewsEngine(cfg.news)
    engine.ingest(_item("btc-large-labeled-shift"))
    pipe = PaperPipeline(cfg, news_engine=engine)
    market = demo_market(hot=True)
    market.market_id = "demo-btc-news-edge"
    result = pipe.evaluate_market(market, p_info=0.55)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.EDGE_TOO_SMALL
    assert result["news"]["apply"] is True
    assert result["news"]["p_info_adjusted"] is not None


def test_news_never_bypasses_risk_kill() -> None:
    cfg = HotflowConfig()
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    engine = NewsEngine(cfg.news)
    engine.ingest(_item("btc-sec-filing"))
    pipe = PaperPipeline(cfg, news_engine=engine)
    pipe.kills.trip(KillSwitchReason.MANUAL, "fixture")
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.55)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.KILL_SWITCH
    assert result["news"]["apply"] is True


def test_validated_news_adjusts_p_info_then_fv() -> None:
    cfg = HotflowConfig()
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    with_news = NewsEngine(cfg.news)
    with_news.ingest(_item("btc-sec-filing"))
    pipe_news = PaperPipeline(cfg, news_engine=with_news)
    pipe_plain = PaperPipeline(HotflowConfig())
    market = demo_market(hot=True)
    news_row = pipe_news.evaluate_market(market, p_info=0.55)
    plain = pipe_plain.evaluate_market(demo_market(hot=True), p_info=0.55)
    assert news_row["news"]["apply"] is True
    assert news_row["news"]["p_info_adjusted"] == news_row["news"]["p_base"] + news_row["news"]["p_shift"]
    news_edge = news_row.get("edge") or {}
    plain_edge = plain.get("edge") or {}
    if news_edge and plain_edge:
        assert news_edge["p_fair"] != plain_edge["p_fair"]


def test_hot_path_does_not_import_kimi() -> None:
    roots = [Path("src/hotflow/pipeline.py"), Path("src/hotflow/news/engine.py"), Path("src/hotflow/news/item.py")]
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not any(mod and ("ai_research" in mod or "news.cold" in mod) for mod in modules)


def test_cold_path_kimi_stub_is_mockable() -> None:
    captured: dict = {}

    def transport(payload: dict) -> dict:
        captured.update(payload)
        return {"mock": True, "content": "official"}

    from hotflow.ai_research.kimi_client import KimiClient

    out = classify_news_cold(_item("btc-sec-filing"), KimiClient(transport=transport, api_key=None))
    assert out["content"] == "official"
    assert captured["messages"][0]["role"] == "system"
    assert "Cold-path only" in captured["messages"][0]["content"]


def test_public_fetch_default_off() -> None:
    off = public_fetch_status(enabled=False)
    assert off["fetched"] is False
    assert off["label"] == "public_fetch_default_off"
    on = public_fetch_status(enabled=True)
    assert on["fetched"] is False
    assert on["label"] == "news_scrape_not_implemented"


def test_cli_news_fixtures(tmp_path) -> None:
    out = tmp_path / "news.json"
    result = CliRunner().invoke(app, ["news-fixtures", "--shadow", "--out", str(out)])
    assert result.exit_code == 0, result.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["news_to_order"] is False
    assert body["public_fetch"]["fetched"] is False
    reasons = {row["news_id"]: row["impact"]["reason"] for row in body["rows"]}
    assert reasons["btc-sec-filing-dup"] == "NEWS_DUPLICATE"
    assert reasons["btc-already-repriced"] == "NEWS_ALREADY_REPRICED"
    assert reasons["chicago-heat-on-btc"] == "NEWS_IRRELEVANT_RESOLUTION"
    assert reasons["anon-btc-rumor"] == "NEWS_UNVALIDATED"
    assert body["shadow_evaluate"]["sent"] is False
    blob = out.read_text(encoding="utf-8")
    assert "MOONSHOT_API_KEY" not in blob
    assert "BEGIN PRIVATE KEY" not in blob


def test_cli_refuses_live(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOTFLOW_TRADING_MODE", "live")
    result = CliRunner().invoke(app, ["news-fixtures", "--out", str(tmp_path / "x.json")])
    assert result.exit_code != 0
