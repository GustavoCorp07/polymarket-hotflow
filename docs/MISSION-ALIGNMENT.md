# Mission alignment map

Source of truth: [`MISSION-FULL.md`](MISSION-FULL.md).

| Parts | Status in this pass |
| --- | --- |
| 1–2 Multi-agent / Grok | Process notes; single paper core |
| 3–4 Kimi council | Implemented, mockable, aliases |
| 5 Research | `research-current.md` |
| 6 Scanner | Gamma + public CLOB, dynamic |
| 7–9 HMS / opp / tiers | Implemented + resource plan |
| 10–11 Crypto + fair value | Paper crypto FV + official 30s/60s TWAP path + public RTDS cache subscriber |
| 12–14 Weather/sports/esports | PAPER weather Gamma fixtures + fixture forecasts; Sports WS cache (default-off) + NBA/Soccer; esports skip-heavy parser/fixtures (`hotflow esports-fixtures`), no invented live model |
| 15 News engine | PAPER: structured ingest → classify → source validation → impact features → existing FV/risk. Skip codes `NEWS_*`. Kimi `NEWS_CLASSIFIER` cold-path stub only. `live_ready` unchanged |
| 16–17 Half-life + maker/taker | Config + EV chooser |
| 18–21 Exec / stale / latency / risk | Paper SM + clocks + VETO |
| 22–25 Sizing / velocity / portfolio / regime | Capped Kelly + scores + labels + paper session ledger + portfolio allocator + **first-class regime detectors** (crypto/sports/weather rules; N/A if features missing; YAML enable/disable + group-cap overlays; risk VETO still absolute) |
| 26–27 Backtest / anti-overfit | Event-driven replay (`hotflow backtest --fixture`); longer synthetic + redacted live CLOB book sample; train/val/OOS; `hotflow walk-forward` on existing paper/backtest closes (expanding/rolling, caveated folds, labeled synthetic regime split or N/A) **or** mixed-soak JSON with **detected** detector labels on proposals; refuses max-abs-PnL; no auto-disable |
| 28 Modes | backtest / paper / shadow (`hotflow shadow --mock`, `hotflow shadow-soak`) / live |
| 29–30 Tuner / experiments | Offline tuner (`hotflow tune`) writes suggestions only; refuses abs-PnL and production config writes |
| 31–36 Storage / obs / alerts | SQLite ledger events/snapshots + JSON logs (request/signal/trade/risk/ledger, redaction) + Prometheus from the paper ledger (equity/PnL/drawdown/win-rate after closed trades) + `/metrics` `/health` `/ready` + alerts. PAPER default. No LIVE. |
| 37–42 Security / tests / clock / resolution | Hygiene + `hotflow live-gates` freeze (accept_* closed, no signing) + clock-skew + failure-soak |
| 43–47 Watchlist / filter / micro / audit | Watchlist + basic filter (book spread fallback). **Parte 45 L2 microstructure** on paper extras / feature snapshot / signal_quality: weighted imbalance, book slope, depth convexity, liquidity gaps, VWAP-to-depth impact, rule-based spread regime (`vs=config` or recent median; `invented:false` when history missing). OFI / trade-imbalance / cancel / replenishment N/A (no L3 or signed print stream). Quote/trade intensity only when timestamped fixture events are passed (backtest). Optional depth/impact risk consume default-off. Parte 46 signal JSON + skip reasons unchanged |
| 48–51 Skills / watch routine | Scripts; no auto prod change |
| 52–53 Performance / decay | PAPER: `hotflow performance` / `hotflow decay` from ledger/backtest JSON only; `hotflow paper-soak --long` labeled ≥50 closes with MARKs; `hotflow paper-soak --mixed` fixture 5m/15m+news allocator/regime audit; walk-forward/decay on mixed JSON uses **detected** labels (tiny-n caveated, not invented); sample-size caveats; abs-PnL ranking refused; decay is suggestion-only (no auto-disable). Readiness gets a non-blocking INFO section |
| 54–64 Preservation / repo / CI / phases | Docs + soaks + LIVE-gate freeze + `hotflow readiness` rollup (`live_ready=false`); LIVE still gated |
