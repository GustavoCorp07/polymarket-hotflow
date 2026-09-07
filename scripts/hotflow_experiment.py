#!/usr/bin/env python3
"""Cold-path /hotflow-experiment (Parte 49). Never auto-promotes live."""

from __future__ import annotations

import json
from pathlib import Path

from hotflow.analytics.experiments import ExperimentRecord, git_commit
from hotflow.analytics.tuner import AutoTunerStub
from hotflow.backtest import NullBacktester


class _Empty:
    def events(self):
        return iter(())


def main() -> None:
    exp = ExperimentRecord(
        experiment_id="exp-local",
        strategy="crypto_updown",
        category="crypto",
        git_commit=git_commit(),
        notes="hypothesis placeholder — implement on a branch, then backtest/OOS/walk-forward",
    )
    smoke = NullBacktester().run(_Empty())
    proposal = AutoTunerStub().propose("expectancy", [])
    out = Path("reports") / "experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"experiment": exp.model_dump(mode="json"), "backtest_smoke": smoke, "tuner": proposal.__dict__},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"experiment record {out}; live strategy was not replaced")


if __name__ == "__main__":
    main()
