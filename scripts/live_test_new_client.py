"""
Live Test: Provision a Brand New Client in Supabase & Auto-Populate into NocoDB.
Simulates the exact end-to-end flow when a new high-ticket client signs up with TrackKaro.
"""

import json
import psycopg2
import urllib.request

# Supabase Credentials
SUPABASE_HOST = "aws-0-eu-west-2.pooler.supabase.com"
SUPABASE_PORT = 6543
SUPABASE_DB = "postgres"
SUPABASE_USER = "postgres.rwkoypazdisfagtiylqa"
SUPABASE_PASS = "kZV#QWtBT4Wn?dw"

# NocoDB Credentials
NOCO_URL = "https://crm.trackkaroai.com"
NOCO_TOKEN = "nc_pat_gPoul6APyQs7Qr77wz3VI6AmaqaXrNg8OipLKIsu"
NOCO_WORKSPACE_ID = "w2nckkp4"

CLIENT_KEY = "apex_solar"
CLIENT_NAME = "Apex Luxury Solar GCC"
CLIENT_INDUSTRY = "CleanTech & Commercial Solar"


def get_pg_conn():
    return psycopg2.connect(
        host=SUPABASE_HOST,
        port=SUPABASE_PORT,
        dbname=SUPABASE_DB,
        user=SUPABASE_USER,
        password=SUPABASE_PASS,
        sslmode="require"
    )


def noco_req(method, path, data=None):
    url = f"{NOCO_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={"xc-token": NOCO_TOKEN, "Content-Type": "application/json"},
        method=method
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def step1_create_in_supabase():
    print(f"\n⚡ STEP 1: Registering new client in Supabase ({CLIENT_KEY})...")
    conn = get_pg_conn()
    with conn.cursor() as cur:
        # Register workspace
        cur.execute("""
            INSERT INTO public.workspaces (id, client_name, industry, port, status)
            VALUES (%s, %s, %s, 5557, 'active')
            ON CONFLICT (id) DO UPDATE SET client_name = EXCLUDED.client_name, updated_at = CURRENT_TIMESTAMP;
        """, (CLIENT_KEY, CLIENT_NAME, CLIENT_INDUSTRY))

        # Insert Companies
        companies = [
            ("comp_solar_1", CLIENT_KEY, "Al Mansoori Renewable Energy", "almansoorisolar.ae", "https://almansoorisolar.ae", "Solar EPC & Luxury Residential", "Dubai, UAE", "Meta Ad Form"),
            ("comp_solar_2", CLIENT_KEY, "Gulf Commercial Solar Ltd", "gulfsolar.com", "https://gulfsolar.com", "Commercial Rooftop Solar", "Abu Dhabi, UAE", "Google Search Ads"),
        ]
        cur.executemany("""
            INSERT INTO public.companies (id, workspace, name, domain, website, industry, location, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (workspace, id) DO NOTHING;
        """, companies)

        # Insert Prospects (Decision Makers)
        prospects = [
            ("pros_solar_1", CLIENT_KEY, "Fahad", "Al-Mansoori", "fahad@almansoorisolar.ae", "verified", "+971501234567", "https://linkedin.com/in/fahad-al-mansoori", "Managing Partner", "Al Mansoori Renewable Energy", 95, "qualified"),
            ("pros_solar_2", CLIENT_KEY, "Tariq", "Mansoor", "tariq@gulfsolar.com", "verified", "+971509876543", "https://linkedin.com/in/tariq-mansoor-solar", "Head of Commercial Projects", "Gulf Commercial Solar Ltd", 88, "contacted"),
        ]
        cur.executemany("""
            INSERT INTO public.prospects (id, workspace, first_name, last_name, email, email_status, phone, linkedin_url, title, company, score, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (workspace, id) DO NOTHING;
        """, prospects)

        # Insert Outbox Pitches (Drafted by Jarvis AI SDR)
        outbox = [
            ("outbox_solar_1", CLIENT_KEY, "fahad@almansoorisolar.ae", "re: Al Mansoori 15s solar lead dispatch pipeline", "Hi Fahad,\n\nNoticed Al Mansoori's new commercial solar installations in Dubai South.\n\nWe deployed TrackKaro's autonomous speed-to-lead nervous system for high-ticket EPC developers — connecting Meta/Google ad form submissions to your sales engineers in under 15 seconds via WhatsApp.\n\nWould you be open to a 60-second interactive demo?\n\nBest,\nMangal Soren • TrackKaro AI", "pending_review"),
            ("outbox_solar_2", CLIENT_KEY, "tariq@gulfsolar.com", "re: Gulf Commercial Solar lead acceleration", "Hi Tariq,\n\nReaching out regarding your commercial rooftop solar lead intake.\n\nTrackKaro eliminates lead decay by routing high-intent commercial inquiries instantly to your reps before competitors call back.\n\nOpen to exploring a brief walkthrough?\n\nBest,\nMangal Soren • TrackKaro AI", "approved"),
        ]
        cur.executemany("""
            INSERT INTO public.outbox (id, workspace, to_email, subject, body, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (workspace, id) DO NOTHING;
        """, outbox)

        conn.commit()
    conn.close()
    print("✅ Supabase updated: Workspace registered, 2 companies, 2 prospects, 2 outbox pitches saved in Supabase!")


