"""Automatic background synchronization between Jarvis SQLite state and NocoDB CRM."""

import asyncio
import json
import logging
import sqlite3
from typing import Optional, List, Dict, Any
from pathlib import Path
from harvey.paths import get_workspace_dir, get_db_path, PROJECT_ROOT

logger = logging.getLogger(__name__)

NOCO_URL = "https://crm.trackkaroai.com"
NOCO_TOKEN = "nc_pat_gPoul6APyQs7Qr77wz3VI6AmaqaXrNg8OipLKIsu"

WORKSPACE_TABLES = {
    "cold_email_outreach": {
        "outbox": "m0v84iqvw6xosuh",
        "prospects": "m2j8e5ewdvr17li",
        "companies": "m6gjglcmsnxq6zs",
    },
    "speed-to-lead": {
        "outbox": "myuqj1gsljmmty1",
        "prospects": "mtvebmvnxpqjw5d",
        "companies": "mrzhj9h4jp15x6r",
    },
}

HEADERS = {
    "xc-token": NOCO_TOKEN,
    "Content-Type": "application/json",
}


def _get_table_id(ws_name: str, table_type: str = "outbox") -> Optional[str]:
    key = "cold_email_outreach" if "cold" in ws_name.lower() else "speed-to-lead"
    return WORKSPACE_TABLES.get(key, {}).get(table_type)


async def sync_outbox_status(recipient_email: str, status: str, ws_name: Optional[str] = None):
    """Update NocoDB Outbox record status asynchronously in background."""
    def _do_sync():
        import urllib.request
        import urllib.parse
        try:
            ws = ws_name or get_workspace_dir().name
            table_id = _get_table_id(ws, "outbox")
            if not table_id:
                return

            # Search record by Recipient Email
            encoded_where = urllib.parse.quote(f"(Recipient Email,eq,{recipient_email})")
            url = f"{NOCO_URL}/api/v2/tables/{table_id}/records?where={encoded_where}&limit=10"
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                records = data.get("list", [])

            if not records:
                return

            updates = [{"Id": r["Id"], "Review Status": status} for r in records]
            patch_req = urllib.request.Request(
                f"{NOCO_URL}/api/v2/tables/{table_id}/records",
                data=json.dumps(updates).encode("utf-8"),
                headers=HEADERS,
                method="PATCH"
            )
            with urllib.request.urlopen(patch_req, timeout=5) as resp:
                logger.info(f"NocoDB synced: {recipient_email} -> {status}")
        except Exception as e:
            logger.warning(f"NocoDB sync failed for {recipient_email}: {e}")

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _do_sync)
    except Exception as e:
        logger.debug(f"Could not dispatch NocoDB async sync: {e}")


async def sync_entire_outbox_now(ws_name: Optional[str] = None) -> Dict[str, Any]:
    """Sync all current outbox statuses from active workspace SQLite DB to NocoDB."""
    def _do_full_sync():
        import urllib.request
        try:
            ws = get_workspace_dir()
            ws_str = ws_name or ws.name
            table_id = _get_table_id(ws_str, "outbox")
            if not table_id:
                return {"success": False, "error": "Unknown workspace table"}

            db_path = get_db_path(ws)
            if not db_path.is_file():
                return {"success": False, "error": "SQLite database not found"}

            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT to_email, status FROM outbox")
            sqlite_map = dict(cur.fetchall())
            conn.close()

            # Fetch existing records from NocoDB
            url = f"{NOCO_URL}/api/v2/tables/{table_id}/records?limit=150"
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                noco_records = json.loads(resp.read().decode()).get("list", [])

            updates = []
            for r in noco_records:
                email = r.get("Recipient Email")
                new_st = sqlite_map.get(email)
                if new_st and new_st != r.get("Review Status"):
                    updates.append({"Id": r["Id"], "Review Status": new_st})

            if updates:
                patch_req = urllib.request.Request(
                    f"{NOCO_URL}/api/v2/tables/{table_id}/records",
                    data=json.dumps(updates).encode("utf-8"),
                    headers=HEADERS,
                    method="PATCH"
                )
                with urllib.request.urlopen(patch_req, timeout=8) as resp:
                    pass

            return {"success": True, "updated": len(updates), "total_noco": len(noco_records)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_full_sync)
