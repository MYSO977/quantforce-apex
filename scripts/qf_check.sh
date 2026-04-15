#!/bin/bash
# QuantForce Apex — Health Check
# Usage: bash ~/quantforce-apex/scripts/qf_check.sh

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  QuantForce Apex — Health Check"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── PostgreSQL ────────────────────────────────────────────────────
echo -e "\n[PostgreSQL @ 192.168.0.18]"
if PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce -c "SELECT 1" -q 2>/dev/null | grep -q 1; then
    ok "Connected to quantforce DB"
    # Check key tables
    for tbl in signals_raw market_events executions universe_whitelist account_state; do
        COUNT=$(PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce -tAc \
            "SELECT COUNT(*) FROM $tbl" 2>/dev/null || echo "ERR")
        if [ "$COUNT" = "ERR" ]; then
            fail "Table $tbl — not found"
        else
            ok "Table $tbl: $COUNT rows"
        fi
    done
else
    fail "Cannot connect to PostgreSQL"
fi

# ── Systemd services on each node ────────────────────────────────
echo -e "\n[Services @ .18 Brain]"
for svc in signal_fusion quant_api; do
    if systemctl is-active --quiet $svc 2>/dev/null; then
        ok "$svc: active"
    else
        warn "$svc: inactive / not found"
    fi
done

echo -e "\n[Services @ .11 Dell — via SSH]"
for svc in ib_executor_v2 market_feed ibc; do
    STATUS=$(ssh -o ConnectTimeout=3 heng@192.168.0.11 \
        "systemctl is-active $svc 2>/dev/null" 2>/dev/null || echo "unreachable")
    if [ "$STATUS" = "active" ]; then
        ok "$svc: active"
    elif [ "$STATUS" = "unreachable" ]; then
        warn ".11 unreachable"
        break
    else
        warn "$svc: $STATUS"
    fi
done

echo -e "\n[Services @ .143 Compute — via SSH]"
for svc in tech_scanner news_scanner; do
    STATUS=$(ssh -o ConnectTimeout=3 heng@192.168.0.143 \
        "systemctl is-active $svc 2>/dev/null" 2>/dev/null || echo "unreachable")
    if [ "$STATUS" = "active" ]; then
        ok "$svc: active"
    elif [ "$STATUS" = "unreachable" ]; then
        warn ".143 unreachable"
        break
    else
        warn "$svc: $STATUS"
    fi
done

# ── ZMQ port 5558 ─────────────────────────────────────────────────
echo -e "\n[ZMQ]"
if ss -tlnp 2>/dev/null | grep -q 5558 || \
   ssh -o ConnectTimeout=3 heng@192.168.0.11 \
       "ss -tlnp 2>/dev/null | grep -q 5558" 2>/dev/null; then
    ok "ZMQ port 5558 listening"
else
    warn "ZMQ port 5558 not detected"
fi

# ── IB Gateway ───────────────────────────────────────────────────
echo -e "\n[IB Gateway @ .11:4002]"
if nc -z -w3 192.168.0.11 4002 2>/dev/null; then
    ok "IB Gateway port 4002 reachable"
else
    fail "IB Gateway port 4002 not reachable"
fi

# ── Recent signals ────────────────────────────────────────────────
echo -e "\n[Recent Activity (last 1h)]"
RECENT=$(PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce -tAc \
    "SELECT COUNT(*) FROM signals_raw WHERE created_at > NOW()-INTERVAL '1 hour'" \
    2>/dev/null || echo "0")
FILLED=$(PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce -tAc \
    "SELECT COUNT(*) FROM executions WHERE filled_at > NOW()-INTERVAL '24 hours'" \
    2>/dev/null || echo "0")
ok "Signals last 1h: $RECENT"
ok "Executions last 24h: $FILLED"

# ── Universe ──────────────────────────────────────────────────────
echo -e "\n[Universe]"
UNIV=$(PGPASSWORD=newpassword123 psql -h 192.168.0.18 -U heng -d quantforce -tAc \
    "SELECT COUNT(*) FROM universe_whitelist WHERE active=true" 2>/dev/null || echo "0")
ok "Active universe symbols: $UNIV"

echo -e "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Check complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
