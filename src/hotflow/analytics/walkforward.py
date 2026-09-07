"""Walk-forward and optional regime split on existing closed trades.

Index-based folds only. Does not invent closes. Not purged CV / Monte Carlo.
"""

from __future__ import annotations

from typing import Any

from hotflow.analytics.performance import sample_caveat
from hotflow.analytics.stats import max_drawdown, mean, refuse_max_abs_pnl_selection
from hotflow.analytics.trades import NormalizedTrade, TradeExtract, extract_trades
from hotflow.monitoring.redact import redact

DEFAULT_TRAIN = 20
DEFAULT_TEST = 10
DEFAULT_STEP = 10


def fold_metrics(trades: list[NormalizedTrade]) -> dict[str, Any]:
    pnls = [row.pnl for row in trades]
    fees = [row.fee for row in trades if row.fee is not None]
    start = 0.0
    equity = [start]
    running = start
    for pnl in pnls:
        running += pnl
        equity.append(running)
    n = len(pnls)
    return {
        "trade_count": n,
        "expectancy": mean(pnls),
        "win_rate": (sum(1 for item in pnls if item > 0) / n) if n else None,
        "max_drawdown": max_drawdown(equity) if n else None,
        "fees": sum(fees) if fees else None,
        "net_pnl": sum(pnls) if pnls else None,
        "abs_pnl": sum(pnls) if pnls else None,
        "abs_pnl_not_a_selection_metric": True,
        "sample": sample_caveat(n),
    }


def _windows(n: int, *, train: int, test: int, step: int, expanding: bool) -> list[dict[str, int]]:
    if n <= 0 or train < 1 or test < 1 or step < 1:
        return []
    out: list[dict[str, int]] = []
    train_end = train
    fold = 0
    while train_end + test <= n:
        train_start = 0 if expanding else max(0, train_end - train)
        out.append(
            {
                "fold": fold,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": train_end,
                "test_end": train_end + test,
            }
        )
        fold += 1
        train_end += step
    return out


def walk_forward_folds(
    trades: list[NormalizedTrade],
    *,
    train_size: int = DEFAULT_TRAIN,
    test_size: int = DEFAULT_TEST,
    step: int = DEFAULT_STEP,
    expanding: bool = True,
) -> list[dict[str, Any]]:
    specs = _windows(len(trades), train=train_size, test=test_size, step=step, expanding=expanding)
    folds: list[dict[str, Any]] = []
    for spec in specs:
        train = fold_metrics(trades[spec["train_start"] : spec["train_end"]])
        test = fold_metrics(trades[spec["test_start"] : spec["test_end"]])
        folds.append(
            {
                **spec,
                "scheme": "expanding" if expanding else "rolling",
                "train": train,
                "holdout": test,
                "strong_conclusion": bool(
                    train["sample"]["strong_conclusion"] and test["sample"]["strong_conclusion"]
                ),
            }
        )
    return folds


def regime_split(trades: list[NormalizedTrade]) -> dict[str, Any]:
    labeled = [row for row in trades if row.regime]
    if not labeled:
        return {
            "status": "N/A",
            "detail": "no regime labels on closes; not invented",
            "regimes": {},
        }
    groups: dict[str, list[NormalizedTrade]] = {}
    for row in labeled:
        key = str(row.regime)
        groups.setdefault(key, []).append(row)
    return {
        "status": "labeled_synthetic",
        "detail": "Regimes taken from fixture/event labels only.",
        "n_labeled": len(labeled),
        "n_unlabeled": len(trades) - len(labeled),
        "regimes": {name: fold_metrics(rows) for name, rows in groups.items()},
    }


def build_walk_forward(
    report: dict[str, Any] | None,
    *,
    source: str | None = None,
    train_size: int = DEFAULT_TRAIN,
    test_size: int = DEFAULT_TEST,
    step: int = DEFAULT_STEP,
    expanding: bool = True,
    rank_metric: str | None = None,
) -> dict[str, Any]:
    blocked = refuse_max_abs_pnl_selection(rank_metric) if rank_metric else None
    extract: TradeExtract = extract_trades(report)
    folds = walk_forward_folds(
        extract.trades,
        train_size=train_size,
        test_size=test_size,
        step=step,
        expanding=expanding,
    )
    payload: dict[str, Any] = {
        "mode": "paper",
        "live": False,
        "live_ready": False,
        "source": source,
        "source_kind": extract.source_kind,
        "n_closes": len(extract.trades),
        "scheme": "expanding" if expanding else "rolling",
        "train_size": train_size,
        "test_size": test_size,
        "step": step,
        "folds": folds,
        "fold_count": len(folds),
        "regime_split": regime_split(extract.trades),
        "sample": sample_caveat(len(extract.trades)),
        "auto_disable": False,
        "suggestion_only": True,
        "production_change": False,
        "abs_pnl_not_a_selection_metric": True,
        "note": (
            "Walk-forward uses only existing closed trades. Tiny holdouts are caveated. "
            "Not a LIVE promotion and not purged CV."
        ),
    }
    if blocked:
        payload["refused"] = True
        payload["reason"] = blocked.get("reason")
        payload["selection"] = blocked
    cleaned = redact(payload)
    return cleaned if isinstance(cleaned, dict) else payload


def format_walk_forward(report: dict[str, Any]) -> str:
    lines = [
        f"n_closes={report.get('n_closes')} folds={report.get('fold_count')} "
        f"scheme={report.get('scheme')} auto_disable=False live_ready={report.get('live_ready')}"
    ]
    if report.get("refused"):
        lines.append(f"  refused={report.get('reason')}")
    for fold in report.get("folds") or []:
        hold = fold.get("holdout") or {}
        sample = hold.get("sample") or {}
        lines.append(
            f"  fold={fold.get('fold')} holdout_n={hold.get('trade_count')} "
            f"expectancy={hold.get('expectancy')} caveat={sample.get('caveat')}"
        )
    regime = report.get("regime_split") or {}
    lines.append(f"  regime={regime.get('status')}")
    return "\n".join(lines)
