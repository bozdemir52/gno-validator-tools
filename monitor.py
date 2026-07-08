# -*- coding: utf-8 -*-
"""
Gno Node Watchdog v2.0 - RPC Precommit Engine & Telegram Alert Daemon
Inspired by GnoDuty & Tenderduty, optimized for Gno.land Test13.

Configure via environment variables (recommended):
    export TELEGRAM_BOT_TOKEN="..."
    export TELEGRAM_CHAT_ID="..."
    export VALIDATOR_MONIKER="your-moniker"
    export GNO_RPC_URL="http://localhost:26657"  # Change if you use a custom port (e.g. 32267)
    export GNO_VALOPER_ADDRESS="g1..."          # Optional: auto-detected from RPC if omitted
"""
import os
import re
import time
import psutil
import requests
import threading
from datetime import datetime

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")
VALIDATOR_MONIKER = os.environ.get("VALIDATOR_MONIKER", "your-moniker")
REPORT_INTERVAL_SECONDS = int(float(os.environ.get("REPORT_INTERVAL_HOURS", "6")) * 3600)

DATA_DIR = os.environ.get("GNO_DATA_DIR", os.path.expanduser("~/gnoland-data"))
CONFIG_TOML = os.path.join(DATA_DIR, "config", "config.toml")

START_TIME = time.time()


def detect_rpc_url():
    """Auto-detect the RPC port from config.toml, fall back to default."""
    env_url = os.environ.get("GNO_RPC_URL")
    if env_url:
        return env_url
    try:
        with open(CONFIG_TOML, "r") as f:
            content = f.read()
        rpc_section = content.split("[rpc]", 1)[1].split("\n[", 1)[0]
        match = re.search(r'^\s*laddr\s*=\s*"tcp://[^:]+:(\d+)"', rpc_section, re.MULTILINE)
        if match:
            return f"http://localhost:{match.group(1)}"
    except Exception:
        pass
    return "http://localhost:26657"


GNO_RPC_URL = detect_rpc_url()

# --- ALERT THRESHOLDS ---
ALERT_CPU_THRESHOLD = int(os.environ.get("ALERT_CPU_THRESHOLD", "95"))
ALERT_DISK_THRESHOLD = int(os.environ.get("ALERT_DISK_THRESHOLD", "90"))
ALERT_RAM_THRESHOLD = int(os.environ.get("ALERT_RAM_THRESHOLD", "90"))
ALERT_TIMEOUT_THRESHOLD = 3  # Alert if validator misses 3 consecutive blocks
CPU_SUSTAINED_CHECKS = 15
HARDWARE_ALERT_COOLDOWN = 1800

missed_block_counter = 0
last_seen_signing_ok = True


def telegram_api(method, data=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        if data:
            requests.post(url, data=data, timeout=5)
        else:
            requests.get(url, timeout=5)
    except Exception:
        pass


def send_alert(text):
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    telegram_api("sendMessage", data)


def detect_validator_address():
    """Auto-detects the running node's validator address from local RPC."""
    try:
        status = requests.get(f"{GNO_RPC_URL}/status", timeout=3).json()
        return status.get("result", {}).get("validator_info", {}).get("address")
    except Exception:
        return None


def monitor_gno_rpc():
    """
    Advanced TM2 Precommit Inspection Engine.
    Queries the actual blockchain state to check for real signing signatures.
    Preserves state on RPC timeouts to prevent false alarms.
    """
    global missed_block_counter, last_seen_signing_ok
    print("[INFO] Gno Duty-Style RPC Precommit Monitor started...")

    val_address = os.environ.get("GNO_VALOPER_ADDRESS")
    if not val_address:
        val_address = detect_validator_address()

    if val_address:
        print(f"[INFO] Target Validator Address Account: {val_address}")
    else:
        print("[WARN] Could not auto-detect validator address yet. Will retry in loop...")

    last_checked_height = 0

    while True:
        time.sleep(1.5)  # Fast polling to track ledger blocks dynamically
        try:
            status_resp = requests.get(f"{GNO_RPC_URL}/status", timeout=3).json()
            current_height = int(status_resp["result"]["sync_info"]["latest_block_height"])
            is_syncing = status_resp["result"]["sync_info"]["catching_up"]

            if not val_address:
                val_address = status_resp.get("result", {}).get("validator_info", {}).get("address")
                if val_address:
                    print(f"[INFO] Auto-detected validator address successfully: {val_address}")

            if current_height <= last_checked_height:
                continue

            if last_checked_height == 0:
                last_checked_height = current_height
                continue

            # Scan missed block windows across newly discovered block range
            for h in range(last_checked_height + 1, current_height + 1):
                block_resp = requests.get(f"{GNO_RPC_URL}/block?height={h}", timeout=3).json()
                last_commit = block_resp.get("result", {}).get("block", {}).get("last_commit", {})
                precommits = last_commit.get("precommits", [])

                if not precommits:
                    continue

                signed = False
                if val_address:
                    val_addr_lower = str(val_address).lower()
                    for precommit in precommits:
                        if precommit and isinstance(precommit, dict):
                            addr = precommit.get("validator_address", "")
                            if str(addr).lower() == val_addr_lower:
                                signed = True
                                break

                if signed:
                    missed_block_counter = 0
                    last_seen_signing_ok = True
                else:
                    # Trigger miss logic only if we are fully synced and verified
                    if val_address and not is_syncing:
                        missed_block_counter += 1
                        last_seen_signing_ok = False
                        print(f"[WARN] Missed on-chain signature for block {h-1}! Consecutive total: {missed_block_counter}")

            last_checked_height = current_height

        except Exception as e:
            # GnoDuty Rule: PRESERVE STATE ON RPC TIMEOUT/ERROR
            # Node might be heavy loaded; don't change counter or alert false positives.
            print(f"[WARN] RPC communication timeout or issue: {e}. Preserving current state safely.")


def get_gno_status():
    try:
        status = requests.get(f"{GNO_RPC_URL}/status", timeout=3).json()
        height = int(status["result"]["sync_info"]["latest_block_height"])
        is_syncing = status["result"]["sync_info"]["catching_up"]

        net_info = requests.get(f"{GNO_RPC_URL}/net_info", timeout=3).json()
        peers = net_info["result"].get("n_peers", "N/A")

        return height, is_syncing, peers
    except Exception:
        return None, None, None


def format_uptime(seconds):
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def build_status_report():
    height, is_syncing, peers = get_gno_status()
    sync_str = "N/A"
    if is_syncing is not None:
        sync_str = "[SYNCING] catching-up" if is_syncing else "[OK] in-sync"

    node_str = "[OK] Active / Signing" if last_seen_signing_ok else "[FAIL] Missing signatures!"

    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else "/").percent
    disk_used_gb = psutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else "/").used / (1024 ** 3)
    disk_total_gb = psutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else "/").total / (1024 ** 3)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = (
        f"AUTOMATIC REPORT\n"
        f"{VALIDATOR_MONIKER} | GNO.LAND TEST13 WATCHDOG\n"
        f"Time: {now}\n"
        f"-----------------------------\n"
        f"Blockchain & Node\n"
        f"Local Block: {height if height is not None else 'N/A'}\n"
        f"Sync Status: {sync_str}\n"
        f"Peers: {peers}\n"
        f"Node Status: {node_str}\n"
        f"-----------------------------\n"
        f"Server Health\n"
        f"CPU: {cpu}% | RAM: {ram}%\n"
        f"Data Dir Disk: {disk_used_gb:.2f} GB / {disk_total_gb:.2f} GB ({disk}%)\n"
        f"Watchdog Uptime: {format_uptime(time.time() - START_TIME)}\n"
        f"-----------------------------"
    )
    return report


