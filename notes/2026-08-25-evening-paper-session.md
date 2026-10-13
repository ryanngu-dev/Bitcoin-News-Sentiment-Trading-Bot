# Paper session notes — Aug 25–26, 2026 (evening)

## What happened

Ran `btcpoly` paper trading on Kalshi `KXBTC15M` from about **8:00pm PT (Aug 25)** through **1:16am PT (Aug 26)** (~5h 15m).

Starting cash was **$100**. By 1:16am the book looked roughly:

| Metric | Value |
| ------ | ----- |
| Settled PnL | **−$41.89** |
| Settled trades | 22 (10 wins / 12 losses ≈ **45%** win rate) |
| Open position | 1 (~$14.60 cost still locked) |
| Cash left | ~**$43.50** |
| Equity (cash + open cost) | ~**$58** |

User read of the night: **down about $53** on cash (100 → ~47ish depending on when they looked) — **not profitable**.

Buys during that window (from DB, first BUY ~8:05pm PT → last ~1:15am): **23** paper buys (10 UP / 13 DOWN). Sentiment/consensus feature was **not** live for this run; model was still **momentum + mention volume (`attn_z`) + Kalshi odds** only.

## Context

- Paper only; live trading not armed.
- Exchange: Kalshi (USA). Series: `KXBTC15M` only.
- Ingest: RSS mostly useful; Twitter/Reddit/etc. often skipped (cookies / CLIs missing).
- Slippage modeling: 50 bps on entries.

## Takeaways

1. Overnight paper run **lost money** under the pre-sentiment model — edge is not validated yet.
2. Win rate under 50% with fees/slippage makes recovery hard on short binary windows.
3. Next experiment: re-run with **post consensus (`sentiment_net_*`)** enabled and compare a fresh `$100` paper book (`reset-paper --yes` when ready to start a clean A/B).
4. Do not arm live until a later session shows sustained positive paper PnL after costs.

## Follow-ups

- [ ] Restart `run` so trade banners include session elapsed / trades / win rate (only on trade, inside `====`).
- [ ] Clean paper book when starting the sentiment-aware comparison session.
- [ ] Watch whether consensus actually changes decisions vs volume-only `attn_z`.
