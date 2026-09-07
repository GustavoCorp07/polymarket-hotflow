"""HOTFLOW CLI. Default paper. LIVE is gated."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.marketdata.sports_cache import SportsGameCache
from hotflow.marketdata.sports_fixtures import default_sports_cache_fixtures
from hotflow.marketdata.twap_cache import TwapPrintCache
from hotflow.marketdata.twap_fixtures import default_paper_fixtures
from hotflow.monitoring.observer import Observability, http_enabled
from hotflow.pipeline import (
    PaperPipeline,
    demo_market,
    demo_sports_nba_market,
    demo_twap_market,
    demo_weather_market,
    gamma_esports_demo_markets,
    gamma_weather_demo_markets,
    write_report,
)
from hotflow.storage.sqlite_store import SqliteStore

app = typer.Typer(help="POLYMARKET HOTFLOW — paper-first quant system")


def _store(config) -> SqliteStore:
    return SqliteStore(config.storage.sqlite_path)


def _attach_rtds(cfg, mock: bool, rtds_live: bool) -> bool:
    if mock:
        return False
    return bool(rtds_live or cfg.feeds.rtds.subscriber_enabled)


def _attach_sports(cfg, mock: bool, sports_live: bool) -> bool:
    if mock:
        return False
    return bool(sports_live or cfg.feeds.sports_ws.subscriber_enabled)


def _prepare_mock_config(cfg):
    """--mock evaluates several fixtures in one process tick; skip inter-order cooldown."""
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    return cfg


def _observability(cfg, *, serve: bool) -> Observability:
    obs = Observability.from_config(cfg, announce_restart=True)
    if serve or http_enabled(cfg):
        obs.start_http()
        addr = obs.http_addr
        if addr is not None:
            typer.echo(f"metrics http://{addr[0]}:{addr[1]}/metrics health=/health ready=/ready")
    return obs


@app.command()
def scan(
    config: Path | None = typer.Option(None, "--config", "-c"),
    mock: bool = typer.Option(False, "--mock", help="Use documented fixture if network is blocked"),
    twap_cache: Path | None = typer.Option(None, "--twap-cache", help="Inject official-shape TWAP cache JSON"),
    sports_cache: Path | None = typer.Option(
        None, "--sports-cache", help="Inject official-shape Sports WS cache JSON"
    ),
    rtds_live: bool = typer.Option(
        False, "--rtds-live", help="Attach public RTDS subscriber briefly (PAPER only)"
    ),
    sports_live: bool = typer.Option(
        False, "--sports-live", help="Attach public Sports WS subscriber briefly (PAPER only)"
    ),
    out: Path | None = typer.Option(None, "--out"),
    serve_metrics: bool = typer.Option(False, "--serve-metrics", help="Bind localhost /metrics /health /ready"),
) -> None:
    """Scan Gamma + public CLOB and write a report. Never places live orders."""
    cfg = load_config(config)
    if mock:
        cfg = _prepare_mock_config(cfg)
    store = _store(cfg)
    obs = _observability(cfg, serve=serve_metrics)
    pipe = PaperPipeline(
        cfg,
        store,
        use_twap_fixtures=mock,
        cache_path=twap_cache,
        sports_cache_path=sports_cache,
        obs=obs,
    )

    async def _run() -> dict:
        if mock:
            markets = [
                demo_twap_market(hot=True),
                demo_weather_market(hot=True),
                demo_sports_nba_market(hot=True),
                *gamma_weather_demo_markets(hot=True),
                *gamma_esports_demo_markets(hot=True),
                demo_market(hot=False),
            ]
            markets[-1].market_id = "demo-cold"
            return await pipe.run_scan(
                markets=markets,
                use_network=False,
                attach_subscriber=_attach_rtds(cfg, mock, rtds_live),
                attach_sports_subscriber=_attach_sports(cfg, mock, sports_live),
            )
        return await pipe.run_scan(
            use_network=True,
            attach_subscriber=_attach_rtds(cfg, mock, rtds_live),
            attach_sports_subscriber=_attach_sports(cfg, mock, sports_live),
        )

    payload = asyncio.run(_run())
    target = out or Path(cfg.storage.reports_dir) / f"scan-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_report(target, payload)
    typer.echo(f"mode={cfg.trading.mode} markets={payload.get('markets')} report={target}")


@app.command("paper-run")
def paper_run(
    config: Path | None = typer.Option(None, "--config", "-c"),
    cycles: int = typer.Option(1, "--cycles"),
    mock: bool = typer.Option(False, "--mock", help="Documented fixture when network is blocked"),
    twap_cache: Path | None = typer.Option(None, "--twap-cache", help="Inject official-shape TWAP cache JSON"),
    sports_cache: Path | None = typer.Option(
        None, "--sports-cache", help="Inject official-shape Sports WS cache JSON"
    ),
    rtds_live: bool = typer.Option(
        False, "--rtds-live", help="Attach public RTDS subscriber briefly (PAPER only)"
    ),
    sports_live: bool = typer.Option(
        False, "--sports-live", help="Attach public Sports WS subscriber briefly (PAPER only)"
    ),
    out: Path | None = typer.Option(None, "--out"),
    serve_metrics: bool = typer.Option(False, "--serve-metrics", help="Bind localhost /metrics /health /ready"),
    flatten: bool = typer.Option(
        False, "--flatten", help="Close paper positions at last observed mids (explicit marks only)"
    ),
    kill_drill: bool = typer.Option(False, "--kill-drill", help="Paper kill-switch trip + recovery drill"),
    acknowledge: str = typer.Option("", "--acknowledge", help="Required text to clear a tripped kill switch"),
    news_fixtures: bool = typer.Option(
        False, "--news-fixtures", help="Attach labeled news fixtures (PAPER impact features only)"
    ),
) -> None:
    """One or more paper cycles. Default mode is paper. LIVE is not started here."""
    from hotflow.portfolio.session import PaperSession, mock_markets, run_kill_recovery_drill

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live" and not live_gates_open(cfg):
        raise typer.BadParameter("LIVE gates closed; staying out of transmit. Use paper.")
    if mock:
        cfg = _prepare_mock_config(cfg)
    store = _store(cfg)
    obs = _observability(cfg, serve=serve_metrics)
    session = PaperSession(
        cfg,
        store,
        obs=obs,
        use_twap_fixtures=mock,
        cache_path=str(twap_cache) if twap_cache else None,
        sports_cache_path=str(sports_cache) if sports_cache else None,
        use_news_fixtures=news_fixtures,
    )
    for _cycle in range(max(1, cycles)):
        if mock:
            markets = mock_markets()
            if news_fixtures:
                from hotflow.pipeline import demo_market

                markets = [demo_market(hot=True), *markets]
            session.run_markets(markets)
        else:
            scanned = asyncio.run(
                session.pipe.run_scan(
                    use_network=True,
                    attach_subscriber=_attach_rtds(cfg, mock, rtds_live),
                    attach_sports_subscriber=_attach_sports(cfg, mock, sports_live),
                )
            )
            for result in scanned.get("results") or []:
                order = result.get("order") if isinstance(result.get("order"), dict) else None
                if order and order.get("token_id") and order.get("price") is not None:
                    session.marks[str(order["token_id"])] = float(order["price"])
            session.cycle_summaries.append(scanned)
    flatten_rows: list[dict[str, Any]] = []
    if flatten or cfg.trading.paper_flatten_at_session_end:
        flatten_rows = session.flatten()
    drill = None
    if kill_drill:
        drill = run_kill_recovery_drill(session, acknowledge=acknowledge or None)
    payload = session.report()
    payload["flatten"] = flatten_rows
    if drill is not None:
        payload["kill_drill"] = drill
    target = out or Path(cfg.storage.reports_dir) / f"paper-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_report(target, payload)
    accepted = sum(c.get("accepted", 0) for c in session.cycle_summaries)
    snap = session.ledger.snapshot()
    typer.echo(
        f"paper-run mode={cfg.trading.mode} accepted={accepted} "
        f"equity={snap.equity:.4f} realized={snap.realized_pnl:.4f} "
        f"win_rate={snap.win_rate:.3f} report={target}"
    )


@app.command("rtds-cache")
def rtds_cache(
    config: Path | None = typer.Option(None, "--config", "-c"),
    mock: bool = typer.Option(
        True, "--mock/--live", help="Mock injects official-shape fixtures; --live opens public RTDS"
    ),
    duration: float | None = typer.Option(None, "--duration", help="Live collect seconds (public RTDS only)"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Fill the official TWAP print cache. PAPER data only — never places orders.

    Default is --mock (no socket). --live is the optional unauthenticated RTDS
    reader at wss://ws-live-data.polymarket.com.
    """
    cfg = load_config(config)
    target = out or Path(cfg.feeds.rtds.cache_path)
    cache = TwapPrintCache(max_age_ms=cfg.feeds.rtds.max_data_age_ms, path=target, persist=True)
    if mock:
        for obs in default_paper_fixtures().values():
            cache.put(obs)
        cache.save(target)
        typer.echo(f"rtds-cache mock prints={len(cache.snapshot()['prints'])} path={target}")
        return

    from hotflow.marketdata.rtds_subscriber import run_live_public_collect

    if duration is not None:
        cfg.feeds.rtds.collect_seconds = duration
    prints = asyncio.run(run_live_public_collect(cache, cfg.feeds.rtds))
    cache.save(target)
    typer.echo(f"rtds-cache live prints={prints} path={target}")


