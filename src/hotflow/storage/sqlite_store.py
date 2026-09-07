"""SQLite persistence designed to lift to Postgres/Timescale later."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from hotflow.portfolio.ledger import LedgerEvent, LedgerSnapshot
from hotflow.types import OrderRecord, RiskDecision, SignalAudit

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT,
    hms REAL,
    tier TEXT,
    net_edge REAL,
    opportunity_score REAL,
    extra TEXT
);
CREATE TABLE IF NOT EXISTS risk_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    market_id TEXT,
    allowed INTEGER NOT NULL,
    veto INTEGER NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    filled_size REAL NOT NULL,
    avg_fill_price REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reject_reason TEXT,
    mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    market_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    market_id TEXT,
    token_id TEXT,
    side TEXT,
    size REAL,
    price REAL,
    fee REAL,
    cash_delta REAL,
    realized_delta REAL,
    closed INTEGER NOT NULL,
    client_order_id TEXT,
    note TEXT,
    cash_after REAL,
    equity_after REAL
);
CREATE TABLE IF NOT EXISTS ledger_snapshots (
    session_id TEXT PRIMARY KEY,
    starting_cash REAL NOT NULL,
    cash REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    fees REAL NOT NULL,
    equity REAL NOT NULL,
    peak_equity REAL NOT NULL,
    drawdown REAL NOT NULL,
    session_pnl REAL NOT NULL,
    win_rate REAL NOT NULL,
    expectancy REAL NOT NULL,
    closed_count INTEGER NOT NULL,
    positions TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _iso(value: datetime) -> str:
    return value.isoformat()


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_signal(self, row: SignalAudit) -> None:
        self._conn.execute(
            """INSERT INTO signals
            (ts, session_id, market_id, accepted, reason, detail, hms, tier, net_edge, opportunity_score, extra)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _iso(row.ts),
                row.session_id,
                row.market_id,
                int(row.accepted),
                row.reason,
                row.detail,
                row.hms,
                row.tier,
                row.net_edge,
                row.opportunity_score,
                json.dumps(row.extra),
            ),
        )
        self._conn.commit()

    def save_risk(self, market_id: str, decision: RiskDecision) -> None:
        self._conn.execute(
            """INSERT INTO risk_decisions (ts, market_id, allowed, veto, reason, detail)
            VALUES (datetime('now'),?,?,?,?,?)""",
            (market_id, int(decision.allowed), int(decision.veto), decision.reason, decision.detail),
        )
        self._conn.commit()

    def save_order(self, order: OrderRecord) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO orders
            (client_order_id, status, market_id, token_id, side, price, size, filled_size,
             avg_fill_price, created_at, updated_at, reject_reason, mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order.client_order_id,
                order.status.value,
                order.market_id,
                order.token_id,
                order.side.value,
                order.price,
                order.size,
                order.filled_size,
                order.avg_fill_price,
                _iso(order.created_at),
                _iso(order.updated_at),
                order.reject_reason,
                order.mode.value,
            ),
        )
        self._conn.commit()

    def save_trade(self, order: OrderRecord, size: float, price: float) -> None:
        self._conn.execute(
            """INSERT INTO trades (ts, client_order_id, market_id, token_id, side, price, size)
            VALUES (datetime('now'),?,?,?,?,?,?)""",
            (order.client_order_id, order.market_id, order.token_id, order.side.value, price, size),
        )
        self._conn.commit()

    def save_feature(self, market_id: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO features (ts, market_id, payload) VALUES (datetime('now'),?,?)",
            (market_id, json.dumps(payload)),
        )
        self._conn.commit()

    def save_ledger_event(self, event: LedgerEvent) -> None:
        row = event.as_dict()
        self._conn.execute(
            """INSERT INTO ledger_events
            (ts, session_id, kind, market_id, token_id, side, size, price, fee,
             cash_delta, realized_delta, closed, client_order_id, note, cash_after, equity_after)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["ts"],
                row["session_id"],
                row["kind"],
                row["market_id"],
                row["token_id"],
                row["side"],
                row["size"],
                row["price"],
                row["fee"],
                row["cash_delta"],
                row["realized_delta"],
                int(row["closed"]),
                row["client_order_id"],
                row["note"],
                row["cash_after"],
                row["equity_after"],
            ),
        )
        self._conn.commit()

    def save_ledger_snapshot(self, snap: LedgerSnapshot) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO ledger_snapshots
            (session_id, starting_cash, cash, realized_pnl, unrealized_pnl, fees, equity,
             peak_equity, drawdown, session_pnl, win_rate, expectancy, closed_count,
             positions, event_count, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (
                snap.session_id,
                snap.starting_cash,
                snap.cash,
                snap.realized_pnl,
                snap.unrealized_pnl,
                snap.fees,
                snap.equity,
                snap.peak_equity,
                snap.drawdown,
                snap.session_pnl,
                snap.win_rate,
                snap.expectancy,
                snap.closed_count,
                json.dumps(snap.positions),
                snap.event_count,
            ),
        )
        self._conn.commit()

    def list_ledger_events(self, session_id: str | None = None) -> list[dict[str, Any]]:
        if session_id:
            cur = self._conn.execute(
                "SELECT * FROM ledger_events WHERE session_id=? ORDER BY id", (session_id,)
            )
        else:
            cur = self._conn.execute("SELECT * FROM ledger_events ORDER BY id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def list_signals(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT ts, session_id, market_id, accepted, reason, detail, hms, net_edge FROM signals"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def iter_orders(self) -> Iterable[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM orders")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            yield dict(zip(cols, row, strict=True))
