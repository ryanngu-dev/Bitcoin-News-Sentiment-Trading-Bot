# BTC Kalshi Attention Lab

Research-first system for testing whether real-time Bitcoin internet attention
contains information that is **not already priced into Kalshi** BTC Up/Down
markets.

This is a research system with a **terminal CLI**. Cursor agents should call `btcpoly`, not invent trades.
Live Polymarket execution is **disabled by default**. Agents use `--mode paper` until you prove edge and arm live.

## What this repo is (Phase 2)

- SQLite storage, kill switch, UTC / point-in-time timestamps
- `btcpoly ingest` polls RSS/web and Agent Reach CLIs (YouTube, GitHub, …)
- Twitter/Reddit/XHS skip unless cookies/login are configured
- `btcpoly execute --mode paper` logs `NO_TRADE` until a model exists
- `btcpoly execute --mode live` is refused (same command later, after profitability)
- Uses Agent-Reach from GitHub to get real-time news from social media sources/news outlets

## Requirements

- Python 3.11+
- [Agent Reach](https://github.com/Panniantong/Agent-Reach) from GitHub (not the unrelated PyPI package), plus `yt-dlp` / `gh` / `bili` / `opencli` as available:

```bash
pip install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach doctor
```

Missing tools skip that channel; ingest still succeeds.

## Setup

```powershell
cd "C:\Users\ryann\Desktop\BTC Polymarket trading bot"
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
btcpoly doctor --json
btcpoly ingest --dry-run --json
btcpoly ingest --once --json
btcpoly execute --mode paper --json
pytest
```

Without activating the venv: `.venv\Scripts\btcpoly.exe ...`

## Commands

| Command | Purpose |
| ------- | ------- |
| `btcpoly doctor --json` | Config, DB, kill switch, Agent Reach health |
| `btcpoly ingest --once --json` | One poll; persist raw posts (agent default) |
| `btcpoly ingest --dry-run --json` | Preview channels; no writes |
| `btcpoly ingest --loop --interval 60` | Human daemon |
| `btcpoly status --json` | Counts, last ingest, kill switch, recent sources |
| `btcpoly feed` | Color-coded BTC mentions (YouTube red + video title) |
| `btcpoly execute --mode paper --json` | Paper decision (`NO_TRADE` until a model) |
| `btcpoly execute --mode live --json` | Refused until live engine + kill switch |

See [AGENTS.md](AGENTS.md) for the Cursor-agent contract.

## Kill switch

Live trading stays off unless **all** of these are true:

1. `execution.enabled` is true in config
2. `BTC_POLY_LIVE_TRADING=1`
3. `BTC_POLY_LIVE_TRADING_CONFIRM=I_UNDERSTAND`

`--mode live` then still errors until the CLOB engine is implemented. It will not silently paper-trade.

## Hypothesis

Does a sudden change in real-time Bitcoin attention/sentiment contain
predictive information about short-term BTC movement that is not already in
Polymarket prices?

The system is built to **prove or disprove** that. It does not assume it works.

## Point-in-time rule

Every record has `event_ts` (when it happened) and `ingested_at` (when we saw
it). At time T the model may only use rows with `event_ts <= T` **and**
`ingested_at <= T`.
