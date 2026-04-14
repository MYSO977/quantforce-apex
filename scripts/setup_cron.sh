#!/bin/bash
# QuantForce Apex — Setup cron jobs on .18 Brain
# Run once: bash scripts/setup_cron.sh

APEX=~/quantforce-apex
PYTHON=python3
LOG=~/quantforce-apex/logs

mkdir -p $LOG

# Remove existing QF cron entries
crontab -l 2>/dev/null | grep -v quantforce-apex | crontab -

# Add new entries
(crontab -l 2>/dev/null; cat << 'CRON'
# QuantForce Apex — Brain (.18) Cron Jobs
# Universe refresh at 09:00 ET (UTC-4 in summer = 13:00 UTC)
0 13 * * 1-5 cd ~/quantforce-apex && python3 -c "from universe.universe_manager import universe; universe.refresh_daily()" >> ~/quantforce-apex/logs/universe.log 2>&1

# Daily report at 16:00 ET (20:00 UTC summer)
0 20 * * 1-5 cd ~/quantforce-apex && python3 backtest/report_generator.py >> ~/quantforce-apex/logs/report.log 2>&1

# Reset daily PnL at 09:25 ET (13:25 UTC summer)
25 13 * * 1-5 cd ~/quantforce-apex && python3 -c "from core.account import AccountManager; a=AccountManager(); a.reset_daily_pnl()" >> ~/quantforce-apex/logs/account.log 2>&1

# Health check every 30 minutes during market hours
*/30 13-21 * * 1-5 bash ~/quantforce-apex/scripts/qf_check.sh >> ~/quantforce-apex/logs/health.log 2>&1
CRON
) | crontab -

echo "✓ Cron jobs installed:"
crontab -l | grep quantforce
