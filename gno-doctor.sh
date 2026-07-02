#!/bin/bash
# Gno.land Node Doctor - Test13 Health Check (Full)
# Bare-metal / config-level diagnostics for gnoland validator nodes.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BLUE}${BOLD}"
echo "====================================================="
echo "   GNO.LAND NODE DOCTOR - Test13 Health Check"
echo "====================================================="
echo -e "${NC}"

SCORE=0
TOTAL_CHECKS=12

DATA_DIR="$HOME/gnoland-data"
CONFIG_TOML="$DATA_DIR/config/config.toml"
SERVICE_FILE="/etc/systemd/system/gnoland.service"
KEY_FILE="$DATA_DIR/secrets/priv_validator_key.json"
GENESIS_FILE="$DATA_DIR/config/genesis.json"

# --- Auto-detect RPC port from config.toml ---
RPC_PORT="26657"
RAW_LADDR_LINE=""
if [ -f "$CONFIG_TOML" ]; then
    RAW_LADDR_LINE=$(awk '/^\[rpc\]/{f=1; next} /^\[/{f=0} f && $0 ~ /^[[:space:]]*laddr[[:space:]]*=[[:space:]]*"tcp:\/\//{print; exit}' "$CONFIG_TOML")
    DETECTED_PORT=$(echo "$RAW_LADDR_LINE" | grep -oE ':[0-9]+"' | tr -dc '0-9')
    [ -n "$DETECTED_PORT" ] && RPC_PORT="$DETECTED_PORT"
fi
GNO_RPC="http://localhost:${RPC_PORT}"

# --- Auto-detect P2P port from config.toml (for check 11) ---
P2P_PORT=""
if [ -f "$CONFIG_TOML" ]; then
    RAW_P2P_LINE=$(awk '/^\[p2p\]/{f=1; next} /^\[/{f=0} f && $0 ~ /^[[:space:]]*laddr[[:space:]]*=[[:space:]]*"tcp:\/\//{print; exit}' "$CONFIG_TOML")
    P2P_PORT=$(echo "$RAW_P2P_LINE" | grep -oE ':[0-9]+"' | tr -dc '0-9')
fi

echo -e "${YELLOW}[debug] config: $CONFIG_TOML | rpc laddr: '${RAW_LADDR_LINE:-NOT FOUND}' -> port $RPC_PORT | p2p port: ${P2P_PORT:-NOT FOUND}${NC}"
echo ""

# 1. Bare Metal Check
echo -n -e "1. Server Architecture: "
VIRT=$(systemd-detect-virt 2>/dev/null | head -n 1)
if [ -z "$VIRT" ] || [ "$VIRT" == "none" ]; then
    echo -e "${GREEN}PASS (Bare Metal Detected)${NC}"
    SCORE=$((SCORE+1))
else
    echo -e "${YELLOW}WARN (Virtual Machine Detected: $VIRT. Bare Metal is recommended for optimal GnoVM performance.)${NC}"
fi

# 2. Log Level Check
echo -n -e "2. Gnoland Log Level Optimization: "
if [ -f "$SERVICE_FILE" ]; then
    if grep -q -- "--log-level info" "$SERVICE_FILE"; then
        echo -e "${GREEN}PASS (--log-level info is active. Disk is safe.)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (Detected DEBUG or default log level! Disk will fill up rapidly. Append '--log-level info' to your service file.)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (gnoland.service not found at $SERVICE_FILE)${NC}"
fi

# 3. Prune Strategy Check
echo -n -e "3. Config Pruning Strategy: "
if [ -f "$CONFIG_TOML" ]; then
    if grep -q 'prune_strategy = "syncable"' "$CONFIG_TOML"; then
        echo -e "${GREEN}PASS (Prune strategy is syncable)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (Prune strategy is not syncable. Storage footprint will grow uncontrollably.)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (config.toml not found at $CONFIG_TOML)${NC}"
fi

# 4. Open File Limits
echo -n -e "4. Open File Limit (systemd LimitNOFILE): "
if command -v systemctl >/dev/null 2>&1 && [ -f "$SERVICE_FILE" ]; then
    SVC_LIMIT=$(systemctl show gnoland -p LimitNOFILE 2>/dev/null | cut -d= -f2)
    if [ -n "$SVC_LIMIT" ] && [ "$SVC_LIMIT" != "infinity" ] && [ "$SVC_LIMIT" -ge 65535 ] 2>/dev/null; then
        echo -e "${GREEN}PASS (LimitNOFILE=$SVC_LIMIT)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (LimitNOFILE=$SVC_LIMIT - Should be at least 65535)${NC}"
    fi