def periodic_report_loop():
    while True:
        time.sleep(REPORT_INTERVAL_SECONDS)
        try:
            send_alert(build_status_report())
        except Exception as e:
            print(f"[ERROR] Failed to send periodic report: {e}")


def telegram_command_listener():
    offset = None
    print("[INFO] Telegram command listener started (/start, /status)...")
    while True:
        try:
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip().lower()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue
                if text in ("/start", "/status"):
                    send_alert(build_status_report())
        except Exception as e:
            print(f"[ERROR] Telegram command listener: {e}")
            time.sleep(5)


def main():
    global missed_block_counter
    print(f"[INFO] Gno Node Watchdog Engine v2.0 Started for {VALIDATOR_MONIKER}...")

    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are placeholders!")

    send_alert(f"[🟢 Watchdog Engine Up]\nValidator: `{VALIDATOR_MONIKER}` is now being verified via RPC block data streams.")

    threading.Thread(target=monitor_gno_rpc, daemon=True).start()
    threading.Thread(target=telegram_command_listener, daemon=True).start()
    if REPORT_INTERVAL_SECONDS > 0:
        threading.Thread(target=periodic_report_loop, daemon=True).start()

    last_height = 0
    stuck_counter = 0
    last_hardware_alert_time = 0
    cpu_high_streak = 0

    while True:
        current_height, is_syncing, _ = get_gno_status()

        # 1. Block Stall (Stuck) Detection
        if current_height is not None:
            if current_height != last_height:
                stuck_counter = 0
            else:
                stuck_counter += 1
            if stuck_counter >= 90:  # ~3 minutes with 2s polling
                send_alert(f"[CRITICAL] Node STUCK!\nBlock: `{current_height}`\nChain production halted locally!")
                stuck_counter = 0
            last_height = current_height

        # 2. On-Chain Missed Block / Signature Window Alert
        if missed_block_counter >= ALERT_TIMEOUT_THRESHOLD:
            send_alert(f"[🚨 VALIDATOR MISSED SIGNING]\nYour node missed `{missed_block_counter}` consecutive blocks on-chain! Investigate immediately.")
            missed_block_counter = 0

        # 3. Hardware Resource Monitoring
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else "/").percent

        if cpu > ALERT_CPU_THRESHOLD:
            cpu_high_streak += 1
        else:
            cpu_high_streak = 0

        if time.time() - last_hardware_alert_time > HARDWARE_ALERT_COOLDOWN:
            alert_msg = ""
            if cpu_high_streak >= CPU_SUSTAINED_CHECKS:
                alert_msg += f"[HIGH CPU, sustained] {cpu}%\n"
            if ram > ALERT_RAM_THRESHOLD:
                alert_msg += f"[HIGH RAM] {ram}%\n"
            if disk > ALERT_DISK_THRESHOLD:
                alert_msg += f"[DATA DIR DISK] {disk}%\n"
            if alert_msg:
                send_alert(f"[SYSTEM RESOURCE WARNING]\n\n{alert_msg}")
                last_hardware_alert_time = time.time()
                cpu_high_streak = 0

        time.sleep(2)


if __name__ == "__main__":
    main()
