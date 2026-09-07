"""Pull closed-trade rows from real paper / backtest / shadow reports.

Never invents PnL, fills, or timestamps. Missing fields stay null.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class NormalizedTrade:
    pnl: float
    fee: float | None = None
    slippage: float | None = None
    style: str | None = None
    ts: datetime | None = None
    open_ts: datetime | None = None
    holding_s: float | None = None
    mae: float | None = None
    mfe: float | None = None
    source: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "pnl": self.pnl,
            "fee": self.fee,
            "slippage": self.slippage,
            "style": self.style,
            "ts": self.ts.isoformat() if self.ts else None,
            "open_ts": self.open_ts.isoformat() if self.open_ts else None,
            "holding_s": self.holding_s,
            "mae": self.mae,
            "mfe": self.mfe,
            "source": self.source,
        }


@dataclass
class TradeExtract:
    trades: list[NormalizedTrade] = field(default_factory=list)
    source_kind: str = "unknown"
    strategy_id: str | None = None
    session_id: str | None = None
    starting_cash: float | None = None
    session_fees: float | None = None
    session_drawdown: float | None = None
    signal_half_life_ms: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def pnls(self) -> list[float]:
        return [row.pnl for row in self.trades]


def _meta(report: dict[str, Any]) -> dict[str, Any]:
    raw_acc = report.get("accounting")
    accounting: dict[str, Any] = raw_acc if isinstance(raw_acc, dict) else {}
    raw_exp = report.get("experiment")
    experiment: dict[str, Any] = raw_exp if isinstance(raw_exp, dict) else {}
    half = report.get("signal_half_life_ms")
    if half is None:
        half = experiment.get("signal_half_life_ms")
    return {
        "strategy_id": report.get("strategy_id") or experiment.get("strategy_id") or experiment.get("strategy"),
        "session_id": report.get("session_id") or accounting.get("session_id"),
        "starting_cash": accounting.get("starting_cash") if accounting else report.get("starting_cash"),
        "session_fees": accounting.get("fees"),
        "session_drawdown": accounting.get("drawdown"),
        "signal_half_life_ms": float(half) if isinstance(half, (int, float)) else None,
    }


def extract_trades(report: dict[str, Any] | None) -> TradeExtract:
    if not report:
        return TradeExtract(source_kind="missing", notes=["report not provided; not invented"])
    mode = str(report.get("mode") or "").lower()
    if mode == "shadow":
        meta = _meta(report)
        return TradeExtract(
            source_kind="shadow",
            strategy_id=meta["strategy_id"],
            session_id=meta["session_id"],
            signal_half_life_ms=meta["signal_half_life_ms"],
            notes=["shadow has no realized PnL; not invented"],
        )
    if isinstance(report.get("trades"), list):
        return _from_backtest(report)
    if isinstance(report.get("events"), list) or isinstance(report.get("accounting"), dict):
        return _from_paper(report)
    return TradeExtract(source_kind="unknown", notes=["unrecognized report shape; no trades invented"])


def _from_backtest(report: dict[str, Any]) -> TradeExtract:
    meta = _meta(report)
    rows: list[NormalizedTrade] = []
    for raw in report.get("trades") or []:
        if not isinstance(raw, dict):
            continue
        pnl = raw.get("pnl")
        if pnl is None:
            continue
        decision = parse_ts(raw.get("decision_ts"))
        fill_ts = parse_ts(raw.get("ts"))
        holding = None
        if decision and fill_ts:
            holding = max(0.0, (fill_ts - decision).total_seconds())
        rows.append(
            NormalizedTrade(
                pnl=float(pnl),
                fee=float(raw["fee"]) if raw.get("fee") is not None else None,
                slippage=float(raw["slippage"]) if raw.get("slippage") is not None else None,
                style=str(raw["style"]) if raw.get("style") is not None else None,
                ts=fill_ts,
                open_ts=decision,
                holding_s=holding,
                mae=float(raw["mae"]) if raw.get("mae") is not None else None,
                mfe=float(raw["mfe"]) if raw.get("mfe") is not None else None,
                source="backtest",
            )
        )
    notes = []
    if not rows:
        notes.append("backtest report has no closed-trade pnl")
    return TradeExtract(
        trades=rows,
        source_kind="backtest",
        strategy_id=meta["strategy_id"],
        session_id=meta["session_id"],
        starting_cash=float(meta["starting_cash"]) if meta["starting_cash"] is not None else None,
        session_fees=float(meta["session_fees"]) if meta["session_fees"] is not None else None,
        session_drawdown=float(meta["session_drawdown"]) if meta["session_drawdown"] is not None else None,
        signal_half_life_ms=meta["signal_half_life_ms"],
        notes=notes,
    )


def _from_paper(report: dict[str, Any]) -> TradeExtract:
    meta = _meta(report)
    events = [row for row in (report.get("events") or []) if isinstance(row, dict)]
    rows = _closed_from_events(events) if events else []
    notes: list[str] = []
    if not rows:
        raw_acc = report.get("accounting")
        accounting: dict[str, Any] = raw_acc if isinstance(raw_acc, dict) else {}
        pnls = accounting.get("closed_pnls")
        if isinstance(pnls, list) and pnls:
            rows = [NormalizedTrade(pnl=float(item), source="paper_closed_pnls") for item in pnls]
            notes.append("holding/MAE/MFE/slippage not in closed_pnls; left null")
        else:
            notes.append("paper report has no closed trades")
    return TradeExtract(
        trades=rows,
        source_kind="paper",
        strategy_id=meta["strategy_id"],
        session_id=meta["session_id"],
        starting_cash=float(meta["starting_cash"]) if meta["starting_cash"] is not None else None,
        session_fees=float(meta["session_fees"]) if meta["session_fees"] is not None else None,
        session_drawdown=float(meta["session_drawdown"]) if meta["session_drawdown"] is not None else None,
        signal_half_life_ms=meta["signal_half_life_ms"],
        notes=notes,
    )


def _closed_from_events(events: list[dict[str, Any]]) -> list[NormalizedTrade]:
    opens: dict[str, dict[str, Any]] = {}
    marks: dict[str, list[tuple[datetime | None, float]]] = {}
    closed: list[NormalizedTrade] = []
    for event in events:
        token = str(event.get("token_id") or "")
        kind = str(event.get("kind") or "")
        ts = parse_ts(event.get("ts"))
        price = event.get("price")
        if kind == "MARK" and token and price is not None:
            marks.setdefault(token, []).append((ts, float(price)))
            continue
        if kind not in {"FILL", "FLATTEN"}:
            continue
        if event.get("closed"):
            opened = opens.pop(token, None)
            entry = float(opened["price"]) if opened and opened.get("price") is not None else None
            open_ts = parse_ts(opened.get("ts")) if opened else None
            size = float(event.get("size") or (opened or {}).get("size") or 0.0)
            holding = None
            if open_ts and ts:
                holding = max(0.0, (ts - open_ts).total_seconds())
            mae, mfe = _mae_mfe(marks.get(token) or [], entry, size, open_ts, ts)
            closed.append(
                NormalizedTrade(
                    pnl=float(event.get("realized_delta") or 0.0),
                    fee=float(event["fee"]) if event.get("fee") is not None else None,
                    slippage=None,
                    style=None,
                    ts=ts,
                    open_ts=open_ts,
                    holding_s=holding,
                    mae=mae,
                    mfe=mfe,
                    source="paper_ledger",
                )
            )
            continue
        if token:
            opens[token] = event
    return closed


def _mae_mfe(
    path: list[tuple[datetime | None, float]],
    entry: float | None,
    size: float,
    open_ts: datetime | None,
    close_ts: datetime | None,
) -> tuple[float | None, float | None]:
    if entry is None or size <= 0:
        return None, None
    excursions: list[float] = []
    for ts, price in path:
        if open_ts and ts is not None and ts < open_ts:
            continue
        if close_ts and ts is not None and ts > close_ts:
            continue
        excursions.append((price - entry) * size)
    if not excursions:
        return None, None
    return min(excursions), max(excursions)
