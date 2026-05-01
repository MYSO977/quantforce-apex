# QuantForce Apex
Multi-asset plugin quantitative trading system — 5-node LAN cluster

## Current Status (2026-04-22)
- ✅ Full pipeline live: market_feed → market_events → signal_fusion → Telegram
- ✅ 26 candidates scanning (Russell 2000 + ETF universe)
- ✅ 4 strategies loaded (STK-01/02/03 + ETF-01, all shadow=true)
- ✅ IB paper account DUP375010 connected (port 4002)
- ⏳ Awaiting first APPROVED signal

## Signal Pipeline
## Node Architecture
| Node | IP | Role | Services |
|---|---|---|---|
| Acer (Brain) | 192.168.0.18 | Orchestration | signal_fusion_notify, PostgreSQL |
| Dell (Exec) | 192.168.0.11 | Execution | market_feed, IB Gateway |
| Lenovo (Compute) | 192.168.0.143 | Compute | tech_scanner, news_scanner |
| Sentry | 192.168.0.101 | Monitoring | Grafana |
| Courier | 192.168.0.102 | Notify | Telegram bot |

## Account Constraints
- **Account**: IB Cash DUP375010 | $1,200 | Paper → Live
- **Risk per trade**: 2.5% (~$30) | ATR-based position sizing
- **Daily loss limit**: 2% circuit breaker
- **T+1 settlement**: settled_balance tracked separately

## Strategy Status
| ID | Name | Status | Condition |
|---|---|---|---|
| STK-01 | MomentumSwing | shadow | RVOL≥2.0 + 20日高点突破 |
| STK-02 | NewsBreakout | shadow | Groq≥7.5 + gap≥3% |
| STK-03 | OpeningRangeBreakout | shadow | 15min ORB + 成交量确认 |
| ETF-01 | SectorRotation | shadow | 4周相对强度排名 |

## Phase Activation
| Phase | Account | Active Strategies |
|---|---|---|
| 0 (paper) | $1,200 | STK-01/02/03 + ETF-01 (shadow=true) |
| 1 (live) | $1,200 | STK-01/02 shadow=false after 5-day validation |
| 2 | ≥$2,000 | + OPT-01 CallBuy |
| 3 | ≥$3,000 | + FX-01 + FUT-01 |
| 4 | ≥$5,000 | + CRY-01 |

## Quick Commands
```bash
# Health check
bash scripts/qf_check.sh

# Signal fusion log
journalctl -u signal_fusion_notify -f

# Today's signals
PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce \
  -c "SELECT symbol, direction, status, created_at FROM signals_raw ORDER BY id DESC LIMIT 10;"

# Market events (last 10 min)
PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce \
  -c "SELECT symbol, COUNT(*), MAX(rvol) FROM market_events WHERE ts > now()-interval '10 min' GROUP BY symbol ORDER BY 3 DESC LIMIT 10;"
```
