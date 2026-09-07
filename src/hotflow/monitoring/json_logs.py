"""Structured JSON logs with request / trade / signal / risk fields."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from hotflow.monitoring.redact import redact


def _scrub(value: Any) -> Any:
    return redact(value)


class JsonLogger:
    def __init__(self, name: str = "hotflow") -> None:
        self.logger = logging.getLogger(name)

    def emit(self, event: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), "event": event, **_scrub(fields)}
        self.logger.info(json.dumps(record, default=str, separators=(",", ":")))

    def request(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status: int,
        latency_ms: float,
        source: str = "local",
        **extra: Any,
    ) -> None:
        self.emit(
            "request",
            request_id=request_id,
            method=method,
            path=path,
            status=status,
            latency_ms=round(latency_ms, 3),
            source=source,
            **extra,
        )

    def signal(
        self,
        *,
        market_id: str,
        decision: str,
        reason: str,
        accepted: bool,
        mode: str,
        session_id: str,
        hms: float | None = None,
        net_edge: float | None = None,
        opportunity_score: float | None = None,
        latency_ms: float | None = None,
        side: str | None = None,
        **extra: Any,
    ) -> None:
        self.emit(
            "signal",
            market_id=market_id,
            decision=decision,
            reason=reason,
            accepted=accepted,
            mode=mode,
            session_id=session_id,
            hms=hms,
            net_edge=net_edge,
            opportunity_score=opportunity_score,
            latency_ms=latency_ms,
            side=side,
            **extra,
        )

    def trade(
        self,
        *,
        market_id: str,
        status: str,
        side: str,
        size: float,
        price: float,
        filled_size: float | None = None,
        fill_ratio: float | None = None,
        fees: float | None = None,
        slippage: float | None = None,
        client_order_id: str | None = None,
        mode: str | None = None,
        **extra: Any,
    ) -> None:
        self.emit(
            "trade",
            market_id=market_id,
            status=status,
            side=side,
            size=size,
            price=price,
            filled_size=filled_size,
            fill_ratio=fill_ratio,
            fees=fees,
            slippage=slippage,
            client_order_id=client_order_id,
            mode=mode,
            **extra,
        )

    def risk_decision(
        self,
        *,
        market_id: str,
        allowed: bool,
        reason: str,
        veto: bool = False,
        detail: str = "",
        kill_switch: bool = False,
        exposure: float | None = None,
        drawdown: float | None = None,
        mode: str | None = None,
        **extra: Any,
    ) -> None:
        self.emit(
            "risk_decision",
            market_id=market_id,
            allowed=allowed,
            reason=reason,
            veto=veto,
            detail=detail,
            kill_switch=kill_switch,
            exposure=exposure,
            drawdown=drawdown,
            mode=mode,
            **extra,
        )
