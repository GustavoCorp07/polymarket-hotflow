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
| 15 News engine | Not implemented (Grok cold path) |
| 16–17 Half-life + maker/taker | Config + EV chooser |
| 18–21 Exec / stale / latency / risk | Paper SM + clocks + VETO |
| 22–25 Sizing / velocity / portfolio / regime | Capped Kelly + scores + labels |
| 26–27 Backtest / anti-overfit | Event-driven replay (`hotflow backtest --fixture`); longer synthetic + redacted live CLOB book sample; train/val/OOS + walk-forward stub; refuses max-abs-PnL selection |
| 28 Modes | backtest / paper / shadow (`hotflow shadow --mock`) / live |
| 29–30 Tuner / experiments | Offline tuner (`hotflow tune`) writes suggestions only; refuses abs-PnL and production config writes |
| 31–36 Storage / obs / alerts | SQLite/Parquet + Prometheus/JSON |
| 37–42 Security / tests / clock / resolution | Hygiene tests + parser |
| 43–47 Watchlist / filter / micro / audit | Implemented |
| 48–51 Skills / watch routine | Scripts; no auto prod change |
| 52–53 Performance / decay | Not yet (needs trade history) |
| 54–64 Preservation / repo / CI / phases | Docs + paper acceptance path |
