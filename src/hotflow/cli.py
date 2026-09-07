"""HOTFLOW CLI. Default paper. LIVE is gated."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.pipeline import PaperPipeline, demo_market, write_report
from hotflow.storage.sqlite_store import SqliteStore

app = typer.Typer(help="POLYMARKET HOTFLOW — paper-first quant system")


def _store(config) -> SqliteStore:
    return SqliteStore(config.storage.sqlite_path)


@app.command()
def scan(
    config: Path | None = typer.Option(None, "--config", "-c"),
    mock: bool = typer.Option(False, "--mock", help="Use documented fixture if network is blocked"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Scan Gamma + public CLOB and write a report. Never places live orders."""
    cfg = load_config(config)
    store = _store(cfg)
    pipe = PaperPipeline(cfg, store)

    async def _run() -> dict:
        if mock:
            markets = [demo_market(hot=True), demo_market(hot=False)]
            markets[1].market_id = "demo-cold"
            return await pipe.run_scan(markets=markets, use_network=False)
        return await pipe.run_scan(use_network=True)

    payload = asyncio.run(_run())
    target = out or Path(cfg.storage.reports_dir) / f"scan-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_report(target, payload)
    typer.echo(f"mode={cfg.trading.mode} markets={payload.get('markets')} report={target}")


@app.command("paper-run")
def paper_run(
    config: Path | None = typer.Option(None, "--config", "-c"),
    cycles: int = typer.Option(1, "--cycles"),
    mock: bool = typer.Option(False, "--mock", help="Documented fixture when network is blocked"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """One or more paper cycles. Default mode is paper. LIVE is not started here."""
    cfg = load_config(config)
    if cfg.trading.mode.lower() == "live" and not live_gates_open(cfg):
        raise typer.BadParameter("LIVE gates closed; staying out of transmit. Use paper.")
    store = _store(cfg)
    summaries: list[dict[str, Any]] = []
    for _cycle in range(max(1, cycles)):
        pipe = PaperPipeline(cfg, store)
        if mock:
            market = demo_market(hot=True)
            # Fixture-only informational probability — not a live price.
            result = pipe.evaluate_market(market, p_info=0.62)
            summaries.append(
                {
                    "ok": True,
                    "mode": cfg.trading.mode,
                    "markets": 1,
                    "accepted": int(bool(result.get("accepted"))),
                    "results": [result],
                    "audits": [a.model_dump(mode="json") for a in pipe.audits],
                }
            )
        else:
            summaries.append(asyncio.run(pipe.run_scan(use_network=True)))
    payload = {"cycles": summaries, "mode": cfg.trading.mode, "shadow": cfg.trading.shadow}
    target = out or Path(cfg.storage.reports_dir) / f"paper-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_report(target, payload)
    accepted = sum(c.get("accepted", 0) for c in summaries)
    typer.echo(f"paper-run mode={cfg.trading.mode} accepted={accepted} report={target}")


@app.command()
def version() -> None:
    from hotflow import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
