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

## Capital order (Parte 54)

1. Survive  
2. Preserve capital  
3. Execute correctly  
4. Find edge  
5. Scale  

Never maximize trade count.
