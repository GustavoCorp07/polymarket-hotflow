"""Offline auto-tuner stub. Never changes live risk limits autonomously."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TuneProposal:
    name: str
    suggested: dict[str, float]
    applied: bool = False


class AutoTunerStub:
    def propose(self, metric_name: str, history: list[float]) -> TuneProposal:
        if not history:
            return TuneProposal(name=metric_name, suggested={})
        mean = sum(history) / len(history)
        return TuneProposal(name=metric_name, suggested={"mean_observed": mean}, applied=False)

    def apply(self, proposal: TuneProposal) -> TuneProposal:
        # Explicit no-op: human/offline review required.
        proposal.applied = False
        return proposal
