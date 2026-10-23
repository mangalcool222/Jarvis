"""Autonomous Google Sheets & Local CRM Auto-Sync Engine.

Keeps Google Sheets CRM and local TSV/CSV lead vaults synchronized in real time
whenever Harvey scouts a lead, dispatches an email, or receives a reply.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Any

import httpx

from harvey.export import collect_prospects, to_csv

logger = logging.getLogger("harvey.sheets_sync")

DEFAULT_TSV_PATH = "/Users/mangal777/Mangal/01_TrackKaro_AI/TrackKaro_Leads/google_sheet_import_ready.tsv"
DEFAULT_CSV_PATH = "/Users/mangal777/Mangal/01_TrackKaro_AI/TrackKaro_Leads/trackkaro_leads.csv"
DEFAULT_WEBHOOK_URL = os.getenv(
    "GOOGLE_SHEET_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbwujgsnYh-8yGoSg4-Az9PGg8QcJVQEEIsS6UcqksLFWmcGLo2jko5Oz3-uetiTlvFw/exec"
)


def _clean_domain(url: str) -> str:
    if not url:
        return ""
    return url.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")


def _resolve_vault_paths():
    from pathlib import Path
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))
    if is_root:
        return DEFAULT_TSV_PATH, DEFAULT_CSV_PATH, True
    leads_dir = ws / "leads"
    leads_dir.mkdir(parents=True, exist_ok=True)
    return str(leads_dir / "crm_vault.tsv"), str(leads_dir / "leads.csv"), False


async def regenerate_local_vaults(state) -> int:
    """Regenerate TSV and CSV vaults from the active workspace DB."""
    try:
        tsv_path, csv_path, is_root = _resolve_vault_paths()
        prospects = await collect_prospects(state, include_all=True)
        if not prospects:
            return 0

        # 1. Update CSV
        csv_content = to_csv(prospects)
        try:
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(csv_content)
        except Exception as e:
            logger.debug(f"CSV vault write error: {e}")

        # 2. Update TSV formatted for Google Sheets CRM
        headers = [
            "Target Account / Company",
            "Region / Market",
            "Niche / Sector",
            "Core Pain Point",
            "Decision Maker & Title",
            "Direct Contact (Email • Phone)",
            "Priority Score",
            "Outreach Status",
            "Estimated Deal Size",
            "Company Website",
            "LinkedIn Profile",
            "Strategy Notes"
        ]

        rows = [headers]
        for p in prospects:
            company = p.get("company_name", "")
            industry = p.get("industry", "")
            phone = p.get("phone", "")
            email = p.get("email", "")

            if "+971" in phone or ".ae" in email:
                region = "Dubai / UAE"
                retainer = "$3,000 – $6,000"
            elif "+44" in phone or ".co.uk" in email:
                region = "UK / London"
                retainer = "£2,500 – £5,000"
            elif "+91" in phone or ".in" in email:
                region = "India"
                retainer = "₹1,50,000 – ₹3,50,000"
            else:
                region = "US / Global"
                retainer = "$2,500 – $5,000"

            pain_point = "Inbound Lead Latency & Speed-to-Lead Decay"
            dm = f"{p.get('first_name', '')} {p.get('last_name', '')} ({p.get('title', '')})".strip()
            clean_p = phone if phone else "N/A"
            contact = f"{email} • {clean_p}"
            score = str(p.get("score", 95))
            
            raw_status = (p.get("status", "queued") or "queued").lower()
            email_status = (p.get("email_status", "unknown") or "unknown").lower()

            if raw_status == "contacted":
                crm_status = "🚀 Contacted (Email Delivered)"
                channel_note = "Email Sequence Active"
            elif raw_status == "replied":
                crm_status = "🔥 Replied (Hot Inbound)"
                channel_note = "Lead Replied! Check Inbox"
            elif raw_status in ("lost", "bounced") or email_status == "invalid":
                crm_status = "❌ Bounced / Invalid Email"
                channel_note = "Do Not Email • Discard"
            elif email_status == "verified":
                crm_status = "✅ Verified (Ready for Email)"
                channel_note = "100% Safe Mailbox • High Intent"
            elif raw_status == "linkedin_backlog" or email_status in ("risky", "catch_all"):
                crm_status = "⚠️ Catch-All (LinkedIn Outreach)"
                channel_note = "Archived from Email • Connect via LinkedIn or Site Form"
            else:
                crm_status = f"🔍 {raw_status.capitalize()}"
                channel_note = "Scouted"

            website_url = p.get("website", "")
            website_formula = f'=HYPERLINK("{website_url}", "{_clean_domain(website_url)} 🌐")' if website_url else "—"

            linkedin_url = p.get("linkedin_url", "")
            linkedin_formula = f'=HYPERLINK("{linkedin_url}", "View Profile ↗")' if linkedin_url else "—"

            source = p.get("source", "verified_global")
            hook = f"{channel_note} • Speed-to-Lead SLA ({source})"

            rows.append([
                company, region, industry, pain_point, dm, contact,
                score, crm_status, retainer, website_formula, linkedin_formula, hook
            ])

        try:
            with open(tsv_path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write("\t".join(r) + "\n")
        except Exception as e:
            logger.debug(f"TSV vault write error: {e}")

        logger.info(f"Regenerated {len(prospects)} leads in local CRM vaults ({tsv_path}).")
        return len(prospects)
    except Exception as e:
        logger.warning(f"Failed to regenerate local CRM vaults: {e}")
        return 0


async def push_to_google_sheet(
    email: str,
    status: str,
    company: str = "",
    name: str = "",
    score: int = 95,
    notes: str = "",
    webhook_url: Optional[str] = None
) -> bool:
    """Send an async webhook event to Google Apps Script / n8n to update Google Sheet CRM."""
    from harvey.paths import PROJECT_ROOT, get_workspace_dir
    ws = get_workspace_dir()
    is_root = (ws.resolve() == PROJECT_ROOT.resolve() or ws.name in ("trackkaro", ""))

    url = webhook_url
    if not url:
        if is_root:
            url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
        else:
            ws_env = ws / ".env"
            if ws_env.is_file():
                for line in ws_env.read_text().splitlines():
                    if line.startswith("GOOGLE_SHEET_WEBHOOK_URL="):
                        url = line.split("=", 1)[1].strip()
    if not url:
        return False

    payload = {
        "action": "outreach_update",
        "email": email,
        "company": company,
        "name": name,
        "status": status,
        "score": score,
        "notes": notes,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code in (200, 201, 302):
                logger.info(f"SheetsSync: Pushed status '{status}' for {email} to Google Sheet webhook.")
                return True
            else:
                logger.debug(f"SheetsSync: Webhook returned HTTP {resp.status_code}")
                return False
    except Exception as e:
        logger.debug(f"SheetsSync: Webhook push failed: {e}")
        return False


async def sync_prospect_status(
    prospect: Any,
    status: str,
    state=None,
    env=None,
    notes: str = ""
) -> None:
    """Triggered on email send, bounce, or reply to keep Sheet & vaults in sync."""
    if not prospect:
        return

    email = getattr(prospect, "email", "") or (prospect.get("email") if isinstance(prospect, dict) else "")
    company = getattr(prospect, "company", "") or (prospect.get("company") if isinstance(prospect, dict) else "")
    first_name = getattr(prospect, "first_name", "") or (prospect.get("first_name") if isinstance(prospect, dict) else "")
    last_name = getattr(prospect, "last_name", "") or (prospect.get("last_name") if isinstance(prospect, dict) else "")
    name = f"{first_name} {last_name}".strip()
    score = getattr(prospect, "score", 95) or (prospect.get("score", 95) if isinstance(prospect, dict) else 95)

    # 1. Push to Webhook
    webhook_url = getattr(env, "google_sheet_webhook_url", "") if env else ""
    await push_to_google_sheet(
        email=email,
        status=status,
        company=company,
        name=name,
        score=score,
        notes=notes,
        webhook_url=webhook_url
    )

    # 2. Refresh local TSV/CSV vaults
    if state is not None:
        await regenerate_local_vaults(state)
