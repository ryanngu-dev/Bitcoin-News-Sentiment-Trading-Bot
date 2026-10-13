# Paper session notes — Aug 26, 2026 (~5pm PT → ~12am Aug 27)

Sentiment-aware `momentum_attn_v1` paper run on Kalshi `KXBTC15M` only. Live not armed.

Window from DB: first buy **5:26pm PT** → last **11:45pm PT** (Aug 26).

## Results

| Metric | Value |
| ------ | ----- |
| Settled trades | **27** (15W / 12L) |
| Win rate | **55.6%** |
| Settled PnL | **+$69.90** |
| Sentiment on trades | **27/27** (mean `sentiment_net` ≈ +0.24) |

### By side

| Side | n | Win rate | PnL |
| ---- | - | -------- | --- |
| UP | 16 | 50.0% | +$15.41 |
| DOWN | 11 | **63.6%** | **+$54.49** |

### Sentiment alignment

| | n | Win rate |
| - | - | -------- |
| Side agrees with sentiment sign | 14 | **64.3%** |
| Side disagrees | 6 | 50.0% |

## Edge accuracy (this session only)

`edge = model P(UP) − Kalshi P(UP)`. Larger \|edge\| ≠ more accurate here.

### By \|edge\| bucket

| \|edge\| at entry | n | Win rate | PnL | Mean \|edge\| |
| ----------------- | - | -------- | --- | ------------- |
| 0.04–0.06 | 6 | **83.3%** | **+$87.42** | 0.052 |
| 0.06–0.10 | 10 | 40.0% | −$57.56 | 0.074 |
| 0.10–0.15 | 6 | 66.7% | +$27.90 | 0.123 |
| 0.15+ | 5 | 40.0% | +$12.14 | 0.181 |

### By \|edge\| tercile

| Tercile | n | Win rate | PnL | Mean \|edge\| |
| ------- | - | -------- | --- | ------------- |
| Low | 9 | **88.9%** | **+$148.77** | 0.056 |
| Mid | 9 | 22.2% | −$123.40 | 0.085 |
| High | 9 | 55.6% | +$44.53 | 0.159 |

Mean \|edge\|: wins **0.090** · losses **0.112**. Soft edges carried the session; mid-band \|edge\| was the money loser.

## Takeaway

This window was profitable at **~56% WR / +$70**. Claimed edge size was **not** well calibrated — the lowest \|edge\| trades did best. Still paper-only; small sample (n=27).
