"""Mixed PAPER soak: 5m/15m crypto + news + uncorrelated names."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from hotflow.cli import app
from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.portfolio.correlation import extract_identity
from hotflow.portfolio.mixed_soak import (
    BTC_5M,
    BTC_15M,
    CROSS_WINDOW_NOTE,
    ETH_5M,
    ETH_15M,
    ORIGIN,
    SPORTS_ID,
    WEATHER_ID,
    mixed_soak_markets,
    run_mixed_paper_soak,
    summarize_results,
)
from hotflow.portfolio.session import PaperSession
from hotflow.reason_codes import ReasonCode


def _paper_session() -> PaperSession:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.trading.mode = "paper"
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    return PaperSession(cfg, use_twap_fixtures=True)


def test_mixed_book_has_5m_15m_and_uncorrelated() -> None:
    now = datetime(2026, 9, 7, 21, 0, tzinfo=UTC)
    markets = mixed_soak_markets(now=now)
    ids = [item.market_id for item in markets]
    assert ids[:4] == [BTC_5M, ETH_5M, BTC_15M, ETH_15M]
    assert WEATHER_ID in ids
    assert SPORTS_ID in ids
    windows = {item.market_id: extract_identity(item).window for item in markets}
    assert windows[BTC_5M] == "5m"
    assert windows[ETH_5M] == "5m"
    assert windows[BTC_15M] == "15m"
    assert windows[ETH_15M] == "15m"
    assert extract_identity(markets[0]).underlying == "btc/usd"
    assert extract_identity(markets[1]).underlying == "eth/usd"


def test_baseline_cycle_skips_correlated_crypto_and_takes_uncorrelated() -> None:
    session = _paper_session()
    now = datetime.now(UTC)
    markets = mixed_soak_markets(now=now)
    summary = session.run_markets(markets, p_info=0.70, now=now)
    by_id = {row["market_id"]: row for row in summary["results"]}
    crypto = [by_id[mid] for mid in (BTC_5M, ETH_5M, BTC_15M, ETH_15M)]
    taken_crypto = [row for row in crypto if row.get("accepted")]
    skipped_crypto = [row for row in crypto if not row.get("accepted")]
    assert len(taken_crypto) == 1
    assert len(skipped_crypto) == 3
    assert all(row["reason"] == ReasonCode.CORRELATED_EXPOSURE for row in skipped_crypto)
    assert by_id[WEATHER_ID]["accepted"] is True
    assert by_id[SPORTS_ID]["accepted"] is True
    windows = {row["market_id"]: (row.get("exposure_identity") or {}).get("window") for row in crypto}
    assert set(windows.values()) == {"5m", "15m"}


def test_news_shock_attaches_and_scales_crypto_group() -> None:
    session = _paper_session()
    meta = run_mixed_paper_soak(session, cycles=2)
    news_cycle = next(item for item in meta["cycle_audits"] if item["recipe"] == "news_shock")
    assert news_cycle["overlay_labeled"].get("news_shock", 0) >= 1
    assert news_cycle["overlay_applied"].get("news_shock", 0) >= 1
    shocked = [row for row in news_cycle["rows"] if row.get("news_apply") and row.get("regime") == "news_shock"]
    assert shocked
    assert any(row["reason"] == ReasonCode.CORRELATED_EXPOSURE for row in news_cycle["rows"])
    weather = next(row for row in news_cycle["rows"] if row["market_id"] == WEATHER_ID)
    assert "news_shock" not in (weather.get("overlay_applied") or [])


def test_near_resolution_labels_weather_and_crypto() -> None:
    session = _paper_session()
    meta = run_mixed_paper_soak(session, cycles=3)
    near = next(item for item in meta["cycle_audits"] if item["recipe"] == "near_resolution")
    assert near["overlay_labeled"].get("near_resolution", 0) >= 1
    weather = next(row for row in near["rows"] if row["market_id"] == WEATHER_ID)
    assert weather["regime"] == "near_resolution"
    assert "near_resolution" in (weather.get("overlay_applied") or [])
    crypto_near = [row for row in near["rows"] if row["market_id"] in {BTC_5M, ETH_5M, BTC_15M, ETH_15M}]
    assert any(row.get("regime") == "near_resolution" for row in crypto_near)
    # Crypto near_resolution must not scale weather_city (group-scoped overlays).
    crypto_assumptions_leak = any(
        "weather_city" in str(row.get("hits")) and "news_shock" in (row.get("overlay_applied") or [])
        for row in crypto_near
    )
    assert crypto_assumptions_leak is False


def test_partial_room_can_downsize_and_carry_skips_open_crypto() -> None:
    session = _paper_session()
    meta = run_mixed_paper_soak(session, cycles=5)
    recipes = meta["recipes"]
    assert recipes == ["baseline", "news_shock", "near_resolution", "partial_room", "carry"]
    partial = next(item for item in meta["cycle_audits"] if item["recipe"] == "partial_room")
    actions = partial["portfolio_actions"]
    assert actions.get("DOWNSIZE", 0) >= 1 or actions.get("TAKE", 0) >= 2
    if actions.get("DOWNSIZE", 0) == 0:
        # Default fill/intended can still SKIP the second name; reason must be portfolio.
        assert partial["reasons"].get(ReasonCode.CORRELATED_EXPOSURE, 0) >= 1
    carry = next(item for item in meta["cycle_audits"] if item["recipe"] == "carry")
    crypto_carry = [row for row in carry["rows"] if row["market_id"] in {BTC_5M, ETH_5M, BTC_15M, ETH_15M}]
    assert all(row["accepted"] is False for row in crypto_carry)
    assert any(row["reason"] == ReasonCode.CORRELATED_EXPOSURE for row in crypto_carry)
    totals = meta["totals"]
    assert totals["correlated_exposure"] >= 6
    assert totals["regime_overlay_events"] >= 1
    assert totals["accepted"] >= 4
    assert meta["origin"] == ORIGIN
    assert meta["live"] is False
    assert CROSS_WINDOW_NOTE in meta["cross_window_note"]


def test_summarize_tracks_reason_codes() -> None:
    audit = summarize_results(
        [
            {
                "market_id": "a",
                "accepted": False,
                "reason": ReasonCode.CORRELATED_EXPOSURE,
                "portfolio": {"action": "SKIP", "hits": ["yaml_group:crypto_short_window"], "assumptions": []},
                "regime": {"primary": "normal", "labels": ["normal"]},
            },
            {
                "market_id": "b",
                "accepted": True,
                "reason": ReasonCode.OK,
                "portfolio": {
                    "action": "DOWNSIZE",
                    "allocated_notional": 80,
                    "assumptions": ["Regime news_shock: tighten scale=0.5."],
                },
                "regime": {"primary": "news_shock", "labels": ["news_shock"]},
                "news": {"apply": True},
            },
        ],
        recipe="unit",
    )
    assert audit["reasons"][ReasonCode.CORRELATED_EXPOSURE] == 1
    assert audit["portfolio_actions"]["DOWNSIZE"] == 1
    assert audit["overlay_applied"]["news_shock"] == 1


def test_cli_mixed_soak_and_refuses_live(tmp_path, monkeypatch) -> None:
    out = tmp_path / "paper-soak-mixed.json"
    result = CliRunner().invoke(app, ["paper-soak", "--mixed", "--cycles", "5", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "paper-soak mixed" in result.output
    assert "live=false" in result.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["origin"] == ORIGIN
    assert body["mixed_soak"] is True
    assert body["auto_disable"] is False
    assert body["totals"]["correlated_exposure"] >= 1
    assert "news_shock" in body["recipes"]
    assert live_gates_open(load_config(Path("configs/default.yaml"))) is False
    monkeypatch.setenv("HOTFLOW_TRADING_MODE", "live")
    blocked = CliRunner().invoke(app, ["paper-soak", "--mixed", "--out", str(tmp_path / "x.json")])
    assert blocked.exit_code != 0


def test_mixed_cannot_combine_with_long() -> None:
    result = CliRunner().invoke(app, ["paper-soak", "--mixed", "--long"])
    assert result.exit_code != 0
