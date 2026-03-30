#!/usr/bin/env python3
"""
Lore-Cast Heartbeat — Background session monitor
Keeps the session alive and watches for player messages.

Usage:
    python heartbeat.py --url https://qa.lore-cast.com --token sk_abc123_... --short-id abc123
    python heartbeat.py --url https://qa.lore-cast.com --token sk_abc123_... --short-id abc123 --interval 90

State file:   /tmp/lorecast_state.json      (overwritten each cycle)
Messages file: /tmp/lorecast_messages.json  (appended when unread > 0)
Log file:     /tmp/lorecast_heartbeat.log

Claude reads /tmp/lorecast_state.json before each GM action instead of making an API call.
"""

import argparse
import json
import time
import urllib.request
import urllib.error
import datetime
import sys
import os
import signal

# ── Config ────────────────────────────────────────────────────────────────────

STATE_FILE    = "/tmp/lorecast_state.json"
MESSAGES_FILE = "/tmp/lorecast_messages.json"
LOG_FILE      = "/tmp/lorecast_heartbeat.log"
PID_FILE      = "/tmp/lorecast_heartbeat.pid"

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_json(url: str, timeout: int = 10) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        log(f"⚠ Network error: {e}")
        return None
    except Exception as e:
        log(f"⚠ Unexpected error: {e}")
        return None


def write_state(state: dict, short_id: str, base_url: str):
    """Write current state to the shared temp file."""
    state["_shortId"]    = short_id
    state["_baseUrl"]    = base_url
    state["_checkedAt"]  = datetime.datetime.utcnow().isoformat() + "Z"
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def append_messages(state: dict, short_id: str, base_url: str, token: str):
    """If there are unread messages, fetch pending chat and append to the messages file."""
    if not state.get("unreadMessages", 0):
        return

    # Use the documented chat/pending endpoint with sessionToken as query param
    pending_url = f"{base_url}/api/table/chat/pending?sessionToken={token}"
    pending = fetch_json(pending_url)
    if not pending:
        return

    # pending is a list of { playerId, playerName, messageCount, lastMessage, lastMessageAt }
    entry = {
        "fetchedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "pending": pending
    }
    with open(MESSAGES_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    total = sum(p.get("messageCount", 1) for p in pending) if isinstance(pending, list) else "?"
    log(f"📨 {total} unread message(s) from {len(pending) if isinstance(pending, list) else '?'} player(s) — appended to {MESSAGES_FILE}")


def write_error_state(short_id: str, base_url: str, error: str):
    """Write an error state so Claude knows the session is unreachable."""
    state = {
        "isActive": False,
        "viewerCount": 0,
        "unreadMessages": 0,
        "error": error,
        "_shortId": short_id,
        "_baseUrl": base_url,
        "_checkedAt": datetime.datetime.utcnow().isoformat() + "Z"
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def cleanup(signum, frame):
    log("🛑 Heartbeat stopped.")
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    sys.exit(0)

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Lore-Cast background heartbeat")
    parser.add_argument("--url",       required=True,  help="Base URL (e.g. https://qa.lore-cast.com)")
    parser.add_argument("--token",     required=True,  help="Session token (sk_...)")
    parser.add_argument("--short-id",  required=True,  help="Session short ID (e.g. hu8jor)")
    parser.add_argument("--interval",  type=int, default=120, help="Ping interval in seconds (default: 120)")
    args = parser.parse_args()

    base_url  = args.url.rstrip("/")
    token     = args.token
    short_id  = args.short_id
    interval  = args.interval
    # sessionToken passed as query param (GM-extended view with unreadMessages)
    state_url = f"{base_url}/api/table/sessions/{short_id}/state?sessionToken={token}"

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT,  cleanup)

    # Write PID so Claude can stop the process cleanly
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log(f"💓 Lore-Cast heartbeat started — session {short_id} @ {base_url}")
    log(f"   Interval: {interval}s | State: {STATE_FILE} | Log: {LOG_FILE}")

    consecutive_failures = 0

    while True:
        state = fetch_json(state_url)

        if state is None:
            consecutive_failures += 1
            write_error_state(short_id, base_url, f"Unreachable after {consecutive_failures} attempt(s)")
            log(f"❌ State fetch failed ({consecutive_failures} consecutive failure(s))")
            if consecutive_failures >= 5:
                log("🚨 5 consecutive failures — Claude should investigate.")
        else:
            consecutive_failures = 0
            write_state(state, short_id, base_url)

            active    = state.get("isActive", False)
            viewers   = state.get("viewerCount", 0)
            unread    = state.get("unreadMessages", 0)

            status_icon = "✅" if active else "💀"
            log(f"{status_icon} active={active} | viewers={viewers} | unread={unread}")

            if not active:
                log("⚠ Session is no longer active. Heartbeat will keep running but Claude should recreate the session.")

            if unread > 0:
                append_messages(state, short_id, base_url, token)

        time.sleep(interval)


if __name__ == "__main__":
    main()
