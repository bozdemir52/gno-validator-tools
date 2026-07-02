Markdown
# Gno.land Test13 Validator Toolset 🛠️

A comprehensive, lightweight toolset tailored for **Gno.land Test13** node operators and validators. This repository contains two production-grade utilities designed to optimize system configurations and ensure high-availability monitoring via Telegram alerts.

Developed and maintained by **pi69** (`g14dwr0qm5j054r9jpfkv0kwdn3z4ptcx9vn8kj9`).

---

## 🩺 1. Gno Node Doctor (`gno-doctor.sh`)

An automated system and configuration health-checker built strictly around the official Gno.land Test13 specifications. It verifies hardware environments, prevents rapid disk expansion, and auto-probes the active local RPC endpoint.

### Checked Metrics:
1. **Server Architecture:** Warns if running inside a restrictive VM (KVM, etc.) since bare-metal is heavily recommended for optimal GnoVM parallel transaction execution.
2. **Log Level Safety:** Verifies that `--log-level info` is explicitly appended to your systemd unit file to save disk space from verbose TM2 debug output.
3. **Pruning Strategy:** Assures `prune_strategy = "syncable"` is accurately declared in `config.toml`.
4. **Open Files Limit:** Queries systemd directly to guarantee `LimitNOFILE` is set to at least `65535`.
5. **RPC Connectivity & Sync Status:** Pings active local ports (`54657` / `26657`) to report current peer counts and catching-up state.

### How to Run:
```bash
chmod +x gno-doctor.sh
./gno-doctor.sh
```
🛡️ 2. Gno Node Watchdog (monitor.py)
A high-performance Python daemon that continuously parses local TM2 consensus log streams via journalctl and monitors hardware thresholds. It immediately broadcasts critical infrastructure anomalies directly to your personal Telegram chat.

Core Safeguards:
Block Stall (Stuck Node) Detection: Triggers an alert if the local block height fails to progress for ~3 minutes.

Missed Signing Windows: Instantly tracks consensus timeout, missed, or failed to sign patterns. Alerts after 3 consecutive missed slots.

Hardware Telemetry: Monitors and updates you if CPU, RAM, or Storage utilization breaches safe operational thresholds (85%-90%).

Interactive Status Checks: Responds seamlessly with an AUTOMATIC REPORT whenever you ping /start or /status inside the Telegram bot.

How to Run:
Install system prerequisites:

```Bash
sudo apt update && sudo apt install python3-psutil python3-requests -y
```
Open an isolated screen environment to persist the daemon:

```Bash
screen -S gno-watchdog
```
Export your operator variables and execute:

```Bash
export TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
export TELEGRAM_CHAT_ID="YOUR_TELEGRAM_CHAT_ID"
export VALIDATOR_MONIKER="pi69"

python3 monitor.py
```
To detach safely from the screen, press Ctrl + A, then D.

🔗 Connect With Us

Mail: bozdemir52@gmail.com

Tg: https://t.me/bahadir69

Website: pi69.net

Twitter/X: @bozdemir5269

Discord: @pi69
