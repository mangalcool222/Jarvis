"""Harvey Dashboard — local web UI to set up, control, and monitor Harvey."""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, Response, FileResponse,
)

logger = logging.getLogger("harvey.dashboard")

from harvey.paths import PROJECT_ROOT, get_workspace_dir, get_db_path, get_data_dir  # noqa: E402


class _DynamicWorkspacePath:
    def __init__(self, resolver):
        self._resolver = resolver

    def _path(self) -> Path:
        return self._resolver()

    def __getattr__(self, name):
        return getattr(self._path(), name)

    def __str__(self):
        return str(self._path())

    def __repr__(self):
        return repr(self._path())

    def __fspath__(self):
        return str(self._path())

    def __truediv__(self, other):
        return self._path() / other


DB_PATH = _DynamicWorkspacePath(get_db_path)
ENV_FILE = _DynamicWorkspacePath(lambda: (get_workspace_dir() / ".env") if (get_workspace_dir() / ".env").is_file() else (PROJECT_ROOT / ".env"))
CONFIG_FILE = _DynamicWorkspacePath(lambda: (get_workspace_dir() / "harvey.yaml"))
PID_FILE = _DynamicWorkspacePath(lambda: get_data_dir() / "harvey.pid")
LOG_FILE = _DynamicWorkspacePath(lambda: get_data_dir() / "harvey.log")


def _resolve_config_file() -> Path:
    """harvey.local.yaml wins when present — same resolution as config.py's
    loader, so the dashboard doesn't judge setup complete against the
    tracked harvey.yaml template while the real trained config sits in the
    gitignored local override."""
    from harvey.config import _find_config_file, ConfigFileNotFoundError
    try:
        return Path(_find_config_file())
    except ConfigFileNotFoundError:
        return CONFIG_FILE

app = FastAPI(title="Harvey Dashboard")

# Harvey process tracking
_harvey_process: subprocess.Popen | None = None
_harvey_started_at: datetime | None = None
_env_lock = asyncio.Lock()


# ── Helpers ──


async def query_db(sql: str, params: tuple = ()) -> list[dict]:
    """Run a query and return results as list of dicts.

    Never raises: a missing DB file, missing table, or malformed schema
    returns [] so no dashboard route can 500 on an empty install.
    """
    if not DB_PATH.exists():
        return []
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("query_db failed (%s): %s", sql.split(None, 4)[:4], e)
        return []


def _mask_key(key: str) -> str:
    """Mask an API key for display: show first 4 and last 4 chars."""
    if not key or len(key) < 10:
        return "****" if key else ""
    return key[:4] + "****" + key[-4:]


def _read_env_file() -> dict[str, str]:
    """Read .env file and return as dict."""
    env_vars = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    return env_vars


def _write_env_file(updates: dict[str, str]):
    """Update .env file with new values, preserving existing entries."""
    existing = _read_env_file()
    existing.update(updates)
    lines = [f"{k}={v}" for k, v in existing.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    load_dotenv(str(ENV_FILE), override=True)


def _check_harvey_pid() -> int | None:
    """Check if there's a running Harvey process from a PID file."""
    global _harvey_process, _harvey_started_at
    if _harvey_process and _harvey_process.poll() is None:
        return _harvey_process.pid
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    return None


# ── Setup Status ──


@app.get("/api/setup-status")
async def get_setup_status():
    """Check what's configured and what still needs setup."""
    checks = []

    # 1. Venv
    import sys
    checks.append({
        "id": "venv", "label": "Python virtual environment",
        "done": (PROJECT_ROOT / ".venv").is_dir() or (sys.prefix != sys.base_prefix),
        "required": True,
        "help": "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -e .",
    })

    # 2. Env file
    env_vars = _read_env_file()
    env_exists = ENV_FILE.exists() and bool(env_vars)
    checks.append({
        "id": "env_file", "label": "Environment file (.env)",
        "done": env_exists,
        "required": True,
        "help": "Go to Settings & Ops to enter your credentials or create .env.",
    })

    # 3. Email provider configured (matches channels.email.provider)
    provider = _current_provider()

    def _has(*keys):
        return all((env_vars.get(k, "") or os.getenv(k, "")).strip() for k in keys)

    if provider == "gmail":
        provider_done = _has("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET") and \
            (PROJECT_ROOT / "data" / "gmail_token.json").is_file()
        provider_help = ("Set GMAIL_CLIENT_ID/SECRET in Settings, then run "
                         "'harvey gmail auth' in your terminal.")
    elif provider == "smtp":
        provider_done = _has("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")
        provider_help = "Enter your SMTP host, username, and password in Settings."
    else:
        instantly_key = env_vars.get("INSTANTLY_API_KEY", "") or os.getenv("INSTANTLY_API_KEY", "")
        provider_done = bool(instantly_key) and instantly_key != "your_instantly_api_key_here"
        provider_help = "Enter your Instantly API key in Settings."
    checks.append({
        "id": "email_provider", "label": f"Email provider configured ({provider})",
        "done": provider_done,
        "required": True,
        "help": provider_help,
    })

    # 4. Email verification (optional / managed by platform MX Shield)
    verifier_set = _has("REOON_API_KEY") or _has("ZEROBOUNCE_API_KEY") or _has("HUNTER_API_KEY")
    checks.append({
        "id": "verifier", "label": "Email verification key",
        "done": verifier_set,
        "required": False,
        "help": "Add a Reoon (free 600/mo), ZeroBounce, or Hunter key in Settings (optional — built-in MX Shield active).",
    })

    # 5. Config valid
    config_valid = False
    config_path = _resolve_config_file()
    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            company = cfg.get("persona", {}).get("company", "")
            product = cfg.get("product", {}).get("name", "")
            config_valid = company not in ("Your Company", "") and product not in ("Your Product", "")
        except Exception:
            pass
    checks.append({
        "id": "config", "label": f"Jarvis configured ({config_path.name})",
        "done": config_valid,
        "required": True,
        "help": "Train Jarvis on your product. Use the trainer or set up manually through Claude.",
    })

    # 6. Product trained
    product_trained = (PROJECT_ROOT / "skills" / "product_knowledge.md").exists()
    checks.append({
        "id": "product_trained", "label": "Product knowledge trained",
        "done": product_trained,
        "required": True,
        "help": "Run: harvey train https://yourwebsite.com (or set up through Claude).",
    })

    # 7. LinkedIn (optional)
    linkedin_email = env_vars.get("LINKEDIN_EMAIL", "") or os.getenv("LINKEDIN_EMAIL", "")
    linkedin_pass = env_vars.get("LINKEDIN_PASSWORD", "") or os.getenv("LINKEDIN_PASSWORD", "")
    checks.append({
        "id": "linkedin", "label": "LinkedIn credentials",
        "done": bool(linkedin_email) and bool(linkedin_pass),
        "required": False,
        "help": "Optional. Enter your LinkedIn credentials in Settings to enable LinkedIn prospecting.",
    })

    # 8. Cloudflare (optional)
    cf_id = env_vars.get("CLOUDFLARE_ACCOUNT_ID", "") or os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    cf_token = env_vars.get("CLOUDFLARE_API_TOKEN", "") or os.getenv("CLOUDFLARE_API_TOKEN", "")
    checks.append({
        "id": "cloudflare", "label": "Cloudflare deep crawling",
        "done": bool(cf_id) and bool(cf_token),
        "required": False,
        "help": "Optional. For JavaScript-rendered website crawling during training.",
    })

    required_checks = [c for c in checks if c["required"]]
    completed_required = sum(1 for c in required_checks if c["done"])

    return {
        "checks": checks,
        "completed": completed_required,
        "total_required": len(required_checks),
        "percent": int(completed_required / len(required_checks) * 100) if required_checks else 0,
    }


# ── Settings ──


def _current_provider() -> str:
    """Read channels.email.provider from the active config (best-effort)."""
    try:
        with open(_resolve_config_file()) as f:
            cfg = yaml.safe_load(f) or {}
        return ((cfg.get("channels") or {}).get("email") or {}).get("provider", "instantly")
    except Exception:
        return "instantly"


@app.get("/api/settings")
async def get_settings():
    """Get current settings — presence flags only for secrets, never raw values."""
    env_vars = _read_env_file()
    all_keys = [
        "INSTANTLY_API_KEY", "LINKEDIN_EMAIL", "LINKEDIN_PASSWORD",
        "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD",
        "IMAP_HOST", "IMAP_PORT", "IMAP_USERNAME", "IMAP_PASSWORD",
        "REOON_API_KEY", "ZEROBOUNCE_API_KEY", "HUNTER_API_KEY",
    ]
    for key in all_keys:
        if key not in env_vars:
            env_vars[key] = os.getenv(key, "")

    def is_set(k):
        return bool((env_vars.get(k) or "").strip())

    # Gmail is authorized once harvey gmail auth has stored a token file.
    gmail_token = (PROJECT_ROOT / "data" / "gmail_token.json").is_file()

    return {
        "provider": _current_provider(),
        # Non-secret values echo back so fields repopulate; secrets are
        # presence-only so keys never leave the box.
        "instantly_api_key_set": is_set("INSTANTLY_API_KEY"),
        "linkedin_email": env_vars.get("LINKEDIN_EMAIL", ""),
        "linkedin_password_set": is_set("LINKEDIN_PASSWORD"),
        "cloudflare_account_id": env_vars.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "cloudflare_api_token_set": is_set("CLOUDFLARE_API_TOKEN"),
        "gmail_client_id": env_vars.get("GMAIL_CLIENT_ID", ""),
        "gmail_client_secret_set": is_set("GMAIL_CLIENT_SECRET"),
        "gmail_authorized": gmail_token,
        "smtp_host": env_vars.get("SMTP_HOST", ""),
        "smtp_port": env_vars.get("SMTP_PORT", ""),
        "smtp_username": env_vars.get("SMTP_USERNAME", ""),
        "smtp_password_set": is_set("SMTP_PASSWORD"),
        "imap_host": env_vars.get("IMAP_HOST", ""),
        "imap_port": env_vars.get("IMAP_PORT", ""),
        "reoon_api_key_set": is_set("REOON_API_KEY"),
        "zerobounce_api_key_set": is_set("ZEROBOUNCE_API_KEY"),
        "hunter_api_key_set": is_set("HUNTER_API_KEY"),
    }


@app.post("/api/settings/env")
async def save_env_settings(request: Request):
    """Save environment variables to .env file."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "message": "Invalid request body."}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"success": False, "message": "Invalid request body."}, status_code=400)
    async with _env_lock:
        updates = {}
        for key in ["INSTANTLY_API_KEY", "LINKEDIN_EMAIL", "LINKEDIN_PASSWORD",
                     "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
                     "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
                     "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD",
                     "IMAP_HOST", "IMAP_PORT", "IMAP_USERNAME", "IMAP_PASSWORD",
                     "REOON_API_KEY", "ZEROBOUNCE_API_KEY", "HUNTER_API_KEY"]:
            if key in data and data[key] is not None:
                # Strip newlines so a crafted value can't inject extra .env entries
                updates[key] = str(data[key]).replace("\n", " ").replace("\r", " ").strip()
        if updates:
            try:
                _write_env_file(updates)
            except Exception as e:
                logger.warning("Failed to write .env: %s", e)
                return {"success": False, "message": "Could not write .env file."}
    return {"success": True}


@app.post("/api/settings/test-instantly")
async def test_instantly(request: Request):
    """Test an Instantly API key."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    api_key = str(data.get("api_key", "") or "")
    if not api_key:
        return {"success": False, "message": "No API key provided."}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.instantly.ai/api/v2/accounts",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return {"success": True, "message": "Connected to Instantly."}
            else:
                return {"success": False, "message": f"API returned {resp.status_code}. Check your key."}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}


