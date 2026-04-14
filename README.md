# QuantForce Apex

Multi-asset plugin quantitative trading system — 5-node LAN cluster

## Architecture
## Node Architecture

| Node | IP | Role | Services |
|---|---|---|---|
| Acer (Brain) | 192.168.0.18 | Orchestration | signal_fusion, quant_api, PostgreSQL |
| Dell (Exec) | 192.168.0.11 | Execution | ib_executor_v2, IB Gateway, market_feed |
| Lenovo (Compute) | 192.168.0.143 | Compute | tech_scanner, news_scanner |
| Sentry | 192.168.0.101 | Monitoring | Grafana, watchdog |
| Courier | 192.168.0.102 | Notify | Telegram bot |

## Signal Pipeline
## Account Constraints

- **Account**: IB Cash DUP375010 | $1,200 | Paper → Live
- **Risk per trade**: 2.5% (~$30) | ATR-based position sizing
- **Daily loss limit**: 2% circuit breaker
- **T+1 settlement**: settled_balance tracked separately

## Phase Activation

| Phase | Account | Active Strategies |
|---|---|---|
| 0 (paper) | $1,200 | STK-01/02/03 + ETF-01 (all shadow=true) |
| 1 (live) | $1,200 | STK-01/02 shadow=false after 5-day validation |
| 2 | ≥$2,000 | + OPT-01 CallBuy |
| 3 | ≥$3,000 | + FX-01 + FUT-01 |
| 4 | ≥$5,000 | + CRY-01 |

## Quick Commands

```bash
# Health check
bash scripts/qf_check.sh

# Deploy to all nodes
bash scripts/deploy.sh all

# Run signal fusion (brain .18)
cd ~/quantforce-apex && python3 nodes/brain_18/signal_fusion.py
```
