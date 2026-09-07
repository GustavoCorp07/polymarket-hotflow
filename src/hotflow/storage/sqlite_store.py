"""SQLite persistence designed to lift to Postgres/Timescale later."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

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
