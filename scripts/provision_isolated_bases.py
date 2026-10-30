"""Creates isolated, dedicated NocoDB Bases for each client / workspace."""

import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

NOCO_URL = "https://crm.trackkaroai.com"
TOKEN = "nc_pat_gPoul6APyQs7Qr77wz3VI6AmaqaXrNg8OipLKIsu"
ROOT = Path("/Users/mangal777/Mangal/01_TrackKaro_AI/harvey")

HEADERS = {
    "xc-token": TOKEN,
    "Content-Type": "application/json",
}


def noco_req(method, path, data=None):
    url = f"{NOCO_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTPError on {method} {path}: {e.code} - {e.read().decode()}")
        raise


def get_or_create_base(title):
    # Check if base exists
    existing = noco_req("GET", "/api/v2/meta/bases")
    for b in existing.get("list", []):
        if b["title"] == title:
            print(f"Found existing Base '{title}' (ID: {b['id']})")
            return b["id"]

    res = noco_req("POST", "/api/v2/meta/bases", {
        "title": title,
        "fk_workspace_id": "w2nckkp4",
        "type": "database",
    })
    base_id = res["id"]
    print(f"✅ Created dedicated Base: '{title}' (ID: {base_id})")
    return base_id


def create_table_if_missing(base_id, title, columns):
    existing = noco_req("GET", f"/api/v2/meta/bases/{base_id}/tables")
    for t in existing.get("list", []):
        if t["title"] == title:
            return t["id"]

    res = noco_req("POST", f"/api/v2/meta/bases/{base_id}/tables", {
        "table_name": title,
        "title": title,
        "columns": columns,
    })
    return res["id"]


def bulk_insert(table_id, records):
    if not records:
        return 0
    chunk_size = 25
    total = 0
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        noco_req("POST", f"/api/v2/tables/{table_id}/records", chunk)
        total += len(chunk)
    return total


def provision_workspace(base_title, db_path):
    print(f"\n=========================================")
    print(f"📦 Provisioning Isolated Base: {base_title}")
    print(f"=========================================")

    base_id = get_or_create_base(base_title)

    # 1. Outbox Table
    outbox_tid = create_table_if_missing(base_id, "Outbox", [
        {"column_name": "Recipient", "title": "Recipient Email", "uidt": "Email"},
        {"column_name": "Subject", "title": "Subject Line", "uidt": "SingleLineText"},
        {"column_name": "Company", "title": "Company Reference", "uidt": "SingleLineText"},
        {"column_name": "Status", "title": "Review Status", "uidt": "SingleLineText"},
        {"column_name": "Pitch", "title": "Email Copy", "uidt": "LongText"},
    ])

    # 2. Prospects Table
    prospects_tid = create_table_if_missing(base_id, "Prospects", [
        {"column_name": "FirstName", "title": "First Name", "uidt": "SingleLineText"},
        {"column_name": "LastName", "title": "Last Name", "uidt": "SingleLineText"},
        {"column_name": "Title", "title": "Job Title", "uidt": "SingleLineText"},
        {"column_name": "Email", "title": "Email Address", "uidt": "Email"},
        {"column_name": "EmailStatus", "title": "Deliverability Status", "uidt": "SingleLineText"},
        {"column_name": "Company", "title": "Company Name", "uidt": "SingleLineText"},
        {"column_name": "LinkedIn", "title": "LinkedIn URL", "uidt": "URL"},
        {"column_name": "Score", "title": "Intent Score", "uidt": "Number"},
    ])

    # 3. Companies Table
    companies_tid = create_table_if_missing(base_id, "Companies", [
        {"column_name": "Name", "title": "Company Name", "uidt": "SingleLineText"},
        {"column_name": "Domain", "title": "Domain", "uidt": "SingleLineText"},
        {"column_name": "Website", "title": "Website URL", "uidt": "URL"},
        {"column_name": "Industry", "title": "Industry", "uidt": "SingleLineText"},
        {"column_name": "Location", "title": "Location", "uidt": "SingleLineText"},
    ])

    if not db_path.exists():
        print(f"⚠️ DB path {db_path} does not exist, created empty schema.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Extract Outbox
    cur.execute("SELECT * FROM outbox")
    outbox_data = [{
        "Recipient": row["to_email"] or "",
        "Subject": row["subject"] or "",
        "Company": row["thread_ref"] or row["campaign_id"] or "",
        "Status": row["status"] or "pending_review",
        "Pitch": row["body"] or "",
    } for row in cur.fetchall()]

    # Extract Prospects
    cur.execute("SELECT * FROM prospects")
    prospects_data = [{
        "FirstName": row["first_name"] or "",
        "LastName": row["last_name"] or "",
        "Title": row["title"] or "",
        "Email": row["email"] or "",
        "EmailStatus": row["email_status"] or "verified",
        "Company": row["company"] or "",
        "LinkedIn": row["linkedin_url"] or "",
        "Score": row["score"] or 0,
    } for row in cur.fetchall()]

    # Extract Companies
    cur.execute("SELECT * FROM companies")
    companies_data = [{
        "Name": row["name"] or "",
        "Domain": row["domain"] or "",
        "Website": row["website"] or "",
        "Industry": row["industry"] or "",
        "Location": row["location"] or "",
    } for row in cur.fetchall()]

    conn.close()

    print(f"Inserting into {base_title}: {len(outbox_data)} outbox, {len(prospects_data)} prospects, {len(companies_data)} companies...")
    bulk_insert(outbox_tid, outbox_data)
    bulk_insert(prospects_tid, prospects_data)
    bulk_insert(companies_tid, companies_data)
    print(f"🎉 '{base_title}' populated with 100% data isolation!")


def main():
    # Base 1: Cold Email Agency Retainer (B2B SaaS & Dev Agencies)
    provision_workspace(
        "TrackKaro - Cold Email Agency Retainer",
        ROOT / "workspaces" / "cold_email_outreach" / "data" / "harvey.db"
    )

    # Base 2: Dubai & India Speed-to-Lead (Luxury Real Estate & Clinics)
    provision_workspace(
        "TrackKaro - Dubai & India Speed-to-Lead",
        ROOT / "data" / "harvey.db"
    )

    print("\n✅ MULTI-TENANT ISOLATION COMPLETE! Each client/offer has its own clean Base.")


if __name__ == "__main__":
    main()