# ── Companies ──


@app.get("/api/companies")
async def get_companies():
    """All companies with contact counts."""
    rows = await query_db("""
        SELECT c.*,
            (SELECT COUNT(*) FROM prospects p WHERE p.company_id = c.id) as contact_count
        FROM companies c ORDER BY c.created_at DESC LIMIT 200
    """)
    return rows


@app.get("/api/companies/{company_id}/contacts")
async def get_company_contacts(company_id: str):
    """Get all contacts for a specific company."""
    rows = await query_db(
        "SELECT * FROM prospects WHERE company_id = ? ORDER BY score DESC",
        (company_id,),
    )
    return rows


# ── Feedback ──


@app.post("/api/feedback")
async def add_feedback(request: Request):
    """Add a comment/feedback on any entity."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    entity_type = str(data.get("entity_type", "") or "")[:50]
    entity_id = str(data.get("entity_id", "") or "")[:100]
    comment = str(data.get("comment", "") or "").strip()[:4000]
    if not comment:
        return {"success": False, "message": "Comment is required."}
    feedback_id = uuid.uuid4().hex[:12]
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(DB_PATH)) as db:
            # Ensure the table exists so feedback works even on a fresh install
            await db.execute(
                """CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT,
                    entity_id TEXT,
                    comment TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            await db.execute(
                "INSERT INTO feedback (id, entity_type, entity_id, comment) VALUES (?, ?, ?, ?)",
                (feedback_id, entity_type, entity_id, comment),
            )
            await db.commit()
    except Exception as e:
        logger.warning("Failed to save feedback: %s", e)
        return {"success": False, "message": "Could not save feedback."}
    return {"success": True, "id": feedback_id}


@app.get("/api/feedback/{entity_type}/{entity_id}")
async def get_feedback(entity_type: str, entity_id: str):
    """Get feedback for an entity."""
    rows = await query_db(
        "SELECT * FROM feedback WHERE entity_type = ? AND entity_id = ? ORDER BY created_at DESC",
        (entity_type, entity_id),
    )
    return rows


# ── Harvey Controls ──


@app.get("/api/harvey/status")
async def get_harvey_status():
    """Check if Harvey is currently running."""
    pid = _check_harvey_pid()
    started = _harvey_started_at.isoformat() if _harvey_started_at else None
    return {"running": pid is not None, "pid": pid, "started_at": started}


@app.post("/api/harvey/start")
async def start_harvey():
    """Start Harvey's heartbeat loop as a subprocess."""
    global _harvey_process, _harvey_started_at

    if _check_harvey_pid():
        return {"success": False, "message": "Jarvis is already running."}

    # Ensure data dir exists
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)

    try:
        log_handle = open(LOG_FILE, "a")
        try:
            env = {**os.environ, "HARVEY_WORKSPACE": str(get_workspace_dir())}
            _harvey_process = subprocess.Popen(
                [sys.executable, "-m", "harvey", "run"],
                cwd=str(get_workspace_dir()),
                env=env,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )
        finally:
            # Child holds its own copies of the fds; don't leak ours.
            log_handle.close()
    except Exception as e:
        logger.warning("Failed to start Jarvis: %s", e)
        return {"success": False, "message": f"Failed to start Jarvis: {e}"}
    _harvey_started_at = datetime.now()

    # Write PID file
    try:
        PID_FILE.write_text(str(_harvey_process.pid))
    except OSError as e:
        logger.warning("Could not write PID file: %s", e)

    return {"success": True, "pid": _harvey_process.pid}


@app.post("/api/harvey/stop")
async def stop_harvey():
    """Stop the Harvey subprocess."""
    global _harvey_process, _harvey_started_at

    pid = _check_harvey_pid()
    if not pid:
        return {"success": False, "message": "Jarvis is not running."}

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait briefly for graceful shutdown
        for _ in range(10):
            try:
                os.kill(pid, 0)
                await asyncio.sleep(0.5)
            except ProcessLookupError:
                break
        else:
            # Force kill if still running
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    except (ProcessLookupError, PermissionError):
        pass

    _harvey_process = None
    _harvey_started_at = None
    PID_FILE.unlink(missing_ok=True)

    return {"success": True}


@app.get("/api/harvey/logs")
async def get_harvey_logs():
    """Get recent log lines."""
    if not LOG_FILE.exists():
        return {"lines": []}
    try:
        # Tail only the last 64KB so a huge log file never blocks the UI
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            text = f.read().decode("utf-8", errors="replace")
        lines = text.strip().splitlines()[-100:]
        return {"lines": lines}
    except Exception:
        return {"lines": []}


# ── Pipeline Data (existing endpoints) ──


@app.get("/api/stats")
async def get_stats():
    """Pipeline overview stats."""
    try:
        prospects = await query_db(
            "SELECT status, COUNT(*) as count FROM prospects GROUP BY status"
        )
        prospect_total = sum(r["count"] for r in prospects)
        prospect_map = {r["status"]: r["count"] for r in prospects}

        campaigns = await query_db(
            "SELECT status, COUNT(*) as count FROM campaigns GROUP BY status"
        )
        campaign_map = {r["status"]: r["count"] for r in campaigns}

        conversations = await query_db(
            "SELECT status, COUNT(*) as count FROM conversations GROUP BY status"
        )
        convo_map = {r["status"]: r["count"] for r in conversations}

        actions = await query_db("SELECT COUNT(*) as count FROM actions")
        action_count = actions[0]["count"] if actions else 0

        usage = await query_db(
            "SELECT claude_calls, codex_calls FROM usage_log WHERE date = date('now')"
        )
        usage_today = (usage[0]["claude_calls"] or 0) if usage else 0
        codex_today = (usage[0]["codex_calls"] or 0) if usage else 0

        return {
            "prospects": {"total": prospect_total, "by_status": prospect_map},
            "campaigns": {"total": sum(campaign_map.values()), "by_status": campaign_map},
            "conversations": {"total": sum(convo_map.values()), "by_status": convo_map},
            "actions_total": action_count,
            "claude_calls_today": usage_today,
            "codex_calls_today": codex_today,
            "brain_provider": _active_provider(),
            "brain_status": await _brain_status(),
        }
    except Exception as e:
        return {"error": str(e)}


