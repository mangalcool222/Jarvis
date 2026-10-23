"""
Harvey Webhook Dispatcher — Real-Time Event Sync with n8n & Google Sheets
"""

import os
import json
import logging
import urllib.request
import asyncio

logger = logging.getLogger("harvey.webhook")

DEFAULT_WEBHOOK_URL = os.environ.get("HARVEY_WEBHOOK_URL", "")

def _send_sync(url: str, payload: dict):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Harvey-AI-SDR/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("Harvey webhook dispatched: %s (status %s)", payload.get("event"), resp.status)
    except Exception as e:
        logger.warning("Harvey webhook dispatch failed (non-fatal): %s", e)

def dispatch_event(event_name: str, data: dict, webhook_url: str | None = None):
    """Fire-and-forget webhook dispatcher."""
    # Safety gate: NEVER fire real webhooks during automated tests or CI runners
    if any(k in os.environ for k in ("PYTEST_CURRENT_TEST", "CI", "GITHUB_ACTIONS")):
        return

    url = webhook_url or os.environ.get("HARVEY_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
    if not url:
        return
        
    payload = {
        "event": event_name,
        "action": "update_status",
        **data
    }
    
    # Run in thread or background loop so we don't block the caller
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop and loop.is_running():
        loop.run_in_executor(None, _send_sync, url, payload)
    else:
        import threading
        threading.Thread(target=_send_sync, args=(url, payload), daemon=True).start()
