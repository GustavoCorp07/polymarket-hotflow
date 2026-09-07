"""HOTFLOW CLI. Default paper. LIVE is gated."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.marketdata.twap_cache import TwapPrintCache
from hotflow.marketdata.twap_fixtures import default_paper_fixtures
from hotflow.pipeline import (
    PaperPipeline,
    demo_market,
    demo_sports_nba_market,
    demo_twap_market,
    demo_weather_market,
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
    rtds_live: bool = typer.Option(
        False, "--rtds-live", help="Attach public RTDS subscriber briefly (PAPER only)"
    ),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Scan Gamma + public CLOB and write a report. Never places live orders."""
    cfg = load_config(config)
    if mock:
        cfg = _prepare_mock_config(cfg)
    store = _store(cfg)
    pipe = PaperPipeline(cfg, store, use_twap_fixtures=mock, cache_path=twap_cache)

    async def _run() -> dict:
        if mock:
            markets = [
                demo_twap_market(hot=True),
                demo_weather_market(hot=True),
                demo_sports_nba_market(hot=True),
                demo_market(hot=False),
            ]
            markets[-1].market_id = "demo-cold"
            return await pipe.run_scan(
                markets=markets,
                use_network=False,
                attach_subscriber=_attach_rtds(cfg, mock, rtds_live),
            )
        return await pipe.run_scan(use_network=True, attach_subscriber=_attach_rtds(cfg, mock, rtds_live))

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
    rtds_live: bool = typer.Option(
        False, "--rtds-live", help="Attach public RTDS subscriber briefly (PAPER only)"
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
        pipe = PaperPipeline(cfg, store, use_twap_fixtures=mock, cache_path=twap_cache)
        if mock:
            results = [
                pipe.evaluate_market(demo_twap_market(hot=True)),
                pipe.evaluate_market(demo_weather_market(hot=True)),
                pipe.evaluate_market(demo_sports_nba_market(hot=True)),
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
                asyncio.run(pipe.run_scan(use_network=True, attach_subscriber=_attach_rtds(cfg, mock, rtds_live)))
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


@app.command()
def version() -> None:
    from hotflow import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
