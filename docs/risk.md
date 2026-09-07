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

Correlation is rule-based only (same underlying, same category+window, tag
overlap, YAML groups). No estimated residual. See `docs/strategy.md`.

## Capital order (Parte 54)

1. Survive  
2. Preserve capital  
3. Execute correctly  
4. Find edge  
5. Scale  

Never maximize trade count.