def step2_provision_nocodb():
    print(f"\n📊 STEP 2: Creating Dedicated Client Portal in NocoDB for {CLIENT_NAME}...")
    base_title = f"TrackKaro - {CLIENT_NAME}"

    # Check if base exists
    existing = noco_req("GET", "/api/v2/meta/bases")
    base_id = None
    for b in existing.get("list", []):
        if b["title"] == base_title:
            base_id = b["id"]
            print(f"Found existing Base '{base_title}' (ID: {base_id})")
            break

    if not base_id:
        res = noco_req("POST", "/api/v2/meta/bases", {
            "title": base_title,
            "fk_workspace_id": NOCO_WORKSPACE_ID,
            "type": "database",
        })
        base_id = res["id"]
        print(f"✅ Created dedicated Base: '{base_title}' (ID: {base_id})")

    # Tables
    t_outbox = noco_req("POST", f"/api/v2/meta/bases/{base_id}/tables", {
        "table_name": "Outbox", "title": "Outbox",
        "columns": [
            {"column_name": "Recipient", "title": "Recipient Email", "uidt": "Email"},
            {"column_name": "Subject", "title": "Subject Line", "uidt": "SingleLineText"},
            {"column_name": "Status", "title": "Review Status", "uidt": "SingleLineText"},
            {"column_name": "Pitch", "title": "Email Pitch", "uidt": "LongText"},
        ]
    })["id"]

    t_prospects = noco_req("POST", f"/api/v2/meta/bases/{base_id}/tables", {
        "table_name": "Prospects", "title": "Prospects",
        "columns": [
            {"column_name": "FirstName", "title": "First Name", "uidt": "SingleLineText"},
            {"column_name": "LastName", "title": "Last Name", "uidt": "SingleLineText"},
            {"column_name": "Title", "title": "Job Title", "uidt": "SingleLineText"},
            {"column_name": "Company", "title": "Company Name", "uidt": "SingleLineText"},
            {"column_name": "Email", "title": "Email Address", "uidt": "Email"},
            {"column_name": "EmailStatus", "title": "Email Status", "uidt": "SingleLineText"},
            {"column_name": "Phone", "title": "Phone Number", "uidt": "PhoneNumber"},
            {"column_name": "Score", "title": "Intent Score", "uidt": "Number"},
        ]
    })["id"]

    t_companies = noco_req("POST", f"/api/v2/meta/bases/{base_id}/tables", {
        "table_name": "Companies", "title": "Companies",
        "columns": [
            {"column_name": "Name", "title": "Company Name", "uidt": "SingleLineText"},
            {"column_name": "Domain", "title": "Domain", "uidt": "SingleLineText"},
            {"column_name": "Website", "title": "Website URL", "uidt": "URL"},
            {"column_name": "Industry", "title": "Industry", "uidt": "SingleLineText"},
            {"column_name": "Location", "title": "Location", "uidt": "SingleLineText"},
        ]
    })["id"]

    # Pull latest from Supabase and insert
    print(f"📥 Pulling {CLIENT_KEY} data directly from Supabase...")
    conn = get_pg_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT to_email, subject, status, body FROM public.outbox WHERE workspace = %s", (CLIENT_KEY,))
        outbox_rows = [{"Recipient": r[0], "Subject": r[1], "Status": r[2], "Pitch": r[3]} for r in cur.fetchall()]

        cur.execute("SELECT first_name, last_name, title, company, email, email_status, phone, score FROM public.prospects WHERE workspace = %s", (CLIENT_KEY,))
        prospects_rows = [{"FirstName": r[0], "LastName": r[1], "Title": r[2], "Company": r[3], "Email": r[4], "EmailStatus": r[5], "Phone": r[6], "Score": r[7]} for r in cur.fetchall()]

        cur.execute("SELECT name, domain, website, industry, location FROM public.companies WHERE workspace = %s", (CLIENT_KEY,))
        companies_rows = [{"Name": r[0], "Domain": r[1], "Website": r[2], "Industry": r[3], "Location": r[4]} for r in cur.fetchall()]
    conn.close()

    # Bulk insert
    noco_req("POST", f"/api/v2/tables/{t_outbox}/records", outbox_rows)
    noco_req("POST", f"/api/v2/tables/{t_prospects}/records", prospects_rows)
    noco_req("POST", f"/api/v2/tables/{t_companies}/records", companies_rows)

    print(f"\n🎉 LIVE TEST COMPLETE!")
    print(f"1. Supabase has live rows under workspace '{CLIENT_KEY}'.")
    print(f"2. NocoDB has created dedicated client project: '{base_title}'.")


if __name__ == "__main__":
    step1_create_in_supabase()
    step2_provision_nocodb()
