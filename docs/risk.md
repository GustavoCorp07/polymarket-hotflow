# Risk (aligned to `docs/MISSION-FULL.md` Parte 21–22, 36, 54)

The risk engine has **absolute VETO**. A score of 100 cannot override it.

## Limits (YAML `risk.*`)

- max order / market / category / correlated / total exposure
- daily and session loss, drawdown
- open orders, concurrent markets
- max slippage, spread, data age, latency
- cooldown and longer `cooldown_after_losses_ms`
- `no_martingale: true`

## Kill switches

Trip on stale critical data, auth fail, position mismatch, runaway rejects,
impossible PnL, excessive latency, abnormal slippage, duplicated orders,
drawdown exceeded, manual halt.

On trip: block new orders → cancel when safe → keep logs → require explicit
`KillSwitchBoard.reset(acknowledge=...)`.

## Portfolio vs risk (Parte 24)

The portfolio layer may skip or downsize (`CORRELATED_EXPOSURE`,
`PORTFOLIO_CONCENTRATION`, `PORTFOLIO_DOWNSIZED`) using explicit correlation
groups plus the same hard caps:

- `max_concurrent_markets` (open-position / concurrent-market cap)
- `max_category_exposure`
- `max_total_exposure`
- `max_correlated_exposure` (backstop on the summed correlated bucket)
- `max_order_notional`

Those proposals do **not** override VETO. After allocation, `RiskEngine.decide`
still runs. A score of 100 still cannot force a blocked order.

Optional book-depth consume (`microstructure.min_top_depth` /
`microstructure.max_impact`) stays **default-off**. `IMPACT_EXHAUSTED` on a
signal is an audit slice from the L2 walk, not a new veto.

Correlation is rule-based only (same underlying, same category+window, tag
overlap, YAML groups). No estimated residual. See `docs/strategy.md`.

`hotflow paper-soak --mixed` audits those skips/downsizes and group-scoped
regime scales on a deterministic 5m/15m + news book. It does not open LIVE
gates and cannot bypass VETO. `hotflow walk-forward` / `decay` on that JSON
group by **detected** labels; a 5-cycle fixture is flagged `too_small` /
`insufficient_sample`, not promoted as edge.

## Capital order (Parte 54)

1. Survive  
2. Preserve capital  
3. Execute correctly  
4. Find edge  
5. Scale  

Never maximize trade count.
