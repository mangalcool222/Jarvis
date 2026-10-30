"""One-click NocoDB synchronizer for Jarvis & TrackKaro AI."""

import json
import sqlite3
import urllib.request
from pathlib import Path

NOCO_URL = "https://crm.trackkaroai.com"
TOKEN = "nc_pat_gPoul6APyQs7Qr77wz3VI6AmaqaXrNg8OipLKIsu"
BASE_ID = "pmrylgz2088xx3y"
ROOT = Path("/Users/mangal777/Mangal/01_TrackKaro_AI/harvey")

HEADERS = {
    "xc-token": TOKEN,
    "Content-Type": "application/json",
}


def noco_request(method, path, data=None):
    url = f"{NOCO_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_existing_tables():
    res = noco_request("GET", f"/api/v2/meta/bases/{BASE_ID}/tables")
    return {t["title"]: t["id"] for t in res.get("list", [])}


def create_table_if_missing(title, columns, existing_tables):
    if title in existing_tables:
        print(f"Table '{title}' already exists (ID: {existing_tables[title]})")
        return existing_tables[title]
    payload = {
        "table_name": title,
        "title": title,
        "columns": columns,
    }
    res = noco_request("POST", f"/api/v2/meta/bases/{BASE_ID}/tables", payload)
    table_id = res["id"]
    print(f"Created table '{title}' (ID: {table_id})")
    return table_id


def bulk_insert(table_id, records):
    if not records:
        return 0
    # Insert in chunks of 25
    chunk_size = 25
    total = 0
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        res = noco_request("POST", f"/api/v2/tables/{table_id}/records", chunk)
        total += len(chunk)
    return total


def main():
    print("🚀 Initializing NocoDB Architecture for Jarvis Outbound OS...")
    existing = get_existing_tables()

    # 1. Ensure Tables
    outbox_table_id = existing.get("Outbox")
    if not outbox_table_id:
        outbox_table_id = create_table_if_missing("Outbox", [
            {"column_name": "Recipient", "title": "Recipient", "uidt": "Email"},
            {"column_name": "Subject", "title": "Subject", "uidt": "SingleLineText"},
            {"column_name": "Company", "title": "Company", "uidt": "SingleLineText"},
            {"column_name": "Workspace", "title": "Workspace", "uidt": "SingleLineText"},
            {"column_name": "Status", "title": "Status", "uidt": "SingleLineText"},
            {"column_name": "Pitch", "title": "Pitch", "uidt": "LongText"},
        ], existing)

    prospects_table_id = create_table_if_missing("Prospects", [
        {"column_name": "FirstName", "title": "First Name", "uidt": "SingleLineText"},
        {"column_name": "LastName", "title": "Last Name", "uidt": "SingleLineText"},
        {"column_name": "Title", "title": "Job Title", "uidt": "SingleLineText"},
        {"column_name": "Email", "title": "Email Address", "uidt": "Email"},
        {"column_name": "EmailStatus", "title": "Deliverability Status", "uidt": "SingleLineText"},
        {"column_name": "Company", "title": "Company Name", "uidt": "SingleLineText"},
        {"column_name": "LinkedIn", "title": "LinkedIn URL", "uidt": "URL"},
        {"column_name": "Score", "title": "Intent Score", "uidt": "Number"},
        {"column_name": "Workspace", "title": "Workspace", "uidt": "SingleLineText"},
    ], existing)

    companies_table_id = create_table_if_missing("Companies", [
        {"column_name": "Name", "title": "Company Name", "uidt": "SingleLineText"},
        {"column_name": "Domain", "title": "Domain", "uidt": "SingleLineText"},
        {"column_name": "Website", "title": "Website URL", "uidt": "URL"},
        {"column_name": "Industry", "title": "Industry", "uidt": "SingleLineText"},
        {"column_name": "Location", "title": "Location", "uidt": "SingleLineText"},
        {"column_name": "Workspace", "title": "Workspace", "uidt": "SingleLineText"},
    ], existing)

    # 2. Extract Data from Local Databases
    sources = [
        ("Cold Email Agency Retainer", ROOT / "workspaces" / "cold_email_outreach" / "data" / "harvey.db"),
        ("Dubai & India Speed-to-Lead", ROOT / "data" / "harvey.db"),
    ]

    all_outbox = []
    all_prospects = []
    all_companies = []

    for ws_label, db_path in sources:
        if not db_path.exists():
            continue
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Outbox
        cur.execute("SELECT * FROM outbox")
        for row in cur.fetchall():
            all_outbox.append({
                "Recipient": row["to_email"] or "",
                "Subject": row["subject"] or "",
                "Company": row["thread_ref"] or row["campaign_id"] or "",
                "Workspace": ws_label,
                "Status": row["status"] or "pending_review",
                "Pitch": row["body"] or "",
            })

        # Prospects
        cur.execute("SELECT * FROM prospects")
        for row in cur.fetchall():
            all_prospects.append({
                "FirstName": row["first_name"] or "",
                "LastName": row["last_name"] or "",
                "Title": row["title"] or "",
                "Email": row["email"] or "",
                "EmailStatus": row["email_status"] or "verified",
                "Company": row["company"] or "",
                "LinkedIn": row["linkedin_url"] or "",
                "Score": row["score"] or 0,
                "Workspace": ws_label,
            })

        # Companies
        cur.execute("SELECT * FROM companies")
        for row in cur.fetchall():
            all_companies.append({
                "Name": row["name"] or "",
                "Domain": row["domain"] or "",
                "Website": row["website"] or "",
                "Industry": row["industry"] or "",
                "Location": row["location"] or "",
                "Workspace": ws_label,
            })
        conn.close()

    print(f"📦 Extracted from SQLite: {len(all_outbox)} Outbox emails, {len(all_prospects)} Prospects, {len(all_companies)} Companies.")

    # 3. Bulk Insert into NocoDB
    print("📤 Pushing Outbox records to NocoDB...")
    o_count = bulk_insert(outbox_table_id, all_outbox)
    print(f"✅ Pushed {o_count} Outbox records.")

    print("📤 Pushing Prospects to NocoDB...")
    p_count = bulk_insert(prospects_table_id, all_prospects)
    print(f"✅ Pushed {p_count} Prospects.")

    print("📤 Pushing Companies to NocoDB...")
    c_count = bulk_insert(companies_table_id, all_companies)
    print(f"✅ Pushed {c_count} Companies.")

    print("\n🎉 ALL DATA SUCCESSFULLY SYNCED TO NOCODB!")


if __name__ == "__main__":
    main()
