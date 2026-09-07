"""Parte 9 / 43 — dynamic resource plan from HMS tier."""

from __future__ import annotations

from hotflow.types import ResourceTier

RESOURCE_PLAN = {
    ResourceTier.COLD: "metadata_only",
    ResourceTier.WARM: "low_frequency",
    ResourceTier.HOT: "full_orderbook",
    ResourceTier.ULTRA_HOT: "highest_frequency",
}


def resource_plan(tier: ResourceTier) -> str:
    return RESOURCE_PLAN[tier]
