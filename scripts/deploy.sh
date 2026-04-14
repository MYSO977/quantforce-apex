#!/bin/bash
# QuantForce Apex — Multi-node deploy
# Usage: bash scripts/deploy.sh [node]
# node: all | brain | exec | compute   (default: all)

TARGET=${1:-all}
REPO=~/quantforce-apex
RSYNC_OPTS="-av --exclude=__pycache__ --exclude=*.pyc --exclude=.git --exclude=config/telegram.yaml"

deploy_brain() {
    echo "→ Deploying brain_18 (local)"
    # brain_18 IS .18, so just ensure path is correct
    echo "  brain_18 runs locally on this node — no rsync needed"
}

deploy_exec() {
    echo "→ Deploying exec_11 (.11 Dell)"
    ssh heng@192.168.0.11 "mkdir -p ~/quantforce-apex"
    rsync $RSYNC_OPTS \
        $REPO/core/ heng@192.168.0.11:~/quantforce-apex/core/
    rsync $RSYNC_OPTS \
        $REPO/nodes/exec_11/ heng@192.168.0.11:~/quantforce-apex/
    rsync $RSYNC_OPTS \
        $REPO/config/risk_config.yaml heng@192.168.0.11:~/quantforce-apex/config/
    echo "  Restarting services on .11..."
    ssh heng@192.168.0.11 "
        sudo systemctl restart ib_executor_v2 2>/dev/null || true
        sudo systemctl restart market_feed     2>/dev/null || true
        echo '  .11 services restarted'
    "
}

deploy_compute() {
    echo "→ Deploying compute_143 (.143 Lenovo)"
    ssh heng@192.168.0.143 "mkdir -p ~/quantforce-apex"
    rsync $RSYNC_OPTS \
        $REPO/core/ heng@192.168.0.143:~/quantforce-apex/core/
    rsync $RSYNC_OPTS \
        $REPO/nodes/compute_143/ heng@192.168.0.143:~/quantforce-apex/
    rsync $RSYNC_OPTS \
        $REPO/config/risk_config.yaml heng@192.168.0.143:~/quantforce-apex/config/
    echo "  Restarting services on .143..."
    ssh heng@192.168.0.143 "
        sudo systemctl restart tech_scanner  2>/dev/null || true
        sudo systemctl restart news_scanner  2>/dev/null || true
        echo '  .143 services restarted'
    "
}

case $TARGET in
    all)
        deploy_brain
        deploy_exec
        deploy_compute
        ;;
    brain)   deploy_brain   ;;
    exec)    deploy_exec    ;;
    compute) deploy_compute ;;
    *)
        echo "Usage: deploy.sh [all|brain|exec|compute]"
        exit 1
        ;;
esac

echo ""
echo "✓ Deploy complete. Run: bash scripts/qf_check.sh"
