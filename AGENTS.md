# Agent contract

`btcpoly` is the system of record. Cursor agents must run these commands — they must not invent trades in chat or enable live trading.

**Exchange: Kalshi** (USA-accessible). Polymarket is retired in this project. Short BTC up/down series is `KXBTC15M` (15m only — Kalshi has no 5m).

Use `--json` (group-level `btcpoly --json ...` or per-command `--json`). No prompts. Do not pass `--loop` or `run` (those are human daemons).

## Commands

```powershell
cd "C:\Users\ryann\Desktop\BTC Polymarket trading bot"
.venv\Scripts\btcpoly.exe doctor --json
.venv\Scripts\btcpoly.exe ingest --once --json
.venv\Scripts\btcpoly.exe status --json
.venv\Scripts\btcpoly.exe execute --mode paper --duration 15 --json
.venv\Scripts\btcpoly.exe settle --json
.venv\Scripts\btcpoly.exe feed
```

| Command | Purpose |
| ------- | ------- |
| `btcpoly ingest --once --json` | One poll; persist new raw posts; skip missing CLIs/cookies |
| `btcpoly ingest --dry-run --json` | Preview channels; no network writes |
| `btcpoly execute --mode paper --duration 15 --json` | Paper decision on Kalshi (`momentum_attn_v1` + bankroll). |
| `btcpoly settle --json` | Resolve closed Kalshi windows; net PnL after fees/slippage |
| `btcpoly reset-paper --yes` | Wipe paper trades → cash back to **$100** |
| `btcpoly run --duration 15` | **Human only** — Kalshi loop; boxed UP/DOWN and WIN/LOSE |
| `btcpoly execute --mode live --json` | Forbidden until the user arms live **and** the live engine exists |

## Exit codes

- `0` ok
- `1` usage / live refused
- `2` partial ingest (some channels failed)
- `3` hard failure / live engine not implemented

## Rules

1. **`--mode paper` only** until the user explicitly says paper results are validated and live is armed.
2. Never set `BTC_POLY_LIVE_TRADING=1` or `BTC_POLY_LIVE_TRADING_CONFIRM`.
3. Never rewrite Agent Reach. Ingest wraps its upstream CLIs.
4. Twitter/Reddit stay skipped until cookies/login exist; that is not a crash.
5. Do not place Kalshi orders by any other path (browser, SDK, raw curl) until live is armed.

## After ingest

Read `inserted`, `duplicates`, `skipped`, and `errors` from JSON. Then `execute --mode paper --json`. Expect `bankroll.cash` (~$100 flat after `reset-paper --yes`), `features.attn_z_900`, and `features.sentiment_net_900` (post bullish/bearish consensus). After a window ends, run `settle --json` and check `paper_stats` / `pnl_total`.
