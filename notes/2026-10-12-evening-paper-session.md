# Paper session notes — Oct 12, 2026 (~6:07–6:15pm PT)

Kalshi `KXBTC15M` paper only (`momentum_attn_v1`). Live not armed.

DB window: first tick **6:07pm PT** → last **6:14pm PT** (`2026-10-13 01:07–01:14 UTC`). Short run (~24 decision ticks).

## Results (this window only)

| Metric | Value |
| ------ | ----- |
| Paper buys | **1** (0W / 1L) |
| Win rate | **0%** |
| PnL (this buy) | **−$23.79** |
| NO_TRADE ticks | 23 |

### The one trade

| Field | Value |
| ----- | ----- |
| Time | ~6:10pm PT |
| Market | `KXBTC15M-26OCT122115-15` |
| Side | **BUY DOWN** |
| Model reason | `model_below_market` |
| Edge (approx.) | **−0.30** (model more bearish than Kalshi mid) |
| `sentiment_net_900` | **−0.27** (bearish lexicon; 7 mentions in 15m) |
| Outcome | **Loss** (−$23.79) |

### Why most ticks did not trade

| NO_TRADE reason | Count |
| --------------- | ----- |
| `entry_price_extreme` | 21 |
| `max_open_positions` | 2 |

Kalshi quotes were often **near 0 or 1** on the active window, so the model blocked entries even when edge looked large. Two ticks hit **`max_open_positions`** while an earlier open leg was still on the book.

## Book after session (all-time in DB, not reset)

| Metric | Value |
| ------ | ----- |
| Settled trades (lifetime) | **7** (3W / 4L) |
| Lifetime settled PnL | **−$29.09** |
| Cash | **~$70.91** (starting book still **$100** on paper ledger) |

This run did **not** wipe prior paper history — **`reset_on_run`** for `btcpoly run` was added in code after this window. Next `run` should reset to **$100** unless you pass **`--no-reset`**.

## Ingest / AI (same evening)

- RSS polling active; recent headlines skewed **bearish** (BTC sub-$82K, liquidations, etc.).
- Ingest metrics: **`ai_sentiment.scored: 0`** (`none_pending`) — Groq did not attach new `llm_v1` scores on those polls, so decisions leaned on **lexicon sentiment + BTC ret + Kalshi**, not credibility-weighted AI.

## Code landed this session (for the *next* run)

1. **`btcpoly run`** → auto **`reset_paper`** to starting cash (default on).
2. **Skip the Kalshi window you started in** — first eligible trades only after the next 15m contract.
3. **News gate** — need ≥1 mention in 15m and sentiment aligned with side (bullish for UP, bearish for DOWN).

## Takeaway

Short test: **one DOWN bet** on bearish news/model vs market, **lost**; market was mostly **untradeable** (`entry_price_extreme`). Before an overnight run: restart **`ingest` + `run`** on the new build, confirm startup banner shows **bankroll reset** and **wait for next window**, and keep ingest live so sentiment can clear the new gate.
