"""Paper ledger vs caller-supplied quantities. Never invents a venue view."""

from __future__ import annotations


def position_mismatches(
    ledger_qty: dict[str, float],
    external_qty: dict[str, float],
    *,
    tol: float = 1e-9,
) -> list[str]:
    """Return token ids that differ. `external_qty` must be supplied by the caller."""
    tokens = set(ledger_qty) | set(external_qty)
    bad: list[str] = []
    for token in sorted(tokens):
        local = float(ledger_qty.get(token) or 0.0)
        remote = float(external_qty.get(token) or 0.0)
        if abs(local - remote) > tol:
            bad.append(token)
    return bad
