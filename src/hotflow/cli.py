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
) -> None:
    """Scan Gamma + public CLOB and write a report. Never places live orders."""
    cfg = load_config(config)
    if mock:
        cfg = _prepare_mock_config(cfg)
    store = _store(cfg)
    pipe = PaperPipeline(
        cfg,
        store,
        use_twap_fixtures=mock,
        cache_path=twap_cache,
        sports_cache_path=sports_cache,
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
) -> None:
    """One or more paper cycles. Default mode is paper. LIVE is not started here."""
    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live" and not live_gates_open(cfg):
        raise typer.BadParameter("LIVE gates closed; staying out of transmit. Use paper.")
    if mock:
        cfg = _prepare_mock_config(cfg)
    store = _store(cfg)
    summaries: list[dict[str, Any]] = []
    for _cycle in range(max(1, cycles)):
        pipe = PaperPipeline(
            cfg,
            store,
            use_twap_fixtures=mock,
            cache_path=twap_cache,
            sports_cache_path=sports_cache,
        )
        if mock:
            results = [
                pipe.evaluate_market(demo_twap_market(hot=True)),
                pipe.evaluate_market(demo_weather_market(hot=True)),
                pipe.evaluate_market(demo_sports_nba_market(hot=True)),
                *[pipe.evaluate_market(item) for item in gamma_weather_demo_markets(hot=True)],
                *[pipe.evaluate_market(item) for item in gamma_esports_demo_markets(hot=True)],
            ]
            summaries.append(
                {
                    "ok": True,
                    "mode": cfg.trading.mode,
                    "markets": len(results),
                    "accepted": sum(1 for item in results if item.get("accepted")),
                    "results": results,
                    "audits": [a.model_dump(mode="json") for a in pipe.audits],
                }
            )
        else:
            summaries.append(
                asyncio.run(
                    pipe.run_scan(
                        use_network=True,
                        attach_subscriber=_attach_rtds(cfg, mock, rtds_live),
                        attach_sports_subscriber=_attach_sports(cfg, mock, sports_live),
                    )
                )
            )
    payload = {"cycles": summaries, "mode": cfg.trading.mode, "shadow": cfg.trading.shadow}
    target = out or Path(cfg.storage.reports_dir) / f"paper-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_report(target, payload)
    accepted = sum(c.get("accepted", 0) for c in summaries)
    typer.echo(f"paper-run mode={cfg.trading.mode} accepted={accepted} report={target}")


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
    report = EventDrivenBacktester(cfg).run_fixture(fixture)
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
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Score would_buy / would_sell on real-shaped data. Never sends orders."""
    from hotflow.backtest.shadow import run_shadow

    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live":
        raise typer.BadParameter("shadow refuses LIVE mode")
    cfg.trading.mode = "shadow"
    cfg.trading.shadow = True
    if mock:
        markets = [
            demo_twap_market(hot=True),
            demo_weather_market(hot=True),
            demo_sports_nba_market(hot=True),
        ]
        rows = run_shadow(cfg, markets)
    else:
        raise typer.BadParameter("shadow --mock is the supported path in this pass")
    payload = {"mode": "shadow", "sent_orders": False, "results": rows}
    target = out or Path(cfg.storage.reports_dir) / (
        f"shadow-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(target, payload)
    typer.echo(f"shadow decisions={len(rows)} sent_orders=0 report={target}")


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


@app.command()
def version() -> None:
    from hotflow import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