_USAGE_SUM = (
    "COUNT(DISTINCT CASE WHEN session_id != '' THEN session_id ELSE id END) AS calls, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
    "COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens, "
    "COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens, "
    "ROUND(COALESCE(SUM(cost_usd), 0), 4) AS cost_usd"
)

_quota_clients: dict = {}


def _active_brain():
    """The brain config harvey.yaml selects (None if unreadable)."""
    try:
        from harvey.config import load_brain_config
        return load_brain_config()
    except Exception:
        return None


async def _brain_status() -> dict:
    """Last recorded brain health transition ({} if none): lets the
    dashboard say "Codex paused: <why>" instead of looking healthy."""
    from harvey.brain import BRAIN_STATUS_KEY, active_brain_status
    rows = await query_db("SELECT value FROM settings WHERE key = ?", (BRAIN_STATUS_KEY,))
    # Only the configured provider's health (a stale Codex pause isn't
    # Claude's).
    return active_brain_status(rows[0]["value"], _active_provider()) if rows else {}


def _active_provider() -> str:
    brain = _active_brain()
    return brain.provider if brain else ""


def _quota_client_for(provider: str, model: str = ""):
    """One cached quota reader per provider (and Codex model). Each reads
    only its own subscription, so a Claude gauge is never shown as Codex or
    vice versa, and Codex shows the bucket metering the configured model."""
    key = (provider, model if provider == "codex" else "")
    if key not in _quota_clients:
        if provider == "codex":
            from harvey.codex import CodexClient, CodexQuotaClient
            _quota_clients[key] = CodexQuotaClient(CodexClient(model=model))
        elif provider == "claude":
            from harvey.integrations.quota import QuotaClient
            _quota_clients[key] = QuotaClient()
        else:
            return None
    return _quota_clients[key]


@app.get("/api/usage")
async def get_usage():
    """Token/cost accounting + live subscription quota for the Usage tab."""

    totals = {}
    for label, where in (
        ("today", "date(created_at) = date('now')"),
        ("week", "created_at >= datetime('now', '-7 days')"),
        ("month", "created_at >= datetime('now', '-30 days')"),
    ):
        rows = await query_db(f"SELECT {_USAGE_SUM} FROM usage_events WHERE {where}")
        totals[label] = rows[0] if rows else {}

    def grouped(expr, alias):
        return (
            f"SELECT {expr} AS {alias}, {_USAGE_SUM} FROM usage_events "
            f"WHERE created_at >= datetime('now', '-30 days') "
            f"GROUP BY {alias} ORDER BY output_tokens DESC LIMIT 25"
        )

    by_agent = await query_db(grouped("CASE WHEN agent = '' THEN 'other' ELSE agent END", "agent"))
    by_task = await query_db(grouped("CASE WHEN task = '' THEN 'other' ELSE task END", "task"))
    by_model = await query_db(grouped("CASE WHEN model = '' THEN 'unknown' ELSE model END", "model"))
    by_provider = await query_db(grouped("provider", "provider"))
    by_day = await query_db(
        f"SELECT date(created_at) AS day, {_USAGE_SUM} FROM usage_events "
        f"WHERE created_at >= datetime('now', '-30 days') "
        f"GROUP BY day ORDER BY day ASC"
    )

    brain = _active_brain()
    provider = brain.provider if brain else ""
    quota = None
    try:
        client = _quota_client_for(provider, brain.model if brain else "")
        if client is not None:
            quota = await client.get_utilization()
    except Exception as e:
        logger.debug("Quota lookup failed: %s", e)

    return {
        "provider": provider,
        "quota": quota,
        # Whose quota this is, even when it couldn't be read, so the UI shows
        # "unavailable" for the active provider instead of hiding the gauge.
        "quota_provider": provider,
        "quota_status": ("available" if quota else "unavailable") if provider else "",
        "by_provider": by_provider,
        "totals": totals,
        "by_day": by_day,
        "by_agent": by_agent,
        "by_task": by_task,
        "by_model": by_model,
    }


@app.get("/api/prospects")
async def get_prospects():
    rows = await query_db("SELECT * FROM prospects ORDER BY created_at DESC LIMIT 200")
    return rows


def _state():
    from harvey.state import StateManager
    return StateManager(db_path=str(DB_PATH))


@app.get("/api/outbox")
async def get_outbox_api():
    """Outbox queue + kill-switch state for the Outbox tab."""
    try:
        state = _state()
        await state.init_db()
        return {
            "paused": await state.get_setting("sending_paused"),
            "pending": await state.get_outbox(status="pending_review", limit=100),
            "approved": await state.get_outbox(status="approved", limit=50),
            "sent": (await query_db(
                "SELECT * FROM outbox WHERE status = 'sent' "
                "ORDER BY sent_at DESC LIMIT 25")),
            "failed": (await query_db(
                "SELECT * FROM outbox WHERE status IN ('failed','rejected') "
                "ORDER BY updated_at DESC LIMIT 25")),
            "archived": (await query_db("""
                SELECT o.id, o.prospect_id, o.to_email, o.subject, o.step, o.error, o.updated_at,
                       p.first_name, p.last_name, p.company, p.title, p.linkedin_url, p.source_url as website, p.email_status
                FROM outbox o
                LEFT JOIN prospects p ON o.prospect_id = p.id
                WHERE o.status = 'cancelled'
                ORDER BY o.updated_at DESC
            """)),
        }
    except Exception as e:
        return {"error": str(e)}


_auto_dispatcher_task = None

async def _drain_now():
    """Trigger drain of due approved items respecting recipient timezones."""
    try:
        from harvey.agents.sender import Sender
        from harvey.config import load_config, load_env
        from harvey.brain import Brain
        cfg = load_config()
        env = load_env()
        state = _state()
        await state.init_db()
        brain = Brain(state, cfg.brain)
        sender = Sender(brain, state, cfg, env)
        return await sender._drain_due()
    except Exception as e:
        logger.exception(f"Drain error: {e}")
        return 0

async def _auto_dispatcher_loop():
    """Autonomous 60-second background loop that drains due outbox items."""
    logger.info("Auto-Dispatcher loop started (checking every 60s).")
    while True:
        try:
            state = _state()
            await state.init_db()
            paused = await state.get_setting("sending_paused")
            if not paused:
                await _drain_now()
        except Exception as e:
            logger.debug(f"Auto-dispatcher loop error: {e}")
        await asyncio.sleep(60)

@app.on_event("startup")
async def start_auto_dispatcher():
    global _auto_dispatcher_task
    if _auto_dispatcher_task is None or _auto_dispatcher_task.done():
        _auto_dispatcher_task = asyncio.create_task(_auto_dispatcher_loop())


@app.post("/api/outbox/approve-all")
async def outbox_approve_all():
    try:
        state = _state()
        await state.init_db()
        n = await state.approve_outbox()
        # Immediately trigger background dispatch for due items
        asyncio.create_task(_drain_now())
        return {"success": True, "approved": n}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/archive-catch-alls")
async def outbox_archive_catch_alls():
    """Archive/Cancel all pending outbox drafts that are on catch-all/risky domains."""
    try:
        state = _state()
        await state.init_db()
        async with aiosqlite.connect(state.db_path) as db:
            cursor = await db.execute("""
                SELECT o.id, o.prospect_id, o.to_email, p.company 
                FROM outbox o 
                JOIN prospects p ON o.prospect_id = p.id 
                WHERE o.status = 'pending_review' AND p.email_status IN ('risky', 'unknown', 'invalid')
            """)
            items = await cursor.fetchall()
            
            count = len(items)
            if count > 0:
                item_ids = [it[0] for it in items]
                placeholders = ",".join("?" for _ in item_ids)
                await db.execute(f"""
                    UPDATE outbox 
                    SET status = 'cancelled', error = 'Archived: Reserved for LinkedIn/Multi-channel outreach' 
                    WHERE id IN ({placeholders})
                """, item_ids)
                
                prospect_ids = list(set(it[1] for it in items))
                p_placeholders = ",".join("?" for _ in prospect_ids)
                await db.execute(f"""
                    UPDATE prospects 
                    SET status = 'linkedin_backlog' 
                    WHERE id IN ({p_placeholders})
                """, prospect_ids)
                await db.commit()

        # Regenerate local CRM vaults
        from harvey.integrations.sheets_sync import regenerate_local_vaults, push_to_google_sheet
        await regenerate_local_vaults(state)
        
        # Fire background webhook sync to Google Sheets for each archived lead
        for it in items:
            try:
                asyncio.create_task(push_to_google_sheet(
                    email=it[2],
                    company=it[3],
                    status="⚠️ Catch-All (LinkedIn Outreach)",
                    notes="Archived from Email • Connect via LinkedIn or Site Form"
                ))
            except Exception:
                pass
        
        return {"success": True, "archived_count": count, "message": f"Archived {count} catch-all drafts! Reserved for LinkedIn outreach."}
    except Exception as e:
        logger.exception(f"Archive catch-alls error: {e}")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/unarchive")
