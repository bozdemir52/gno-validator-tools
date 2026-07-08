# -*- coding: utf-8 -*-
"""
Gno Node Watchdog - TM2 Consensus Log Parser & Telegram Alert Daemon
Designed for Gno.land Test13 node operators.

Configure via environment variables (recommended):
    export TELEGRAM_BOT_TOKEN="..."
    export TELEGRAM_CHAT_ID="..."
    export VALIDATOR_MONIKER="your-moniker"
    export GNO_RPC_URL="http://localhost:54657"     # optional, auto-detected if omitted
    export REPORT_INTERVAL_HOURS="6"                # periodic status report, like a heartbeat
"""
import os
import re
import time
import psutil
import requests
import subprocess
import threading
from datetime import datetime

# --- CONFIGURATION (env vars override these) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")
VALIDATOR_MONIKER = os.environ.get("VALIDATOR_MONIKER", "your-moniker")
REPORT_INTERVAL_SECONDS = int(float(os.environ.get("REPORT_INTERVAL_HOURS", "6")) * 3600)

DATA_DIR = os.environ.get("GNO_DATA_DIR", os.path.expanduser("~/gnoland-data"))
CONFIG_TOML = os.path.join(DATA_DIR, "config", "config.toml")

START_TIME = time.time()


def detect_rpc_url():
    """Auto-detect the RPC port from config.toml's [rpc] laddr, fall back to env/default."""
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

# --- ALERT THRESHOLDS (env-configurable) ---
ALERT_CPU_THRESHOLD = int(os.environ.get("ALERT_CPU_THRESHOLD", "95"))
ALERT_DISK_THRESHOLD = int(os.environ.get("ALERT_DISK_THRESHOLD", "90"))
ALERT_RAM_THRESHOLD = int(os.environ.get("ALERT_RAM_THRESHOLD", "90"))
ALERT_TIMEOUT_THRESHOLD = 3  # Alert if node misses 3 consecutive blocks locally
CPU_SUSTAINED_CHECKS = 15  # ~30s of sustained high CPU (at 2s polling) before alerting
HARDWARE_ALERT_COOLDOWN = 1800  # 30 min between repeat hardware alerts, not 5 min

missed_block_counter = 0
last_seen_signing_ok = True  # tracked for the periodic report's "Node Status" line


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


def monitor_gno_logs():
    """
    STRICT FILTERING: Only triggers on absolute signing failures.
    Ignores regular consensus timeouts, peer drops, and benign warnings.
    """
    global missed_block_counter, last_seen_signing_ok
    print("[INFO] Gno TM2 log reader started with STRICT filtering...")
    try:
        process = subprocess.Popen(
            ["journalctl", "-u", "gnoland", "-f", "-n", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in process.stdout:
            line_lower = line.lower()

            # Sadece KESİN imza veya yetki kaçırma loglarını say
            is_signing_failure = any(
                k in line_lower for k in (
                    "failed to sign", 
                    "wrong signature", 
                    "signature verification failed",
                    "missed block",
                    "absent validator"
                )
            )

            if is_signing_failure:
                missed_block_counter += 1
                last_seen_signing_ok = False
            elif "finalizing commit of block" in line_lower:
                missed_block_counter = 0
                last_seen_signing_ok = True
    except Exception as e:
        print(f"[ERROR] Failed to read journalctl: {e}")


def get_gno_status():
    """Fetches local block height, sync status and peer count from Gno RPC"""
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
    """Builds a formatted report, adapted for Gno.land Test13."""
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
    """Sends a heartbeat-style status report every REPORT_INTERVAL_SECONDS."""
    while True:
        time.sleep(REPORT_INTERVAL_SECONDS)
        try:
            send_alert(build_status_report())
        except Exception as e:
            print(f"[ERROR] Failed to send periodic report: {e}")


def telegram_command_listener():
    """Listens for /start or /status typed in Telegram and replies immediately."""
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
                    continue  # ignore commands from any other chat
                if text in ("/start", "/status"):
                    send_alert(build_status_report())
        except Exception as e:
            print(f"[ERROR] Telegram command listener: {e}")
            time.sleep(5)


def main():
    global missed_block_counter
    print(f"[INFO] Gno Node Watchdog started for {VALIDATOR_MONIKER} (RPC: {GNO_RPC_URL})...")

    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are still placeholders!")
        print("[WARN] No alerts will actually reach Telegram until these env vars are set")
    if VALIDATOR_MONIKER == "your-moniker":
        print("[WARN] VALIDATOR_MONIKER is still the default placeholder - set it via env var.")

    send_alert(f"[OK] Watchdog Started\nValidator: `{VALIDATOR_MONIKER}` is now being monitored locally.")

    threading.Thread(target=monitor_gno_logs, daemon=True).start()
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

        # 2. Missed Block / Timeout Alert
        if missed_block_counter >= ALERT_TIMEOUT_THRESHOLD:
            send_alert(f"[VALIDATOR ALERT]\nYour node just missed `{missed_block_counter}` consecutive signing windows! Check `gnoland` logs immediately.")
            missed_block_counter = 0

        # 3. Hardware Resource Monitoring (sustained-check to avoid alerting on brief spikes)
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