@app.command("sports-cache")
def sports_cache_cmd(
    config: Path | None = typer.Option(None, "--config", "-c"),
    mock: bool = typer.Option(
        True, "--mock/--live", help="Mock injects official-shape fixtures; --live opens public Sports WS"
    ),
    seconds: float | None = typer.Option(None, "--seconds", help="Live collect seconds (public Sports WS only)"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Fill the official-shape Sports WS cache. PAPER data only — never places orders.

    Default is --mock (no socket). --live is the optional unauthenticated Sports
    reader at wss://sports-api.polymarket.com/ws. Data is informational.
    """
    cfg = load_config(config)
    target = out or Path(cfg.feeds.sports_ws.cache_path)
    cache = SportsGameCache(max_age_ms=cfg.feeds.sports_ws.max_data_age_ms, path=target, persist=True)
    if mock:
        for state in default_sports_cache_fixtures():
            cache.put(state)
        cache.save(target)
        typer.echo(f"sports-cache mock games={len(cache.snapshot()['games'])} path={target}")
        return

    from hotflow.marketdata.sports_subscriber import run_live_public_sports_collect

    if seconds is not None:
        cfg.feeds.sports_ws.collect_seconds = seconds
    prints = asyncio.run(run_live_public_sports_collect(cache, cfg.feeds.sports_ws))
    cache.save(target)
    typer.echo(
        f"sports-cache live accepted={prints} stored={len(cache.snapshot()['games'])} path={target}"
    )


@app.command("weather-fixtures")
def weather_fixtures_cmd(
    out: Path | None = typer.Option(None, "--out", help="Directory for redacted Gamma weather JSON"),
    data_out: Path | None = typer.Option(
        None, "--data-out", help="Optional gitignored copy (e.g. data/weather)"
    ),
    open_only: bool = typer.Option(False, "--open-only", help="Skip closed=true event pages"),
) -> None:
    """Pull public Gamma weather-tag market text. PAPER metadata only — no forecasts, no orders."""
    from hotflow.discovery.weather_gamma import DEFAULT_FIXTURE_DIR, collect_weather_fixtures

    dest = out or DEFAULT_FIXTURE_DIR
    payload = asyncio.run(
        collect_weather_fixtures(
            directory=dest,
            data_directory=data_out,
            include_closed=not open_only,
        )
    )
    typer.echo(
        f"weather-fixtures scanned={payload.get('scanned')} saved={payload.get('saved')} "
        f"path={payload.get('path')}"
    )


@app.command("esports-fixtures")
def esports_fixtures_cmd(
    out: Path | None = typer.Option(None, "--out", help="Directory for redacted Gamma esports JSON"),
    data_out: Path | None = typer.Option(
        None, "--data-out", help="Optional gitignored copy (e.g. data/esports)"
    ),
    open_only: bool = typer.Option(False, "--open-only", help="Skip closed=true event pages"),
) -> None:
    """Pull public Gamma esports-tag market text. PAPER metadata only — no live odds."""
    from hotflow.discovery.esports_gamma import DEFAULT_FIXTURE_DIR, collect_esports_fixtures

    dest = out or DEFAULT_FIXTURE_DIR
    payload = asyncio.run(
        collect_esports_fixtures(
            directory=dest,
            data_directory=data_out,
            include_closed=not open_only,
        )
    )
    typer.echo(
        f"esports-fixtures scanned={payload.get('scanned')} saved={payload.get('saved')} "
        f"path={payload.get('path')}"
    )


@app.command("news-fixtures")
def news_fixtures_cmd(
    config: Path | None = typer.Option(None, "--config", "-c"),
    out: Path | None = typer.Option(None, "--out"),
    fetch_public: bool = typer.Option(
        False, "--fetch-public", help="Default-off. Live news scrape is not implemented."
    ),
    shadow: bool = typer.Option(False, "--shadow", help="Also score would_* after news-adjusted FV"),
) -> None:
    """Run labeled news fixtures through classify → validate → impact. No orders."""
    from hotflow.monitoring.redact import redact
    from hotflow.news.engine import NewsEngine, classify
    from hotflow.news.fixtures import labeled_news_items, public_fetch_status

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("news-fixtures refuses LIVE mode")
    cfg = _prepare_mock_config(cfg)
    engine = NewsEngine(cfg.news)
    items = labeled_news_items()
    engine.ingest_many(items)
    market = demo_market(hot=True)
    rows: list[dict[str, Any]] = []
    engine.reset_seen()
    for item in items:
        bound = market
        if item.market_id == "demo-btc-repriced":
            bound = demo_market(hot=True)
            bound.market_id = "demo-btc-repriced"
            if bound.book is not None:
                from hotflow.types import BookLevel

                bound.book.asks = [BookLevel(price=0.71, size=80.0)]
                bound.book.bids = [BookLevel(price=0.69, size=90.0)]
            bound.best_ask = 0.71
            bound.best_bid = 0.69
        elif item.market_id == "demo-btc-news-edge":
            bound = demo_market(hot=True)
            bound.market_id = "demo-btc-news-edge"
        impact = engine.evaluate_item(item, bound, p_base=0.55)
        rows.append(
            {
                "news_id": item.news_id,
                "classification": classify(item).value,
                "impact": impact.as_dict(),
                "orders": False,
            }
        )
    paper = PaperPipeline(cfg, use_twap_fixtures=True, news_engine=NewsEngine(cfg.news))
    paper.news.ingest_many(
        [item for item in items if item.news_id == "btc-sec-filing"],
    )
    paper_result = paper.evaluate_market(demo_market(hot=True), p_info=0.55)
    shadow_row: dict[str, Any] | None = None
    if shadow:
        cfg.trading.mode = "shadow"
        cfg.trading.shadow = True
        sh = PaperPipeline(cfg, use_twap_fixtures=True, news_engine=NewsEngine(cfg.news))
        sh.news.ingest_many([item for item in items if item.news_id == "btc-sec-filing"])
        shadow_row = sh.evaluate_market(demo_market(hot=True), p_info=0.55)
    payload = redact(
        {
            "mode": "paper",
            "origin": "labeled_fixtures",
            "public_fetch": public_fetch_status(enabled=fetch_public or cfg.news.public_fetch),
            "rows": rows,
            "paper_evaluate": {
                "accepted": paper_result.get("accepted"),
                "reason": paper_result.get("reason"),
                "news": paper_result.get("news"),
                "p_fair": (paper_result.get("edge") or {}).get("p_fair")
                if isinstance(paper_result.get("edge"), dict)
                else None,
            },
            "shadow_evaluate": None
            if shadow_row is None
            else {
                "would_buy": shadow_row.get("would_buy"),
                "would_sell": shadow_row.get("would_sell"),
                "sent": False,
                "news": shadow_row.get("news"),
                "reason": shadow_row.get("reason"),
            },
            "news_to_order": False,
            "note": "News adjusts p_info/confidence only. Risk and min-edge still apply.",
        }
    )
    if not isinstance(payload, dict):
        raise RuntimeError("redact must return a mapping")
    report_path = out or Path(cfg.storage.reports_dir) / (
        f"news-fixtures-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(report_path, payload)
    applied = sum(1 for row in rows if (row.get("impact") or {}).get("apply"))
    typer.echo(
        f"news-fixtures items={len(rows)} applied={applied} "
        f"paper_accepted={paper_result.get('accepted')} live=false report={report_path}"
    )


@app.command()
def backtest(
    fixture: Path = typer.Option(..., "--fixture", "-f", help="Recorded event-stream JSON"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Replay a time-ordered fixture on BACKTEST. Never sends LIVE orders."""
    from hotflow.backtest import EventDrivenBacktester

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("backtest refuses LIVE mode")
    cfg.trading.mode = "backtest"
    obs = Observability.from_config(cfg, announce_restart=False)
    report = EventDrivenBacktester(cfg, obs=obs).run_fixture(fixture)
    target = out or Path(cfg.storage.reports_dir) / (
        f"backtest-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, report)
    metrics = report.get("metrics") or {}
    typer.echo(
        f"backtest trades={metrics.get('trade_count')} expectancy={metrics.get('expectancy')} "
        f"dd={metrics.get('max_drawdown')} report={target}"
    )


@app.command()
def shadow(
    config: Path | None = typer.Option(None, "--config", "-c"),
    mock: bool = typer.Option(True, "--mock", help="Documented fixtures only"),
    cycles: int = typer.Option(1, "--cycles"),
    out: Path | None = typer.Option(None, "--out"),
    serve_metrics: bool = typer.Option(False, "--serve-metrics", help="Bind localhost /metrics /health /ready"),
    compare_paper: bool = typer.Option(
        False, "--compare-paper", help="Same-fixture paper fills vs shadow would_* (no live-edge claim)"
    ),
    stale_probe: bool = typer.Option(False, "--stale-probe", help="Age a fixture book and assert STALE skip"),
    news_fixtures: bool = typer.Option(
        False, "--news-fixtures", help="Attach labeled news fixtures; would_* after news-adjusted FV"
    ),
) -> None:
    """Score would_buy / would_sell on real-shaped data. Never sends orders."""
    from hotflow.backtest.shadow import ShadowSession, compare_shadow_vs_paper, run_stale_probe
    from hotflow.portfolio.session import mock_markets

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("shadow refuses LIVE mode")
    if not mock:
        raise typer.BadParameter("shadow --mock is the supported path in this pass")
    cfg.trading.mode = "shadow"
    cfg.trading.shadow = True
    cfg = _prepare_mock_config(cfg)
    obs = _observability(cfg, serve=serve_metrics)
    session = ShadowSession(cfg, obs=obs, use_twap_fixtures=True, use_news_fixtures=news_fixtures)
    markets = mock_markets()
    if news_fixtures:
        markets = [demo_market(hot=True), *markets]
    for _cycle in range(max(1, cycles)):
        session.run_cycle(markets)
    if stale_probe:
        run_stale_probe(session)
    if compare_paper:
        paper_cfg = _prepare_mock_config(load_config(config))
        session.comparison = compare_shadow_vs_paper(paper_cfg, markets)
    payload = session.report()
    target = out or Path(cfg.storage.reports_dir) / (
        f"shadow-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, payload)
    complete = payload.get("completeness") or {}
    intents = payload.get("intents") or {}
    typer.echo(
        f"shadow mode=shadow cycles={payload.get('cycle_count')} "
        f"decisions={complete.get('rows', 0)} complete={complete.get('complete', 0)} "
        f"would_buy={intents.get('would_buy', 0)} skip={intents.get('skip', 0)} "
        f"sent_orders=0 report={target}"
    )


@app.command("shadow-soak")
def shadow_soak(
    config: Path | None = typer.Option(None, "--config", "-c"),
    cycles: int = typer.Option(5, "--cycles"),
    serve_metrics: bool = typer.Option(False, "--serve-metrics"),
    compare_paper: bool = typer.Option(True, "--compare-paper/--no-compare-paper"),
    stale_probe: bool = typer.Option(True, "--stale-probe/--no-stale-probe"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Longer SHADOW soak: completeness, stale probe, optional paper comparison. No orders."""
    shadow(
        config=config,
        mock=True,
        cycles=cycles,
        out=out,
        serve_metrics=serve_metrics,
        compare_paper=compare_paper,
        stale_probe=stale_probe,
    )


@app.command("record-stream")
def record_stream(
    mock: bool = typer.Option(True, "--mock/--live", help="Mock writes the synthetic longer fixture"),
    seconds: float | None = typer.Option(None, "--seconds", help="Live collect seconds (capped)"),
    rtds: bool = typer.Option(False, "--rtds", help="Also collect public RTDS 30s/60s prints"),
    symbol: str = typer.Option("btc/usd", "--symbol", help="Documented Chainlink symbol"),
    token_id: str | None = typer.Option(None, "--token-id", help="Public CLOB token id (live only)"),
    out: Path | None = typer.Option(None, "--out"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Record official-shape CLOB book (+ optional RTDS) for backtest. No orders."""
    from hotflow.backtest.recorder import (
        DEFAULT_FIXTURE_DIR,
        DEFAULT_SECONDS,
        LONGER_SYNTHETIC_NAME,
        MAX_SECONDS,
        build_synthetic_longer_stream,
        record_live_stream,
        write_stream,
    )

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("record-stream refuses LIVE trading mode")
    if mock:
        document = build_synthetic_longer_stream()
        target = out or (DEFAULT_FIXTURE_DIR / LONGER_SYNTHETIC_NAME)
        write_stream(target, document)
        typer.echo(
            f"record-stream origin=synthetic_official_shape events={document.get('event_count')} "
            f"path={target}"
        )
        return
    duration = min(seconds or cfg.recorder.default_seconds or DEFAULT_SECONDS, MAX_SECONDS)
    document = asyncio.run(
        record_live_stream(
            seconds=duration,
            poll_interval_s=cfg.recorder.poll_interval_s,
            token_id=token_id,
            include_rtds=rtds,
            symbol=symbol,
        )
    )
    target = out or Path(cfg.storage.reports_dir) / (
        f"record-stream-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_stream(target, document)
    typer.echo(
        f"record-stream origin=live_public_clob events={document.get('event_count')} "
        f"rtds={rtds} path={target}"
    )


@app.command()
def tune(
    report: list[Path] = typer.Option(..., "--report", help="Backtest report JSON (repeatable)"),
    objective: str = typer.Option("expectancy", "--objective"),
    hypothesis: str = typer.Option("", "--hypothesis"),
    write_suggestion: Path | None = typer.Option(
        None, "--write-suggestion", help="Non-live path under reports/ only"
    ),
    out: Path | None = typer.Option(None, "--out"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Offline tuner: bounded suggestions from backtest reports. Never auto-applies."""
    import json

    from hotflow.analytics.tuner import OfflineTuner
    from hotflow.analytics.tuner import write_suggestion as dump_suggestion

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live" or cfg.tuner.auto_apply:
        raise typer.BadParameter("tune refuses LIVE mode and auto_apply")
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in report]
    payload = OfflineTuner().propose_from_reports(
        rows, objective=objective, hypothesis=hypothesis
    )
    target = out or Path(cfg.storage.reports_dir) / (
        f"tune-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, payload.as_dict())
    if write_suggestion is not None:
        dump_suggestion(write_suggestion, payload)
        typer.echo(f"tune suggestion={write_suggestion} applied=false")
    typer.echo(
        f"tune refused={payload.refused} suggested={len(payload.suggested)} "
        f"applied=false report={target}"
    )


@app.command("paper-soak")
def paper_soak(
    config: Path | None = typer.Option(None, "--config", "-c"),
    cycles: int = typer.Option(5, "--cycles"),
    serve_metrics: bool = typer.Option(False, "--serve-metrics"),
    kill_drill: bool = typer.Option(True, "--kill-drill/--no-kill-drill"),
    acknowledge: str = typer.Option(
        "operator confirmed recover",
        "--acknowledge",
        help="Explicit kill-switch recovery text",
    ),
    out: Path | None = typer.Option(None, "--out"),
    long: bool = typer.Option(
        False, "--long", help="Labeled synthetic official-shape lots until ≥50 closes (PAPER)"
    ),
    mixed: bool = typer.Option(
        False,
        "--mixed",
        help="Deterministic 5m/15m crypto + news + weather/sports book (allocator/regime audit)",
    ),
    target_closes: int | None = typer.Option(
        None, "--target-closes", help="Labeled closed trades to record (implies long soak)"
    ),
) -> None:
    """PAPER soak. Default: short mock + flatten + kill drill. --long labeled closes. --mixed allocator audit."""
    if mixed and (long or target_closes is not None):
        raise typer.BadParameter("paper-soak --mixed cannot combine with --long / --target-closes")
    if mixed:
        from hotflow.portfolio.mixed_soak import run_mixed_paper_soak
        from hotflow.portfolio.session import PaperSession

        cfg = load_config(config)
        if cfg.trading.mode.lower() == "live":
            raise typer.BadParameter("paper-soak --mixed refuses LIVE mode")
        cfg = _prepare_mock_config(cfg)
        cfg.trading.mode = "paper"
        obs = _observability(cfg, serve=serve_metrics)
        session = PaperSession(cfg, _store(cfg), obs=obs, use_twap_fixtures=True)
        meta = run_mixed_paper_soak(session, cycles=cycles)
        payload = session.report()
        payload.update(meta)
        snap = session.ledger.snapshot()
        payload["ledger"] = {
            "origin": meta.get("origin"),
            "starting_cash": snap.starting_cash,
            "snapshot": snap.as_dict(),
            "events": payload.get("events"),
        }
        payload["auto_disable"] = False
        target = out or Path(cfg.storage.reports_dir) / (
            f"paper-soak-mixed-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        write_report(target, payload)
        totals = meta.get("totals") or {}
        typer.echo(
            f"paper-soak mixed origin={meta.get('origin')} cycles={meta.get('cycles')} "
            f"accepted={totals.get('accepted')} skipped={totals.get('skipped')} "
            f"correlated={totals.get('correlated_exposure')} "
            f"downsize={totals.get('portfolio_downsized')} "
            f"news_shock_overlay={(totals.get('overlay_applied') or {}).get('news_shock', 0)} "
            f"near_resolution_overlay={(totals.get('overlay_applied') or {}).get('near_resolution', 0)} "
            f"equity={snap.equity:.4f} live=false report={target}"
        )
        return
    if long or target_closes is not None:
        from hotflow.portfolio.long_soak import DEFAULT_TARGET_CLOSES, run_labeled_long_soak
        from hotflow.portfolio.session import PaperSession

        cfg = load_config(config)
        if cfg.trading.mode.lower() == "live":
            raise typer.BadParameter("paper-soak --long refuses LIVE mode")
        cfg = _prepare_mock_config(cfg)
        cfg.trading.mode = "paper"
        obs = _observability(cfg, serve=serve_metrics)
        session = PaperSession(cfg, _store(cfg), obs=obs, use_twap_fixtures=True)
        target_n = target_closes or DEFAULT_TARGET_CLOSES
        meta = run_labeled_long_soak(session, target_closes=target_n)
        payload = session.report()
        payload.update(meta)
        snap = session.ledger.snapshot()
        payload["ledger"] = {
            "origin": meta.get("origin"),
            "starting_cash": snap.starting_cash,
            "snapshot": snap.as_dict(),
            "events": payload.get("events"),
        }
        payload["auto_disable"] = False
        target = out or Path(cfg.storage.reports_dir) / (
            f"paper-soak-long-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        write_report(target, payload)
        typer.echo(
            f"paper-soak long origin={meta.get('origin')} closed={snap.closed_count} "
            f"target={target_n} fail_safe={meta.get('fail_safe')} live=false report={target}"
        )
        return
    paper_run(
        config=config,
        cycles=cycles,
        mock=True,
        twap_cache=None,
        sports_cache=None,
        rtds_live=False,
        sports_live=False,
        out=out,
        serve_metrics=serve_metrics,
        flatten=True,
        kill_drill=kill_drill,
        acknowledge=acknowledge,
    )


@app.command("serve-metrics")
def serve_metrics_cmd(
    config: Path | None = typer.Option(None, "--config", "-c"),
    bind: str | None = typer.Option(None, "--bind", help="Default 127.0.0.1"),
    port: int | None = typer.Option(None, "--port", help="Default monitoring.prometheus_port"),
) -> None:
    """Optional localhost scrape: /metrics /health /ready. PAPER only. No orders."""
    import time

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("serve-metrics refuses LIVE mode")
    obs = Observability.from_config(cfg, announce_restart=True)
    server = obs.start_http(bind=bind, port=port)
    host, listen = server.server_address[:2]
    typer.echo(f"serving http://{host}:{listen}/metrics /health /ready mode={cfg.trading.mode}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        obs.stop_http()


@app.command("failure-soak")
def failure_soak(
    config: Path | None = typer.Option(None, "--config", "-c"),
    out: Path | None = typer.Option(None, "--out"),
    serve_metrics: bool = typer.Option(False, "--serve-metrics"),
) -> None:
    """Inject mocked failures. Must fail safe: no orders, no invented data. No LIVE."""
    from hotflow.failure.soak import run_failure_soak

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("failure-soak refuses LIVE mode")
    cfg.trading.mode = "paper"
    obs = _observability(cfg, serve=serve_metrics)
    payload = run_failure_soak(obs=obs)
    target = out or Path(cfg.storage.reports_dir) / (
        f"failure-soak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, payload)
    typer.echo(
        f"failure-soak fail_safe={payload.get('fail_safe')} "
        f"scenarios={payload.get('scenario_count')} sent_orders=0 "
        f"live_blocked={payload.get('gates', {}).get('live_still_blocked')} report={target}"
    )


@app.command("walk-forward")
def walk_forward_cmd(
    config: Path | None = typer.Option(None, "--config", "-c"),
    report: Path | None = typer.Option(None, "--report", help="Existing paper-soak/backtest JSON"),
    from_reports: Path | None = typer.Option(None, "--from-reports"),
    train_size: int = typer.Option(20, "--train-size"),
    test_size: int = typer.Option(10, "--test-size"),
    step: int = typer.Option(10, "--step"),
    expanding: bool = typer.Option(True, "--expanding/--rolling"),
    rank_by: str | None = typer.Option(None, "--rank-by", help="Refuses abs_pnl / pnl"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Walk-forward + regime split on existing reports. Mixed soak uses detected labels."""
    from hotflow.analytics.review import load_review_source
    from hotflow.analytics.walkforward import build_walk_forward, format_walk_forward

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("walk-forward refuses LIVE mode")
    payload_in, source = load_review_source(report, from_reports)
    if payload_in is None and report is None and from_reports is None:
        raise typer.BadParameter("pass --report or --from-reports; will not invent trades")
    body = build_walk_forward(
        payload_in,
        source=source,
        train_size=train_size,
        test_size=test_size,
        step=step,
        expanding=expanding,
        rank_metric=rank_by,
    )
    target = out or Path(cfg.storage.reports_dir) / (
        f"walk-forward-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, body)
    typer.echo(format_walk_forward(body))
    typer.echo(f"report={target}")
    if body.get("refused"):
        raise typer.Exit(code=1)


@app.command()
def performance(
    config: Path | None = typer.Option(None, "--config", "-c"),
    report: Path | None = typer.Option(None, "--report", help="Existing paper/backtest JSON (no invented trades)"),
    from_reports: Path | None = typer.Option(None, "--from-reports", help="Load latest paper/backtest JSON"),
    rank_by: str | None = typer.Option(None, "--rank-by", help="Refuses abs_pnl / pnl"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Review Gross/Net/fees/win-rate/decay from existing reports. Suggestion-only."""
    from hotflow.analytics.review import build_review, format_review, load_review_source

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("performance refuses LIVE mode")
    payload_in, source = load_review_source(report, from_reports)
    if payload_in is None and report is None and from_reports is None:
        raise typer.BadParameter("pass --report or --from-reports; will not invent trades")
    body = build_review(payload_in, source=source, rank_metric=rank_by)
    target = out or Path(cfg.storage.reports_dir) / (
        f"performance-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, body)
    typer.echo(format_review(body))
    typer.echo(f"report={target}")
    if body.get("refused"):
        raise typer.Exit(code=1)


@app.command()
def decay(
    config: Path | None = typer.Option(None, "--config", "-c"),
    report: Path | None = typer.Option(None, "--report"),
    from_reports: Path | None = typer.Option(None, "--from-reports"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Alpha-decay windows vs baseline. Never auto-disables a strategy."""
    from hotflow.analytics.review import build_review, format_review, load_review_source

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("decay refuses LIVE mode")
    payload_in, source = load_review_source(report, from_reports)
    if payload_in is None and report is None and from_reports is None:
        raise typer.BadParameter("pass --report or --from-reports; will not invent trades")
    body = build_review(payload_in, source=source)
    target = out or Path(cfg.storage.reports_dir) / (
        f"decay-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, body)
    typer.echo(format_review(body))
    typer.echo(f"auto_disable=False report={target}")


@app.command()
def readiness(
    config: Path | None = typer.Option(None, "--config", "-c"),
    from_reports: Path | None = typer.Option(
        None, "--from-reports", help="Load latest soak/gate JSON from this directory (no invented results)"
    ),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Roll up paper/shadow/failure/live-gates. live_ready stays false. No LIVE."""
    from hotflow.readiness.collect import collect_by_running, collect_from_reports
    from hotflow.readiness.rollup import build_readiness, format_summary

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("readiness refuses LIVE mode")
    bundle = collect_from_reports(from_reports) if from_reports else collect_by_running(cfg)
    payload = build_readiness(
        paper=bundle["paper"],
        shadow=bundle["shadow"],
        failure=bundle["failure"],
        live_gates=bundle["live_gates"],
        sources=bundle["sources"],
    )
    target = out or Path(cfg.storage.reports_dir) / (
        f"readiness-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, payload)
    typer.echo(format_summary(payload))
    typer.echo(f"report={target}")
    if not payload.get("ok"):
        raise typer.Exit(code=1)


@app.command("live-gates")
def live_gates_cmd(
    config: Path | None = typer.Option(None, "--config", "-c"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Print LIVE acceptance gates. Exits 1 if any gate is unexpectedly open. No transmit."""
    from hotflow.execution.live_gate import inspect_live_gates

    cfg = load_config(config)
    report = inspect_live_gates(cfg)
    for gate in report.gates:
        state = "OPEN" if gate.open else "CLOSED"
        typer.echo(f"{gate.id}={state} detail={gate.detail}")
    typer.echo(
        f"live_gates_open={report.live_gates_open} freeze_ok={report.freeze_ok} "
        f"signing_implemented={report.signing_implemented} mode={report.mode}"
    )
    if out is not None:
        write_report(out, report.as_dict())
        typer.echo(f"report={out}")
    if not report.freeze_ok:
        raise typer.Exit(code=1)


@app.command("skip-audit")
def skip_audit_cmd(
    config: Path | None = typer.Option(None, "--config", "-c"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Parte 47 cold-path skip rollup from SQLite. No production mutation."""
    from hotflow.analytics.skip_audit import format_skip_audit, rollup_skip_audit

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("skip-audit refuses LIVE mode")
    store = _store(cfg)
    body = rollup_skip_audit(store.list_signals(), source=str(cfg.storage.sqlite_path))
    target = out or Path(cfg.storage.reports_dir) / (
        f"skip-audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, body)
    typer.echo(format_skip_audit(body))
    typer.echo(f"report={target} production_changed=False")


@app.command()
def version() -> None:
    from hotflow import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