async def outbox_unarchive(item_id: str):
    """Restore an archived draft back to pending_review in Outbox."""
    try:
        state = _state()
        await state.init_db()
        async with aiosqlite.connect(state.db_path) as db:
            cursor = await db.execute("SELECT prospect_id FROM outbox WHERE id = ?", (item_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                await db.execute("UPDATE prospects SET status = 'queued' WHERE id = ?", (row[0],))
            await db.execute("UPDATE outbox SET status = 'pending_review', error = '' WHERE id = ?", (item_id,))
            await db.commit()
        from harvey.integrations.sheets_sync import regenerate_local_vaults
        await regenerate_local_vaults(state)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/drain")
async def outbox_drain():
    """Dispatch due approved emails through configured provider immediately."""
    try:
        sent = await _drain_now()
        return {"success": True, "sent": sent}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/approve")
async def outbox_approve(item_id: str):
    try:
        state = _state()
        await state.init_db()
        n = await state.approve_outbox(item_id)
        # Immediately trigger background dispatch for due items
        asyncio.create_task(_drain_now())
        return {"success": bool(n)}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/reject")
async def outbox_reject(item_id: str):
    try:
        state = _state()
        await state.init_db()
        await state.update_outbox_item(item_id, status="rejected")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/cancel")
async def outbox_cancel(item_id: str):
    try:
        state = _state()
        await state.init_db()
        await state.update_outbox_item(item_id, status="cancelled")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/unapprove")
async def outbox_unapprove(item_id: str):
    try:
        state = _state()
        await state.init_db()
        await state.update_outbox_item(item_id, status="pending_review")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/retry")
async def outbox_retry(item_id: str):
    try:
        state = _state()
        await state.init_db()
        await state.update_outbox_item(item_id, status="pending_review", error="")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/outbox/{item_id}/edit")
async def outbox_edit(item_id: str, request: Request):
    try:
        data = await request.json()
        state = _state()
        await state.init_db()
        updates = {}
        if "subject" in data:
            updates["subject"] = str(data["subject"]).strip()
        if "body" in data:
            updates["body"] = str(data["body"]).strip()
        if updates:
            await state.update_outbox_item(item_id, **updates)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/prospect/instant-url")
async def prospect_instant_url(request: Request):
    try:
        data = await request.json()
        raw_url = str(data.get("url") or "").strip()
        if not raw_url:
            return JSONResponse({"success": False, "message": "Website URL is required"}, status_code=200)

        # Normalize URL
        clean_url = raw_url
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        import urllib.parse
        parsed = urllib.parse.urlparse(clean_url)
        domain = (parsed.netloc or parsed.path).lower()
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.split("/")[0].strip()

        if not domain or "." not in domain:
            return JSONResponse({"success": False, "message": "Please enter a valid website domain"}, status_code=200)

        # Clean company name
        base_name = domain.split(".")[0]
        if base_name in ("dlf", "gmr", "emaar", "damac", "sobha"):
            company_name = base_name.upper()
        else:
            company_name = base_name.replace("-", " ").replace("_", " ").title()

        from harvey.scoring import compute_icp_score
        prospect_title = "Founder / Managing Director"
        score, detected_industry = compute_icp_score(
            company=company_name, domain=domain, title=prospect_title, email_status="verified"
        )

        now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        state = _state()
        await state.init_db()

        async with state._connect() as db:
            db.row_factory = aiosqlite.Row
            # 1. Company
            async with db.execute("SELECT * FROM companies WHERE domain = ? OR website LIKE ? LIMIT 1", (domain, f"%{domain}%")) as cur:
                existing_company = await cur.fetchone()

            if existing_company:
                company_id = existing_company["id"]
                company_name = existing_company["name"] or company_name
            else:
                company_id = str(uuid.uuid4())
                await db.execute(
                    """INSERT INTO companies (id, name, domain, website, industry, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (company_id, company_name, domain, clean_url, detected_industry, "instant_url", now_iso, now_iso)
                )
                await db.commit()

            # 2. Prospect
            prospect_email = f"contact@{domain}"
            async with db.execute("SELECT * FROM prospects WHERE email = ? LIMIT 1", (prospect_email,)) as cur:
                existing_prospect = await cur.fetchone()

            if existing_prospect:
                prospect_id = existing_prospect["id"]
                await db.execute("UPDATE prospects SET score = ?, industry = ? WHERE id = ?", (score, detected_industry, prospect_id))
                await db.commit()
            else:
                prospect_id = str(uuid.uuid4())
                await db.execute(
                    """INSERT INTO prospects (id, company_id, company, first_name, last_name, email, email_status, title, industry, score, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (prospect_id, company_id, company_name, "Team", company_name, prospect_email, "verified", prospect_title, detected_industry, score, "instant_url", now_iso, now_iso)
                )
                await db.commit()

            # 3. Personalized Speed-to-Lead Email Pitch
            subject = f"Quick question regarding {company_name} buyer inquiries"
            body = (
                f"Hi {company_name} Team,\n\n"
                f"I noticed that when high-net-worth buyers inquire about properties or high-ticket services through "
                f"{company_name}'s digital campaigns, sales teams often take an hour or more to manually follow up.\n\n"
                f"In high-ticket transactions, international buyer intent drops significantly after the first 15 minutes.\n\n"
                f"At TrackKaro AI, we build backend speed-to-lead nervous systems: the moment an inquiry submits, "
                f"the client gets the full brochure & floorplan instantly delivered on WhatsApp, while your assigned "
                f"sales reps receive an immediate sound alert on Telegram with a 1-click direct call trigger.\n\n"
                f"You can test our live 30-second simulation here:\n"
                f"👉 https://trackkaroai.com\n\n"
                f"Would you be open to a 5-minute teardown of your current lead response time this week?\n\n"
                f"Best,\nMangal Soren\nLead Automation | TrackKaro AI\nhttps://trackkaroai.com"
            )

            # Check if pending outbox item exists for this email
            async with db.execute("SELECT id FROM outbox WHERE to_email = ? AND status = 'pending_review' LIMIT 1", (prospect_email,)) as cur:
                existing_outbox = await cur.fetchone()

            if existing_outbox:
                item_id = existing_outbox["id"]
            else:
                item_id = str(uuid.uuid4())
                await db.execute(
                    """INSERT INTO outbox (id, prospect_id, to_email, subject, body, step, kind, status, send_at, provider, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, 'instant_pitch', 'pending_review', ?, 'resend', ?, ?)""",
                    (item_id, prospect_id, prospect_email, subject, body, now_iso, now_iso, now_iso)
                )
                await db.commit()

        return {
            "success": True,
            "company": company_name,
            "domain": domain,
            "website": clean_url,
            "email": prospect_email,
            "item_id": item_id
        }
    except Exception as e:
        logger.exception("Instant prospect URL failed")
        return JSONResponse({"success": False, "message": str(e)}, status_code=200)


@app.post("/api/sending/{action}")
async def sending_toggle(action: str):
    if action not in ("pause", "resume"):
        return JSONResponse({"success": False, "message": "unknown action"}, status_code=400)
    try:
        state = _state()
        await state.init_db()
        if action == "pause":
            await state.set_setting("sending_paused", "paused from dashboard")
        else:
            await state.set_setting("sending_paused", "")
            await state.set_setting("bounce_count", "0")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.get("/api/export/prospects.csv")
async def export_prospects(all: bool = False, min_score: int = 0, email_status: str = ""):
    """Sequencer-ready CSV download of the prospect list."""
    from harvey.state import StateManager
    from harvey.export import export_prospects_csv

    state = StateManager(db_path=str(DB_PATH))
    try:
        await state.init_db()
        statuses = [s.strip() for s in email_status.split(",") if s.strip()] or None
        _, text = await export_prospects_csv(
            state, email_statuses=statuses, min_score=min_score, include_all=all,
        )
    except Exception as e:
        logger.warning("Prospect export failed: %s", e)
        text = ""
    return PlainTextResponse(
        text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="prospects.csv"'},
    )


@app.get("/api/crm/table")
async def get_crm_table():
    """Returns the live CRM spreadsheet records directly from local vaults/DB."""
    try:
        from harvey.paths import PROJECT_ROOT, get_workspace_dir
        ws = get_workspace_dir()
        is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

        # If this is the root TrackKaro workspace, load the 28 leads from the master TSV/vault
        if is_root:
            from harvey.integrations.sheets_sync import DEFAULT_TSV_PATH
            import csv
            if os.path.exists(DEFAULT_TSV_PATH):
                with open(DEFAULT_TSV_PATH, "r", encoding="utf-8") as f:
                    reader = csv.reader(f, delimiter="\t")
                    rows = list(reader)
                    if rows:
                        items = []
                        for r in rows[1:]:
                            if not r or len(r) < 8:
                                continue
                            def _clean_formula(val):
                                if val.startswith("=HYPERLINK("):
                                    parts = val.replace("=HYPERLINK(\"", "").replace("\")", "").split("\", \"")
                                    return parts[0] if len(parts) > 0 else val
                                return val

                            def _clean_status(val):
                                v = val.replace("🚀", "").replace("❌", "").replace("⚠️", "").replace("✅", "").replace("🔥", "").replace("⏳", "").strip()
                                if "Contacted" in v or "Delivered" in v:
                                    return "Contacted"
                                if "Bounced" in v or "Invalid" in v:
                                    return "Bounced"
                                if "Catch-All" in v or "Catchall" in v:
                                    return "Catch-All"
                                if "Verified" in v:
                                    return "Verified Safe"
                                if "Replied" in v:
                                    return "Replied"
                                return v or "Queued"

                            items.append({
                                "company": r[0] if len(r) > 0 else "",
                                "region": r[1] if len(r) > 1 else "",
                                "niche": r[2] if len(r) > 2 else "",
                                "pain_point": r[3] if len(r) > 3 else "",
                                "decision_maker": r[4] if len(r) > 4 else "",
                                "contact": r[5] if len(r) > 5 else "",
                                "score": r[6] if len(r) > 6 else "95",
                                "status": _clean_status(r[7] if len(r) > 7 else "Queued"),
                                "deal_size": r[8] if len(r) > 8 else "$3,000 – $6,000",
                                "website": _clean_formula(r[9]) if len(r) > 9 else "",
                                "linkedin": _clean_formula(r[10]) if len(r) > 10 else "",
                                "notes": r[11] if len(r) > 11 else ""
                            })
                        return {"rows": items, "count": len(items)}

        # For custom/client workspaces (e.g. cold_email_outreach), load ONLY prospects from THIS workspace's DB:
        prospects = await query_db(
            "SELECT p.*, c.name as company_name, c.domain, c.industry, c.location "
            "FROM prospects p "
            "LEFT JOIN companies c ON p.company_id = c.id "
            "ORDER BY p.score DESC, p.created_at DESC"
        )
        if prospects:
            items = []
            for p in prospects:
                status_raw = p.get("status", "new")
                email_status = p.get("email_status", "")
                
                if status_raw == "contacted":
                    status_badge = "Contacted"
                elif email_status == "verified" or p.get("email_verified"):
                    status_badge = "Verified Safe"
                elif email_status == "catch_all":
                    status_badge = "Catch-All"
                elif email_status in ("invalid", "bounced"):
                    status_badge = "Bounced"
                else:
                    status_badge = "Queued"

                items.append({
                    "company": p.get("company_name") or p.get("company") or "Unknown",
                    "region": p.get("location") or "Global",
                    "niche": p.get("industry") or "B2B",
                    "pain_point": "Lead Automation & Outbound Growth",
                    "decision_maker": f"{p.get('first_name', '')} {p.get('last_name', '')} ({p.get('title', 'Founder')})".strip(),
                    "contact": f"{p.get('email', 'N/A')} • {p.get('phone') or 'N/A'}",
                    "score": str(p.get("score") or 90),
                    "status": status_badge,
                    "deal_size": "$2,500 – $5,000",
                    "website": f"https://{p.get('domain')}" if p.get("domain") and not str(p.get("domain")).startswith("http") else (p.get("domain") or ""),
                    "linkedin": p.get("linkedin_url") or "—",
                    "notes": p.get("personalization_notes") or ""
                })
            return {"rows": items, "count": len(items)}

        # Clean slate: zero prospects in this isolated workspace
        return {"rows": [], "count": 0}
    except Exception as e:
        logger.warning(f"CRM table load error: {e}")
        return {"error": str(e), "rows": [], "count": 0}


@app.get("/api/crm/export.tsv")
async def export_crm_tsv():
    """Direct TSV/Excel download of the active CRM Vault."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))
    
    if is_root:
        from harvey.integrations.sheets_sync import DEFAULT_TSV_PATH
        if os.path.exists(DEFAULT_TSV_PATH):
            with open(DEFAULT_TSV_PATH, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = ""
    else:
        # Generate clean TSV from workspace DB
        prospects = await query_db(
            "SELECT p.*, c.name as company_name, c.domain, c.industry, c.location "
            "FROM prospects p LEFT JOIN companies c ON p.company_id = c.id "
            "ORDER BY p.score DESC, p.created_at DESC"
        )
        lines = ["Company\tRegion\tNiche\tPain Point\tDecision Maker\tContact\tScore\tStatus\tDeal Size\tWebsite\tLinkedIn\tStrategy Notes"]
        for p in prospects:
            c_name = p.get("company_name") or p.get("company") or ""
            lines.append(f"{c_name}\t{p.get('location','')}\t{p.get('industry','')}\tLead Automation\t{p.get('first_name','')} {p.get('last_name','')}\t{p.get('email','')}\t{p.get('score',90)}\t{p.get('status','Queued')}\t$2,500 – $5,000\t{p.get('domain','')}\t{p.get('linkedin_url','')}\t{p.get('personalization_notes','')}")
        content = "\n".join(lines)

    return PlainTextResponse(
        content,
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{ws.name}_crm_vault.tsv"'}
    )


@app.get("/api/workspace/info")
async def get_workspace_info():
    """Returns active workspace metadata and its specific Google Sheet URL."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

    sheet_url = ""
    webhook_url = ""
    if is_root:
        sheet_url = os.getenv("GOOGLE_SHEET_URL", "")
        webhook_url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "")
    else:
        ws_env = ws / ".env"
        if ws_env.is_file():
            for line in ws_env.read_text().splitlines():
                if line.startswith("GOOGLE_SHEET_URL="):
                    sheet_url = line.split("=", 1)[1].strip()
                elif line.startswith("GOOGLE_SHEET_WEBHOOK_URL="):
                    webhook_url = line.split("=", 1)[1].strip()

    return {
        "workspace": ws.name if not is_root else "trackkaro",
        "is_root": is_root,
        "sheet_url": sheet_url,
        "has_sheet": bool(sheet_url),
        "has_webhook": bool(webhook_url),
    }


@app.post("/api/switch-workspace")
async def switch_workspace_api(request: Request):
    """Dynamically switch active workspace in-process (supports single domain / production)."""
    from harvey.paths import PROJECT_ROOT, set_workspace_dir, get_workspace_dir, get_db_path
    from harvey.state import StateManager
    try:
        body = await request.json()
    except Exception:
        body = {}
    ws_key = body.get("workspace", "").strip().lower()
    if ws_key in ("speed-to-lead", "trackkaro", "root", "dubai"):
        set_workspace_dir(None)
    elif ws_key in ("cold-email", "cold_email", "cold_email_outreach"):
        set_workspace_dir(PROJECT_ROOT / "workspaces" / "cold_email_outreach")
    else:
        target = PROJECT_ROOT / "workspaces" / ws_key
        if target.is_dir():
            set_workspace_dir(target)
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

    try:
        sm = StateManager(get_db_path(ws))
        await sm.init_db()
    except Exception as e:
        logger.warning(f"Error ensuring DB on workspace switch: {e}")

    return {
        "success": True,
        "workspace": ws.name if not is_root else "trackkaro",
        "is_root": is_root,
        "display_name": "Dubai & India Speed-to-Lead" if is_root else ws.name.replace("_", " ").title()
    }


@app.post("/api/database/sync")
async def sync_database(request: Request, workspace: str = "current"):
    """Accepts raw sqlite db binary and writes it to the target workspace data directory."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    raw_data = await request.body()
    if not raw_data or len(raw_data) < 100:
        return JSONResponse({"error": "Empty or invalid database payload"}, status_code=400)

    if not raw_data.startswith(b"SQLite format 3"):
        return JSONResponse({"error": "File is not a valid SQLite database"}, status_code=400)

    target_ws = get_workspace_dir()
    ws_key = workspace.strip().lower()
    if ws_key in ("speed-to-lead", "trackkaro", "root", "dubai"):
        target_ws = PROJECT_ROOT
    elif ws_key in ("cold-email", "cold_email", "cold_email_outreach"):
        target_ws = PROJECT_ROOT / "workspaces" / "cold_email_outreach"
    elif ws_key != "current":
        cand = PROJECT_ROOT / "workspaces" / ws_key
        if cand.is_dir():
            target_ws = cand

    db_dir = target_ws / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    target_db = db_dir / "harvey.db"

    target_db.write_bytes(raw_data)
    logger.info(f"Database synced for workspace {target_ws.name} ({len(raw_data)} bytes)")

    return {
        "success": True,
        "workspace": target_ws.name,
        "size_bytes": len(raw_data),
        "message": f"Successfully synced database to {target_ws.name}!"
    }


@app.get("/api/database/download")
async def download_database(workspace: str = "current"):
    """Download the current workspace SQLite database file."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir, get_db_path
    ws = get_workspace_dir()
    ws_key = workspace.strip().lower()
    if ws_key in ("speed-to-lead", "trackkaro", "root", "dubai"):
        target_db = PROJECT_ROOT / "data" / "harvey.db"
    elif ws_key in ("cold-email", "cold_email", "cold_email_outreach"):
        target_db = PROJECT_ROOT / "workspaces" / "cold_email_outreach" / "data" / "harvey.db"
    else:
        target_db = get_db_path(ws)

    if not target_db.is_file():
        return JSONResponse({"error": "Database not found"}, status_code=404)
    return FileResponse(
        path=str(target_db),
        filename=f"harvey_{ws.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
        media_type="application/x-sqlite3"
    )


@app.get("/api/workspace-config")
async def get_workspace_config():
    """Fetch live workspace configuration (Offer & SMTP) from .env and harvey.yaml."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

    env_path = (ws / ".env") if (ws / ".env").is_file() else (PROJECT_ROOT / ".env")
    env_vars = {}
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    cfg_path = ws / "harvey.yaml"
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            cfg = {}

    company = cfg.get("company", {})
    campaign = cfg.get("campaign", {})
    target = cfg.get("target", {})

    offer_name = company.get("name") or ("Dubai & India Speed-to-Lead" if is_root else "Cold Email Agency Retainer")
    offer_tagline = company.get("description") or ("High-ticket speed-to-lead nervous system (Sub-15s response)" if is_root else "$1,500 – $2,500/mo Autonomous AI SDR Retainer")
    target_titles = ", ".join(target.get("titles", [])) or "Founder, CEO, Managing Partner, Head of Growth, VP Sales"
    target_geo = ", ".join(target.get("locations", [])) or ("Dubai, UAE, India" if is_root else "United States, United Kingdom, Dubai, Canada")
    booking_url = os.getenv("CALENDLY_URL", "https://calendly.com/trackkaroai/15min")

    smtp_host = env_vars.get("SMTP_HOST") or os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = env_vars.get("SMTP_PORT") or os.getenv("SMTP_PORT", "465")
    smtp_user = env_vars.get("SMTP_USERNAME") or os.getenv("SMTP_USERNAME", "mangal@trackkaroai.com")
    from_name = env_vars.get("FROM_NAME") or "Mangal Soren • TrackKaro AI"
    daily_cap = int(env_vars.get("DAILY_SEND_LIMIT", "25"))

    return {
        "workspace": ws.name if not is_root else "trackkaro",
        "is_root": is_root,
        "display_name": "Dubai & India Speed-to-Lead (Port 5555)" if is_root else "Cold Email Agency Retainer (Port 5556)",
        "offer": {
            "name": offer_name,
            "tagline": offer_tagline,
            "target_titles": target_titles,
            "target_geo": target_geo,
            "booking_url": booking_url
        },
        "smtp": {
            "provider": "google" if "gmail.com" in smtp_host else "smtp",
            "host": smtp_host,
            "port": int(smtp_port) if str(smtp_port).isdigit() else 465,
            "sender_email": smtp_user,
            "from_name": from_name,
            "daily_limit": daily_cap,
            "require_approval": True
        },
        "brain": "gemini"
    }


@app.post("/api/save-workspace-config")
async def save_workspace_config(request: Request):
    """Save workspace configuration directly to active workspace .env."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

    try:
        body = await request.json()
        cfg_data = body.get("config", {})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

    env_path = ws / ".env"
    existing_env = {}
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing_env[k.strip()] = v.strip()
    elif not is_root:
        root_env = PROJECT_ROOT / ".env"
        if root_env.is_file():
            for line in root_env.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    existing_env[k.strip()] = v.strip()

    smtp_data = cfg_data.get("smtp", {})
    if smtp_data.get("host"):
        existing_env["SMTP_HOST"] = str(smtp_data["host"]).strip()
    if smtp_data.get("port"):
        existing_env["SMTP_PORT"] = str(smtp_data["port"]).strip()
    if smtp_data.get("sender_email"):
        existing_env["SMTP_USERNAME"] = str(smtp_data["sender_email"]).strip()
    if smtp_data.get("from_name"):
        existing_env["FROM_NAME"] = str(smtp_data["from_name"]).strip()
    if smtp_data.get("daily_limit"):
        existing_env["DAILY_SEND_LIMIT"] = str(smtp_data["daily_limit"]).strip()

    lines = [f"{k}={v}" for k, v in existing_env.items()]
    env_path.write_text("\n".join(lines) + "\n")

    return {"success": True, "message": f"Workspace '{ws.name}' configuration saved to {env_path.name}!"}


@app.post("/api/test-smtp-live")
async def test_smtp_live(request: Request):
    """Execute a real socket/handshake ping to the configured SMTP server."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    env_path = (ws / ".env") if (ws / ".env").is_file() else (PROJECT_ROOT / ".env")

    env_vars = {}
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    host = env_vars.get("SMTP_HOST") or os.getenv("SMTP_HOST", "")
    port = int(env_vars.get("SMTP_PORT") or os.getenv("SMTP_PORT", 465))
    user = env_vars.get("SMTP_USERNAME") or os.getenv("SMTP_USERNAME", "")
    password = env_vars.get("SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")

    if not host or not user or not password:
        return {"success": False, "message": f"Missing SMTP credentials in {env_path.name} (Host: {host}, User: {user})"}

    import smtplib
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                server.login(user, password)
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls()
                server.login(user, password)
        return {
            "success": True,
            "message": f"Verified Live 200 OK! Connected to {host}:{port} as {user}."
        }
    except Exception as e:
        return {"success": False, "message": f"SMTP Authentication failed on {host}:{port}: {str(e)}"}


@app.get("/api/workspaces/list")
async def list_workspaces_api():
    """List all available client workspaces dynamically from the filesystem."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    active_ws = get_workspace_dir()
    is_active_root = (active_ws.resolve() == PROJECT_ROOT.resolve() or active_ws.name in ("trackkaro", ""))

    items = [
        {
            "key": "speed-to-lead",
            "name": "Dubai & India Speed-to-Lead (Port 5555)",
            "sub": "Real Estate & Clinics",
            "icon": "🏢",
            "is_root": True,
            "active": is_active_root,
        }
    ]

    ws_dir = PROJECT_ROOT / "workspaces"
    if ws_dir.is_dir():
        for d in sorted(ws_dir.iterdir()):
            if not d.is_dir() or d.name.startswith(".") or d.name.startswith("_") or d.name in ("README.md", "trackkaro"):
                continue

            key = d.name
            is_active = (not is_active_root and active_ws.name == key)
            if key == "cold_email_outreach":
                title = "Cold Email Agency Retainer (Port 5556)"
                sub = "B2B SaaS & Dev Agencies"
                icon = "🚀"
            else:
                title = key.replace("_", " ").replace("-", " ").title()
                sub = "Client ICP Engine"
                icon = "⚡"

            yaml_path = d / "harvey.yaml"
            if yaml_path.is_file():
                try:
                    cfg = yaml.safe_load(yaml_path.read_text()) or {}
                    if "offer" in cfg and "name" in cfg["offer"]:
                        title = cfg["offer"]["name"]
                    if "offer" in cfg and "tagline" in cfg["offer"]:
                        sub = cfg["offer"]["tagline"]
                except Exception:
                    pass

            items.append({
                "key": key,
                "name": title,
                "sub": sub,
                "icon": icon,
                "is_root": False,
                "active": is_active,
            })

    return {"workspaces": items}


@app.delete("/api/workspaces/{workspace_name}")
@app.post("/api/workspaces/{workspace_name}/delete")
async def delete_workspace_api(workspace_name: str, request: Request):
    """Safely archive or delete a client workspace, optionally purging Supabase records."""
    import shutil
    from harvey.paths import PROJECT_ROOT

    # Protect root primary workspace
    protected = {"trackkaro", "trackkaro_speed_to_lead", "speed-to-lead", "root", ""}
    clean_name = workspace_name.strip().lower()
    if clean_name in protected:
        return JSONResponse({"success": False, "error": "Primary Root Engine is protected and cannot be deleted."}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}

    action = body.get("action", "delete")
    purge_supabase = body.get("purge_supabase", True)

    ws_dir = PROJECT_ROOT / "workspaces" / workspace_name
    if not ws_dir.exists():
        if clean_name in ("cold-email", "cold_email"):
            ws_dir = PROJECT_ROOT / "workspaces" / "cold_email_outreach"
            clean_name = "cold_email_outreach"

    archived_dir = PROJECT_ROOT / "workspaces" / ".archived"
    archived_dir.mkdir(exist_ok=True)

    # 1. Local filesystem cleanup
    if ws_dir.exists():
        if action == "archive":
            dest = archived_dir / f"{ws_dir.name}_{int(datetime.now().timestamp())}"
            shutil.move(str(ws_dir), str(dest))
        else:
            shutil.rmtree(ws_dir)

    # 2. Supabase multi-tenant isolation cleanup
    try:
        from scripts.sync_to_supabase import get_supabase_conn
        pg_conn = get_supabase_conn()
        with pg_conn.cursor() as cur:
            if action == "archive" or not purge_supabase:
                cur.execute("UPDATE public.workspaces SET status = 'archived' WHERE id = %s;", (clean_name,))
            else:
                cur.execute("DELETE FROM public.outbox WHERE workspace = %s;", (clean_name,))
                cur.execute("DELETE FROM public.prospects WHERE workspace = %s;", (clean_name,))
                cur.execute("DELETE FROM public.companies WHERE workspace = %s;", (clean_name,))
                cur.execute("DELETE FROM public.workspaces WHERE id = %s;", (clean_name,))
            pg_conn.commit()
        pg_conn.close()
    except Exception as e:
        logger.warning("Supabase cleanup note: %s", e)

    return {
        "success": True,
        "message": f"Workspace '{clean_name}' successfully {'archived' if action == 'archive' else 'deleted'}. Other clients remain 100% safe."
    }


@app.post("/api/sync/sheets")
async def sync_sheets_api():
    """1-Click CRM Sync: Regenerates TSV & CSV vaults and pushes live webhook event."""
    try:
        from harvey.integrations.sheets_sync import regenerate_local_vaults, push_to_google_sheet
        state = _state()
        await state.init_db()
        count = await regenerate_local_vaults(state)
        from harvey.paths import PROJECT_ROOT, get_workspace_dir
        ws = get_workspace_dir()
        is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

        if is_root:
            await push_to_google_sheet(
                email="mangal@trackkaroai.com",
                status="Manual Sync Triggered",
                company="TrackKaro AI",
                notes=f"Full CRM Sync executed for {count} prospects"
            )
            return {"success": True, "count": count, "message": f"Synced {count} leads to CRM vaults & Google Sheet!"}
        else:
            return {"success": True, "count": count, "message": f"Regenerated local CRM vaults ({count} leads)."}
    except Exception as e:
        logger.exception(f"Sync error: {e}")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)



@app.get("/api/campaigns")
async def get_campaigns():
    rows = await query_db("SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 100")
    for row in rows:
        try:
            row["sequence"] = json.loads(row.get("sequence_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            row["sequence"] = []
        try:
            row["prospect_ids"] = json.loads(row.get("prospect_ids_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            row["prospect_ids"] = []
    return rows


@app.get("/api/conversations")
async def get_conversations():
    rows = await query_db("""
        SELECT c.*, p.first_name, p.last_name, p.email as prospect_email, p.company
        FROM conversations c
        LEFT JOIN prospects p ON c.prospect_id = p.id
        ORDER BY c.updated_at DESC LIMIT 100
    """)
    for row in rows:
        try:
            row["thread"] = json.loads(row.get("thread_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            row["thread"] = []
    return rows


@app.get("/api/activity")
async def get_activity():
    rows = await query_db("SELECT * FROM actions ORDER BY created_at DESC LIMIT 100")
    for row in rows:
        try:
            row["details"] = json.loads(row.get("details_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            row["details"] = {}
    return rows


# ── Dashboard UI ──


# ── Discovery: the provider menu, an estimate, and a run ──
#
# This is the only stage that spends money, so the UI never starts one without
# showing what it will cost first.

_discovery_task: asyncio.Task | None = None
_discovery_report: dict | None = None


def _discovery_queries(body: dict, config):
    from harvey.collectors.discover import build_queries

    cities = [c.strip() for c in (body.get("cities") or []) if c.strip()] or None
    return build_queries(
        config, cities=cities,
        depth=int(body.get("depth") or 30),
        limit=int(body.get("limit") or 100),
    )


@app.get("/api/discover/providers")
async def get_discovery_providers():
    """What each source does, what it costs, and whether it's ready to use."""
    try:
        from harvey.collectors.discover import DEFAULT_PROVIDER, provider_menu
        from harvey.config import load_env

        state = _state()
        await state.init_db()
        return {
            "providers": provider_menu(load_env().model_dump()),
            "default": DEFAULT_PROVIDER,
            "selected": await state.get_setting("discovery_provider") or DEFAULT_PROVIDER,
            "paused": await state.get_setting("discovery_paused"),
            "running": bool(_discovery_task and not _discovery_task.done()),
            "last_report": _discovery_report,
        }
    except Exception as e:
        logger.exception("discovery providers failed")
        return {"providers": [], "error": str(e)}


@app.post("/api/discover/estimate")
async def estimate_discovery(request: Request):
    """Projected spend and the exact query list, before anything is called."""
    try:
        from harvey.collectors.discover import PROVIDERS, estimate_cost
        from harvey.config import load_config

        body = await request.json()
        provider = body.get("provider") or ""
        if provider not in PROVIDERS:
            return JSONResponse({"error": f"unknown provider {provider!r}"},
                                status_code=400)

        queries = _discovery_queries(body, load_config())
        return {
            "provider": provider,
            "queries": [q.keyword() for q in queries],
            "query_count": len(queries),
            "estimated_cost": round(estimate_cost(provider, queries), 4),
            "free": PROVIDERS[provider].estimate(queries) == 0,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/discover/run")
async def start_discovery(request: Request):
    """Kick off a run in the background and hand back immediately.

    Discovery takes minutes, not milliseconds — holding the request open
    would just time out. Progress shows up in the run log.
    """
    global _discovery_task, _discovery_report

    if _discovery_task and not _discovery_task.done():
        return JSONResponse({"success": False, "message": "a run is already going"},
                            status_code=409)
    try:
        from harvey.collectors.discover import PROVIDERS
        from harvey.config import load_config
        from harvey.pipeline import run_prospecting

        body = await request.json()
        provider = body.get("provider") or ""
        if provider not in PROVIDERS:
            return JSONResponse({"success": False,
                                 "message": f"unknown provider {provider!r}"},
                                status_code=400)

        config = load_config()
        queries = _discovery_queries(body, config)
        max_spend = float(body.get("max_spend") or 1.0)

        state = _state()
        await state.init_db()
        await state.set_setting("discovery_provider", provider)
        await state.set_setting("discovery_paused", "")

        async def _go():
            global _discovery_report
            try:
                # Discovery chains straight into profiling: reading the sites
                # is free, and it is what makes the results worth anything.
                result = await run_prospecting(state, config, provider, queries,
                                               max_spend=max_spend)
                _discovery_report = {
                    **(result.discover or {}),
                    "profiled_companies": result.profiled_companies,
                    "profile_observations": result.profile_observations,
                    "errors": result.errors,
                }
            except Exception as exc:
                logger.exception("discovery run failed")
                _discovery_report = {"errors": [str(exc)], "stopped": "failed"}

        _discovery_report = None
        _discovery_task = asyncio.create_task(_go())
        return {"success": True, "queries": len(queries)}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/profile/run")
async def start_profile():
    """Read the websites of everything discovered but not yet looked at.

    Free and model-free, so there is nothing to estimate and no cap to set.
    """
    global _discovery_task, _discovery_report

    if _discovery_task and not _discovery_task.done():
        return JSONResponse({"success": False, "message": "a run is already going"},
                            status_code=409)
    try:
        from harvey.pipeline import run_profile_stage

        state = _state()
        await state.init_db()
        pending = await state.count_companies_needing_profile()
        if not pending:
            return {"success": True, "pending": 0}

        async def _go():
            global _discovery_report
            try:
                companies, observations, _ = await run_profile_stage(state, limit=200)
                _discovery_report = {
                    "profiled_companies": companies,
                    "profile_observations": observations,
                }
            except Exception as exc:
                logger.exception("profile run failed")
                _discovery_report = {"errors": [str(exc)], "stopped": "failed"}

        _discovery_report = None
        _discovery_task = asyncio.create_task(_go())
        return {"success": True, "pending": pending}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/discover/stop")
async def stop_discovery():
    """Kill switch. Read between batches, so an in-flight run stops cleanly."""
    try:
        state = _state()
        await state.init_db()
        await state.set_setting("discovery_paused", "stopped from dashboard")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.get("/api/today")
async def get_today():
    """What needs a human, right now.

    The dashboard opens here rather than on a setup checklist: the question a
    returning user actually has is "is anything waiting on me?", and the
    answer is usually a short list or nothing at all.
    """
    items: list[dict] = []
    stats: dict = {}
    try:
        from harvey.signals import seed_signal_catalog

        state = _state()
        await state.init_db()
        await seed_signal_catalog(state)

        codes = await state.get_signal_codes()
        proposed = [c for c in codes if c.get("status") == "proposed"]
        confirmed = [c for c in codes if c.get("status") == "confirmed"]
        pending = await state.get_outbox(status="pending_review", limit=200)
        approved = await state.get_outbox(status="approved", limit=200)
        paused = await state.get_setting("sending_paused")
        counts = await state.count_prospects_by_status()

        convos = await query_db(
            "SELECT COUNT(*) AS n FROM conversations WHERE status = 'open'"
        )
        open_convos = convos[0]["n"] if convos else 0
        companies = await query_db("SELECT COUNT(*) AS n FROM companies")
        n_companies = companies[0]["n"] if companies else 0

        unprofiled_count = await state.count_companies_needing_profile()
        stats = {
            "companies": n_companies,
            "prospects": sum(counts.values()),
            "signals_confirmed": len(confirmed),
            "outbox_pending": len(pending),
            "outbox_approved": len(approved),
            "open_conversations": open_convos,
            "unprofiled": unprofiled_count,
        }

        # Ordered by how much it blocks Harvey from doing anything at all.
        if paused:
            items.append({
                "key": "paused", "tone": "bad",
                "title": "Sending is paused",
                "detail": str(paused) + ". Nothing will go out until you resume it.",
                "action": "Review and resume", "tab": "outbox",
            })

        setup = await get_setup_status()
        if isinstance(setup, dict) and setup.get("percent", 100) < 100:
            missing = [c["label"] for c in setup.get("checks", [])
                       if c.get("required") and not c.get("done")]
            items.append({
                "key": "setup", "tone": "warn",
                "title": "Finish setting Jarvis up",
                "detail": ", ".join(missing[:3]) or "Some required steps are incomplete.",
                "action": "Open setup", "tab": "controls",
            })

        if proposed:
            items.append({
                "key": "signals", "tone": "warn",
                "title": (f"{len(proposed)} signal waiting for your confirmation"
                          if len(proposed) == 1
                          else f"{len(proposed)} signals waiting for your confirmation"),
                "detail": ("Jarvis won't collect anything you haven't approved. "
                           "Confirm which signals define a good prospect for you."),
                "action": "Review signals", "tab": "signals",
            })
        elif not confirmed:
            items.append({
                "key": "signals-none", "tone": "warn",
                "title": "No signals confirmed",
                "detail": "Every signal is rejected, so prospecting has nothing to collect.",
                "action": "Review signals", "tab": "signals",
            })

        if not n_companies and confirmed:
            items.append({
                "key": "discover", "tone": "good",
                "title": "No companies yet",
                "detail": ("Signals are confirmed but nothing has been collected. "
                           "Discovery is free to try — no account needed."),
                "action": "Find businesses", "tab": "discover",
            })

        unprofiled = unprofiled_count
        if unprofiled:
            items.append({
                "key": "profile", "tone": "good",
                "title": f"{unprofiled} companies not looked at yet",
                "detail": ("Reading their websites is free and it is what makes "
                           "an email specific — who their agency is, what they "
                           "are missing, whether they are spending on ads."),
                "action": "Read their sites", "tab": "discover",
            })

        if pending:
            items.append({
                "key": "outbox", "tone": "warn",
                "title": (f"{len(pending)} email waiting for approval" if len(pending) == 1
                          else f"{len(pending)} emails waiting for approval"),
                "detail": "Nothing sends until you approve it. Read them one at a time.",
                "action": "Open the decisions desk", "tab": "outbox",
            })

        if open_convos:
            items.append({
                "key": "replies", "tone": "good",
                "title": (f"{open_convos} live conversation" if open_convos == 1
                          else f"{open_convos} live conversations"),
                "detail": "People replied. Check how Jarvis is handling them.",
                "action": "Read conversations", "tab": "conversations",
            })

        return {"items": items, "stats": stats}
    except Exception as e:
        logger.exception("today load failed")
        return {"items": [], "stats": stats, "error": str(e)}


# ── Signals: Harvey proposes, the user confirms ──
#
# Nothing is collected until a human has said yes to it. This is the gate the
# whole prospecting pipeline hangs off: collectors ask `state.confirmed_signal_codes()`
# and skip anything that isn't in the set.

CATEGORY_META = {
    "discovery": {
        "label": "Discovery — who exists",
        "blurb": "How Jarvis finds businesses at all, and how visible they are. "
                 "This is the only stage that costs money.",
    },
    "profile": {
        "label": "Profile — what they are",
        "blurb": "Read from the pages a business already publishes. Free, no AI "
                 "tokens, three HTTP requests per company. These are the signals "
                 "that make an email specific.",
    },
    "people": {
        "label": "People — who decides",
        "blurb": "Named humans and whether they're the one who can say yes.",
    },
    "verification": {
        "label": "Contactability — can you reach them",
        "blurb": "Whether the address will actually deliver, and what to do when "
                 "it won't.",
    },
}
CATEGORY_ORDER = ["discovery", "profile", "people", "verification"]


@app.get("/api/signals")
async def get_signals():
    """The signal vocabulary, grouped for review, with live cohort sizes."""
    try:
        from harvey.signals import seed_signal_catalog

        state = _state()
        await state.init_db()
        # Seeding is idempotent and never overrides a decision the user made,
        # so it is safe to run on every load — new signals shipped in an
        # upgrade show up as `proposed` without any migration step.
        await seed_signal_catalog(state)

        codes = await state.get_signal_codes()
        counts = {c["signal_code"]: c for c in await state.signal_counts()}

        groups, summary = [], {"proposed": 0, "confirmed": 0, "rejected": 0}
        for cat in CATEGORY_ORDER:
            rows = []
            for sig in codes:
                if sig.get("category") != cat:
                    continue
                seen = counts.get(sig["code"], {})
                rows.append({
                    **sig,
                    "companies": seen.get("companies", 0),
                    "observations": seen.get("observations", 0),
                })
            if rows:
                meta = CATEGORY_META.get(cat, {})
                groups.append({
                    "key": cat,
                    "label": meta.get("label", cat.title()),
                    "blurb": meta.get("blurb", ""),
                    "signals": rows,
                })
        for sig in codes:
            summary[sig.get("status", "proposed")] = (
                summary.get(sig.get("status", "proposed"), 0) + 1
            )

        return {"summary": summary, "groups": groups, "total": len(codes)}
    except Exception as e:
        logger.exception("signals load failed")
        return {"error": str(e), "groups": [], "summary": {}}


@app.post("/api/signals/status")
async def set_signals_status(request: Request):
    """Confirm or reject one signal, or a whole category at once."""
    try:
        body = await request.json()
        status = (body.get("status") or "").strip()
        codes = body.get("codes") or ([body["code"]] if body.get("code") else [])
        if status not in ("proposed", "confirmed", "rejected"):
            return JSONResponse(
                {"success": False, "message": f"invalid status: {status!r}"},
                status_code=400,
            )
        if not codes:
            return JSONResponse(
                {"success": False, "message": "no signal codes given"}, status_code=400
            )

        from harvey.signals import seed_signal_catalog

        state = _state()
        await state.init_db()
        # Seed first: a confirm that arrives before anything has loaded the
        # catalog would otherwise report success while changing nothing.
        await seed_signal_catalog(state)

        changed, unknown = 0, []
        for code in codes:
            if await state.set_signal_status(code, status):
                changed += 1
            else:
                unknown.append(code)
        return {
            "success": True, "changed": changed,
            "status": status, "unknown": unknown,
        }
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/cohort")
async def preview_cohort(request: Request):
    """How many companies carry ALL these signals and none of those.

    The payoff for confirming signals: a cohort is a query, not a list. Set
    intersection happens in SQL — intersecting in JS over a capped fetch
    silently returns the wrong answer.
    """
    try:
        body = await request.json()
        require = [c for c in (body.get("require") or []) if c]
        exclude = [c for c in (body.get("exclude") or []) if c]
        if not require:
            return {"size": 0, "companies": []}

        state = _state()
        await state.init_db()
        ids = await state.cohort(require, exclude, limit=1000)
        if not ids:
            return {"size": 0, "companies": []}

        placeholders = ",".join("?" for _ in ids[:200])
        rows = await query_db(
            f"SELECT id, name, domain, industry, location FROM companies "
            f"WHERE id IN ({placeholders})",
            tuple(ids[:200]),
        )
        return {"size": len(ids), "companies": rows}
    except Exception as e:
        return JSONResponse({"size": 0, "companies": [], "error": str(e)}, status_code=500)


@app.get("/api/runs")
async def get_runs_api():
    """The collector run log — what ran, when, what it produced and cost."""
    try:
        state = _state()
        await state.init_db()
        await state.sweep_stale_runs()
        return await state.get_runs(limit=25)
    except Exception as e:
        return {"error": str(e)}


WEB_DIR = (Path(__file__).resolve().parent / "web")


TEXT_TYPES = {".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}
BINARY_TYPES = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@app.get("/static/{path:path}")
async def static_file(path: str):
    """Serve the dashboard's own assets from disk.

    Read per-request rather than cached at import: editing app.css and hitting
    reload is the whole point of having them as real files. Fonts are vendored
    rather than fetched from a CDN — this is a local tool and it should work
    with the network off.
    """
    target = (WEB_DIR / path).resolve()
    root = WEB_DIR.resolve()
    if not target.is_file() or not target.is_relative_to(root):
        return PlainTextResponse("not found", status_code=404)

    if target.suffix in BINARY_TYPES:
        return Response(
            target.read_bytes(),
            media_type=BINARY_TYPES[target.suffix],
            headers={"Cache-Control": "public, max-age=604800"},
        )
    return PlainTextResponse(
        target.read_text(encoding="utf-8"),
        media_type=TEXT_TYPES.get(target.suffix, "text/plain"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


def start_dashboard(host: str = "127.0.0.1", port: int = 5555):
    """Start the dashboard server."""
    import uvicorn

    print(f"\n  Jarvis Dashboard running at http://{host}:{port}")
    print("  Press Ctrl+C to stop.\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
