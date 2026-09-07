"""Kimi K3 client — cold-path only. Never import from decide/transmit."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import httpx

from hotflow.config import AIResearchConfig
from hotflow.official import KIMI_BASE_URL, KIMI_MODEL, KIMI_REASONING

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|passphrase|private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)POLY_[A-Z_]+"),
    re.compile(r"(?i)-----BEGIN .*PRIVATE KEY-----"),
)


class KimiRole(StrEnum):
    QUANT_RESEARCHER = "QUANT_RESEARCHER"
    STRATEGY_CRITIC = "STRATEGY_CRITIC"
    CODE_REVIEWER = "CODE_REVIEWER"
    PERFORMANCE_ANALYST = "PERFORMANCE_ANALYST"
    ANOMALY_INVESTIGATOR = "ANOMALY_INVESTIGATOR"
    NEWS_CLASSIFIER = "NEWS_CLASSIFIER"
    # Mission aliases (Parte 4)
    KIMI_QUANT_RESEARCHER = "QUANT_RESEARCHER"
    KIMI_STRATEGY_CRITIC = "STRATEGY_CRITIC"
    KIMI_CODE_REVIEWER = "CODE_REVIEWER"
    KIMI_PERFORMANCE_ANALYST = "PERFORMANCE_ANALYST"
    KIMI_ANOMALY_INVESTIGATOR = "ANOMALY_INVESTIGATOR"


SYSTEM_PROMPTS: dict[KimiRole, str] = {
    KimiRole.QUANT_RESEARCHER: "You are a quantitative researcher. Propose testable hypotheses. Never request secrets.",
    KimiRole.STRATEGY_CRITIC: "You criticize trading strategies for leakage, overfitting, and hidden risk. No secrets.",
    KimiRole.CODE_REVIEWER: "You review research code for correctness and safety. Refuse to handle credentials.",
    KimiRole.PERFORMANCE_ANALYST: "You analyze sanitized performance summaries. Do not ask for keys.",
    KimiRole.ANOMALY_INVESTIGATOR: "You investigate sanitized anomalies and data-quality issues. No credentials.",
    KimiRole.NEWS_CLASSIFIER: (
        "You classify sanitized news text for research only. Never invent sources, "
        "prices, or orders. Never request secrets. Cold-path only."
    ),
}


def resolve_api_key() -> str | None:
    return os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY")


def redact(text: str) -> str:
    cleaned = text
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


class KimiClient:
    def __init__(
        self,
        config: AIResearchConfig | None = None,
        *,
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        api_key: str | None = None,
    ) -> None:
        self.config = config or AIResearchConfig()
        self.transport = transport
        self._api_key = api_key if api_key is not None else resolve_api_key()

    def effort_for(self, *, hard: bool = False) -> str:
        effort = self.config.hard_task_reasoning_effort if hard else self.config.reasoning_effort
        if effort not in KIMI_REASONING:
            raise ValueError(f"reasoning_effort must be one of {sorted(KIMI_REASONING)}")
        return effort

    def _payload(self, role: KimiRole, user_text: str, *, hard: bool) -> dict[str, Any]:
        safe_user = redact(user_text)
        return {
            "model": self.config.model or KIMI_MODEL,
            "reasoning_effort": self.effort_for(hard=hard),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPTS[role]},
                {"role": "user", "content": safe_user},
            ],
        }

    def complete(
        self,
        role: KimiRole,
        user_text: str,
        *,
        hard: bool = False,
    ) -> dict[str, Any]:
        payload = self._payload(role, user_text, hard=hard)
        if self.transport is not None:
            return self.transport(payload)
        if not self._api_key:
            return {
                "mock": True,
                "role": role.value,
                "content": "Kimi mock response (no API key). Cold-path only.",
                "request": {k: payload[k] for k in ("model", "reasoning_effort")},
            }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        url = (self.config.base_url or KIMI_BASE_URL).rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=self.config.timeout_s) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
