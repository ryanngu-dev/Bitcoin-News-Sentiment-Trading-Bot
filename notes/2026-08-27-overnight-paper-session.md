# Paper session notes — Aug 27–28, 2026 (evening → shutdown)

PC shut down mid-run; notes reconstructed from `data/btcpoly.db` (no live chat log of the crash).

## Window

| | |
| - | - |
| First paper buy | **7:21pm PT Aug 27** (`2026-08-28 02:21 UTC`) |
| Last paper buy | **1:00am PT Aug 28** (`2026-08-28 08:00 UTC`) |
| Exchange | Kalshi `KXBTC15M` paper only |
| Model | `momentum_attn_v1` |

## Results (this overnight only)

| Metric | Value |
| ------ | ----- |
| Settled trades | **24** (7W / 17L) |
| Win rate | **29.2%** |
| Settled PnL | **−$96.11** |
| Cash after (book) | **~$5.53** (start $100; all-time settled PnL ≈ −$94.47 on 77 trades) |
| Open positions | 0 |

### By side

| Side | n | Win rate | PnL |
| ---- | - | -------- | --- |
| UP | 13 | 30.8% | −$77.91 |
| DOWN | 11 | 27.3% | −$18.21 |

### By \|edge\| bucket

| \|edge\| | n | Win rate | PnL |
| -------- | - | -------- | --- |
| 0.04–0.06 | 7 | 28.6% | −$77.09 |
| 0.06–0.10 | 7 | 42.9% | +$32.52 |
| 0.10–0.15 | 6 | 16.7% | −$46.73 |
| 0.15+ | 4 | 25.0% | −$4.81 |

Unlike the earlier ~5pm Aug 26 session (soft edges won), this overnight the **softest** bucket also lost hard — sample still small, but the book was bleeding steadily as cash shrank (later bets smaller).

## AI / Groq

- DB has **105** `llm_v1` AI score rows (Groq was running at times).
- **None** of these 24 overnight trades stored `ai_sentiment_*` on the prediction snapshot (`ai_n=0` on all).
- Likely causes: period of **403/model failures** before the `openai/gpt-oss-20b` fix, and/or `run` process started before AI was wired into execute features.
- So this loss session is mostly **lexicon + attn_z + BTC ret vs Kalshi**, not the credibility-weighted Groq path.

## Takeaways

1. Overnight paper was **not profitable** (~29% WR, ~−$96 on the window).
2. Bankroll is nearly flatlined (~$5.50) — use `btcpoly reset-paper --yes` before a clean next experiment if you want a fresh $100 book.
3. Re-confirm Groq is scoring **and** showing up on trade Why (`AI lean` / `cred=`) after restart.
4. Still paper-only; do not arm live.

## Follow-ups

- [ ] Restart with current code + working Groq model; verify AI lean appears on new trades.
- [ ] Optional: `reset-paper --yes` for a clean A/B with broad RSS + AI credibility.
- [ ] Prefer VPS/tmux next time so a PC shutdown doesn’t kill the loop mid-session.