else
    ULIMIT=$(ulimit -n)
    if [ "$ULIMIT" -ge 65535 ]; then
        echo -e "${GREEN}PASS (shell ulimit: $ULIMIT)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${YELLOW}WARN (systemctl unavailable, shell ulimit=$ULIMIT)${NC}"
    fi
fi

# 5. RPC Sync Status
echo -n -e "5. RPC Sync Status ($GNO_RPC): "
SVC_ACTIVE="unknown"
command -v systemctl >/dev/null 2>&1 && SVC_ACTIVE=$(systemctl is-active gnoland 2>/dev/null)
SYNC_RES=$(curl -s --max-time 3 "$GNO_RPC/status")
if [ -n "$SYNC_RES" ]; then
    IS_SYNCING=$(echo "$SYNC_RES" | grep -oE '"catching_up":[[:space:]]*true')
    LOCAL_HEIGHT=$(echo "$SYNC_RES" | grep -oE '"latest_block_height":[[:space:]]*"[0-9]+"' | grep -oE '[0-9]+')
    if [ -z "$IS_SYNCING" ]; then
        echo -e "${GREEN}PASS (Fully Synced | Height: ${LOCAL_HEIGHT:-N/A})${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${YELLOW}WARN (Still catching up | Height: ${LOCAL_HEIGHT:-N/A})${NC}"
    fi
else
    if [ "$SVC_ACTIVE" != "active" ]; then
        echo -e "${RED}FAIL (gnoland.service is '$SVC_ACTIVE'. Start it: sudo systemctl start gnoland)${NC}"
    else
        echo -e "${RED}FAIL (Running but RPC unreachable at $GNO_RPC - check the debug line above)${NC}"
    fi
fi

# 6. Peer Count
echo -n -e "6. Peer Count (min 5 recommended): "
PEER_RES=$(curl -s --max-time 3 "$GNO_RPC/net_info")
PEER_COUNT=$(echo "$PEER_RES" | grep -oE '"n_peers":[[:space:]]*"?[0-9]+"?' | grep -oE '[0-9]+')
if [ -n "$PEER_COUNT" ] && [ "$PEER_COUNT" -ge 5 ]; then
    echo -e "${GREEN}PASS (Peers: $PEER_COUNT)${NC}"
    SCORE=$((SCORE+1))
elif [ -n "$PEER_COUNT" ]; then
    echo -e "${YELLOW}WARN (Only $PEER_COUNT peers - low connectivity may affect sync/gossip)${NC}"
else
    echo -e "${RED}FAIL (Could not read peer count - is RPC reachable?)${NC}"
fi

# 7. Time Sync (NTP)
echo -n -e "7. System Time Sync (NTP): "
if command -v timedatectl >/dev/null 2>&1; then
    NTP_STATUS=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
    if [ "$NTP_STATUS" == "yes" ]; then
        echo -e "${GREEN}PASS (Clock is NTP-synchronized)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (Clock is NOT NTP-synchronized. Consensus needs accurate time - run: sudo timedatectl set-ntp true)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (timedatectl not available, cannot verify NTP sync)${NC}"
fi

# 8. Disk Usage on data dir partition
echo -n -e "8. Disk Usage ($DATA_DIR partition): "
if [ -d "$DATA_DIR" ]; then
    DISK_PCT=$(df -P "$DATA_DIR" | awk 'NR==2{gsub("%","",$5); print $5}')
    if [ -n "$DISK_PCT" ] && [ "$DISK_PCT" -lt 85 ]; then
        echo -e "${GREEN}PASS (${DISK_PCT}% used)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (${DISK_PCT:-N/A}% used - approaching capacity, free up space or expand disk)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (data dir not found: $DATA_DIR)${NC}"
fi

# 9. Private Key File Permissions
echo -n -e "9. Validator Key File Permissions: "
if [ -f "$KEY_FILE" ]; then
    PERMS=$(stat -c "%a" "$KEY_FILE" 2>/dev/null)
    if [ "$PERMS" == "600" ] || [ "$PERMS" == "400" ]; then
        echo -e "${GREEN}PASS (mode $PERMS - only owner can read)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (mode $PERMS is too permissive! Run: chmod 600 $KEY_FILE)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (key file not found at $KEY_FILE - check your actual secrets path)${NC}"
fi

# 10. Systemd Auto-Restart Policy
echo -n -e "10. Systemd Auto-Restart Policy: "
if [ -f "$SERVICE_FILE" ]; then
    RESTART_POLICY=$(grep -oE '^Restart=.*' "$SERVICE_FILE" | cut -d= -f2)
    if [ "$RESTART_POLICY" == "on-failure" ] || [ "$RESTART_POLICY" == "always" ]; then
        echo -e "${GREEN}PASS (Restart=$RESTART_POLICY)${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (Restart=${RESTART_POLICY:-unset}. Add 'Restart=on-failure' so the node recovers automatically from crashes)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (gnoland.service not found)${NC}"
fi

# 11. P2P Port Listening (local proxy for external reachability)
echo -n -e "11. P2P Port Listening ($P2P_PORT): "
if [ -n "$P2P_PORT" ]; then
    if command -v ss >/dev/null 2>&1; then
        LISTENING=$(ss -tlnp 2>/dev/null | grep ":$P2P_PORT ")
    else
        LISTENING=$(netstat -tlnp 2>/dev/null | grep ":$P2P_PORT ")
    fi
    if [ -n "$LISTENING" ]; then
        echo -e "${GREEN}PASS (Daemon is bound to :$P2P_PORT)${NC}"
        echo -e "   ${YELLOW}Note: this only confirms local binding, NOT that your firewall/router allows inbound traffic. Verify externally with: nc -zv YOUR_PUBLIC_IP $P2P_PORT${NC}"
        SCORE=$((SCORE+1))
    else
        echo -e "${RED}FAIL (Nothing listening on :$P2P_PORT locally)${NC}"
    fi
else
    echo -e "${YELLOW}WARN (Could not detect p2p port from config.toml)${NC}"
fi

# 12. RAM / Swap Pressure
echo -n -e "12. Memory Pressure: "
RAM_PCT=$(free | awk '/Mem:/{printf "%.0f", $3/$2*100}')
SWAP_TOTAL=$(free | awk '/Swap:/{print $2}')
SWAP_USED=$(free | awk '/Swap:/{print $3}')
if [ -n "$RAM_PCT" ] && [ "$RAM_PCT" -lt 90 ]; then
    SWAP_MSG=""
    if [ "$SWAP_TOTAL" -gt 0 ] 2>/dev/null; then
        SWAP_PCT=$((SWAP_USED * 100 / SWAP_TOTAL))
        [ "$SWAP_PCT" -gt 20 ] && SWAP_MSG=" | WARN: swap usage ${SWAP_PCT}% (may indicate RAM pressure)"
    fi
    echo -e "${GREEN}PASS (RAM: ${RAM_PCT}%${SWAP_MSG})${NC}"
    SCORE=$((SCORE+1))
else
    echo -e "${RED}FAIL (RAM: ${RAM_PCT:-N/A}% - node may be under memory pressure)${NC}"
fi

# --- Informational only (not scored) ---
echo ""
echo -e "${BLUE}--- Informational ---${NC}"

echo -n -e "Binary Version: "
if command -v gnoland >/dev/null 2>&1; then
    gnoland version 2>/dev/null || echo "N/A (command exists but --version not recognized, check manually)"
else
    echo -e "${YELLOW}gnoland binary not found in PATH${NC}"
fi

echo -n -e "Genesis File: "
if [ -f "$GENESIS_FILE" ]; then
    GSIZE=$(stat -c "%s" "$GENESIS_FILE")
    GHASH=$(sha256sum "$GENESIS_FILE" 2>/dev/null | cut -d' ' -f1)
    echo -e "${GREEN}Found (${GSIZE} bytes) - sha256: ${GHASH}${NC}"
    echo -e "   ${YELLOW}Compare this hash against the official genesis.json for test13 to confirm you're on the right chain.${NC}"
else
    echo -e "${YELLOW}genesis.json not found at $GENESIS_FILE${NC}"
fi

echo ""
echo -e "${BLUE}=====================================================${NC}"
if [ "$SCORE" -eq "$TOTAL_CHECKS" ]; then
    echo -e "${GREEN}${BOLD}RESULT: EXCELLENT! Your Gno node is highly optimized for Test13. ($SCORE/$TOTAL_CHECKS)${NC}"
else
    echo -e "${YELLOW}${BOLD}RESULT: Action required. Please fix the warnings/fails above. ($SCORE/$TOTAL_CHECKS)${NC}"
fi
echo -e "${BLUE}=====================================================${NC}"
