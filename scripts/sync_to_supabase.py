"""
Multi-Tenant Supabase PostgreSQL Sync Engine for Jarvis AI SDR & TrackKaro.
Maintains client isolation using workspace keys, automated discovery, and Appsmith views.
"""

import os
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from pathlib import Path

SUPABASE_HOST = os.environ.get("SUPABASE_HOST", "aws-0-eu-west-2.pooler.supabase.com")
SUPABASE_PORT = int(os.environ.get("SUPABASE_PORT", 6543))
SUPABASE_DB = os.environ.get("SUPABASE_DB", "postgres")
SUPABASE_USER = os.environ.get("SUPABASE_USER", "postgres.rwkoypazdisfagtiylqa")
SUPABASE_PASS = os.environ.get("SUPABASE_PASS", "kZV#QWtBT4Wn?dw")

BASE_DIR = Path(__file__).resolve().parent.parent

def get_supabase_conn():
    return psycopg2.connect(
        host=SUPABASE_HOST,
        port=SUPABASE_PORT,
        dbname=SUPABASE_DB,
        user=SUPABASE_USER,
        password=SUPABASE_PASS,
        sslmode="require"
    )

def init_tables(pg_conn):
    with pg_conn.cursor() as cur:
        # 0. Client Workspaces Master Registry
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.workspaces (
                id TEXT PRIMARY KEY,
                client_name TEXT NOT NULL,
                industry TEXT,
                port INTEGER,
                sheet_url TEXT,
                webhook_url TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 1. Companies Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.companies (
                id TEXT NOT NULL,
                workspace TEXT NOT NULL DEFAULT 'cold_email_outreach',
                name TEXT,
                domain TEXT,
                website TEXT,
                phone TEXT,
                industry TEXT,
                location TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (workspace, id)
            );
        """)

        # 2. Prospects Table (Scraped Decision Makers)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.prospects (
                id TEXT NOT NULL,
                workspace TEXT NOT NULL DEFAULT 'cold_email_outreach',
                first_name TEXT,
                last_name TEXT,
                full_name TEXT,
                email TEXT,
                email_status TEXT,
                email_verified BOOLEAN DEFAULT FALSE,
                phone TEXT,
                linkedin_url TEXT,
                title TEXT,
                company TEXT,
                industry TEXT,
                score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                personalization_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (workspace, id)
            );
        """)

        # 3. Outbox Table (Emails Sent & Bounces)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.outbox (
                id TEXT NOT NULL,
                workspace TEXT NOT NULL DEFAULT 'cold_email_outreach',
                to_email TEXT,
                subject TEXT,
                body TEXT,
                status TEXT DEFAULT 'pending_review',
                sent_at TIMESTAMP,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (workspace, id)
            );
        """)

        # Performance Indexes for multi-tenant filtering
        cur.execute("CREATE INDEX IF NOT EXISTS idx_comp_ws ON public.companies (workspace);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pros_ws ON public.prospects (workspace);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_outbox_ws ON public.outbox (workspace);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_outbox_status ON public.outbox (status);")

        # 4. Executive Summary View for Appsmith & Super-Admin Cockpit
        cur.execute("""
            CREATE OR REPLACE VIEW public.view_workspace_summary AS
            SELECT 
                w.id AS workspace_id,
                w.client_name,
                w.industry,
                w.port,
                w.status,
                COALESCE(COUNT(DISTINCT c.id), 0) AS total_companies,
                COALESCE(COUNT(DISTINCT p.id), 0) AS total_prospects,
                COALESCE(COUNT(DISTINCT CASE WHEN o.status = 'sent' THEN o.id END), 0) AS emails_sent,
                COALESCE(COUNT(DISTINCT CASE WHEN o.status = 'pending_review' THEN o.id END), 0) AS emails_pending,
                COALESCE(COUNT(DISTINCT CASE WHEN o.status = 'failed' OR o.error IS NOT NULL THEN o.id END), 0) AS email_errors,
                MAX(o.sent_at) AS last_email_sent_at
            FROM public.workspaces w
            LEFT JOIN public.companies c ON c.workspace = w.id
            LEFT JOIN public.prospects p ON p.workspace = w.id
            LEFT JOIN public.outbox o ON o.workspace = w.id
            GROUP BY w.id, w.client_name, w.industry, w.port, w.status;
        """)

        # 5. Client-Dedicated Views for Clean Sidebar & Appsmith Portals
        cur.execute("""
            CREATE OR REPLACE VIEW public.dubai_realestate_prospects AS
            SELECT id, first_name, last_name, full_name, email, email_status, phone, linkedin_url, title, company, industry, score, status, personalization_notes, created_at, updated_at
            FROM public.prospects
            WHERE workspace = 'trackkaro_speed_to_lead';

            CREATE OR REPLACE VIEW public.dubai_realestate_companies AS
            SELECT id, name, domain, website, phone, industry, location, source, created_at
            FROM public.companies
            WHERE workspace = 'trackkaro_speed_to_lead';

            CREATE OR REPLACE VIEW public.dubai_realestate_outbox AS
            SELECT id, to_email, subject, body, status, sent_at, error, created_at, updated_at
            FROM public.outbox
            WHERE workspace = 'trackkaro_speed_to_lead';

            CREATE OR REPLACE VIEW public.cold_email_agency_prospects AS
            SELECT id, first_name, last_name, full_name, email, email_status, phone, linkedin_url, title, company, industry, score, status, personalization_notes, created_at, updated_at
            FROM public.prospects
            WHERE workspace = 'cold_email_outreach';

            CREATE OR REPLACE VIEW public.cold_email_agency_companies AS
            SELECT id, name, domain, website, phone, industry, location, source, created_at
            FROM public.companies
            WHERE workspace = 'cold_email_outreach';

            CREATE OR REPLACE VIEW public.cold_email_agency_outbox AS
            SELECT id, to_email, subject, body, status, sent_at, error, created_at, updated_at
            FROM public.outbox
            WHERE workspace = 'cold_email_outreach';
        """)

        pg_conn.commit()
        print("✅ Supabase Multi-Tenant Tables & Executive Views ready.")

def register_workspace(pg_conn, ws_id: str, client_name: str, industry: str, port: int, sheet_url: str = "", webhook_url: str = ""):
    with pg_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO public.workspaces (id, client_name, industry, port, sheet_url, webhook_url, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                client_name = EXCLUDED.client_name,
                industry = EXCLUDED.industry,
                port = EXCLUDED.port,
                sheet_url = EXCLUDED.sheet_url,
                webhook_url = EXCLUDED.webhook_url,
                updated_at = CURRENT_TIMESTAMP;
        """, (ws_id, client_name, industry, port, sheet_url, webhook_url))
        pg_conn.commit()

def sync_workspace(pg_conn, sqlite_path: Path, workspace_name: str):
    if not sqlite_path.exists():
        print(f"⚠️ SQLite DB not found: {sqlite_path}")
        return

    print(f"🔄 Syncing workspace '{workspace_name}' from {sqlite_path.name}...")
    sq_conn = sqlite3.connect(sqlite_path)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()
    pg_cur = pg_conn.cursor()

    # --- Sync Companies ---
    try:
        sq_cur.execute("SELECT id, name, domain, website, phone, industry, location, source, created_at FROM companies")
        companies = sq_cur.fetchall()
        comp_records = []
        for r in companies:
            comp_records.append((
                str(r["id"]), workspace_name, r["name"], r["domain"], r["website"],
                r["phone"], r["industry"], r["location"], r["source"], r["created_at"]
            ))
        if comp_records:
            query = """
                INSERT INTO public.companies (id, workspace, name, domain, website, phone, industry, location, source, created_at)
                VALUES %s
                ON CONFLICT (workspace, id) DO UPDATE SET
                    name = EXCLUDED.name,
                    domain = EXCLUDED.domain,
                    website = EXCLUDED.website,
                    phone = EXCLUDED.phone,
                    industry = EXCLUDED.industry,
                    location = EXCLUDED.location;
            """
            execute_values(pg_cur, query, comp_records)
            pg_conn.commit()
            print(f"  🏢 Companies synced: {len(comp_records)}")
    except Exception as e:
        print(f"  ⚠️ Error syncing companies: {e}")
        pg_conn.rollback()

    # --- Sync Prospects ---
    try:
        sq_cur.execute("""
            SELECT id, first_name, last_name, email, email_status, email_verified,
                   phone, linkedin_url, title, company, industry, score, status,
                   personalization_notes, created_at, updated_at
            FROM prospects
        """)
        prospects = sq_cur.fetchall()
        pros_records = []
        for r in prospects:
            full_name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
            pros_records.append((
                str(r["id"]), workspace_name, r["first_name"], r["last_name"], full_name,
                r["email"], r["email_status"], bool(r["email_verified"]), r["phone"],
                r["linkedin_url"], r["title"], r["company"], r["industry"],
                r["score"] or 0, r["status"], r["personalization_notes"],
                r["created_at"], r["updated_at"]
            ))
        if pros_records:
            query = """
                INSERT INTO public.prospects (
                    id, workspace, first_name, last_name, full_name, email, email_status,
                    email_verified, phone, linkedin_url, title, company, industry, score,
                    status, personalization_notes, created_at, updated_at
                )
                VALUES %s
                ON CONFLICT (workspace, id) DO UPDATE SET
                    email = EXCLUDED.email,
                    email_status = EXCLUDED.email_status,
                    status = EXCLUDED.status,
                    score = EXCLUDED.score,
                    updated_at = EXCLUDED.updated_at;
            """
            execute_values(pg_cur, query, pros_records)
            pg_conn.commit()
            print(f"  🎯 Prospects synced: {len(pros_records)}")
    except Exception as e:
        print(f"  ⚠️ Error syncing prospects: {e}")
        pg_conn.rollback()

    # --- Sync Outbox (Emails & Bounces) ---
    try:
        sq_cur.execute("SELECT id, to_email, subject, body, status, sent_at, error, created_at, updated_at FROM outbox")
        outbox = sq_cur.fetchall()
        outbox_records = []
        for r in outbox:
            outbox_records.append((
                str(r["id"]), workspace_name, r["to_email"], r["subject"], r["body"],
                r["status"], r["sent_at"], r["error"], r["created_at"], r["updated_at"]
            ))
        if outbox_records:
            query = """
                INSERT INTO public.outbox (
                    id, workspace, to_email, subject, body, status, sent_at, error, created_at, updated_at
                )
                VALUES %s
                ON CONFLICT (workspace, id) DO UPDATE SET
                    status = EXCLUDED.status,
                    sent_at = EXCLUDED.sent_at,
                    error = EXCLUDED.error,
                    updated_at = EXCLUDED.updated_at;
            """
            execute_values(pg_cur, query, outbox_records)
            pg_conn.commit()
            print(f"  ✉️ Outbox emails synced: {len(outbox_records)}")
    except Exception as e:
        print(f"  ⚠️ Error syncing outbox: {e}")
        pg_conn.rollback()

    sq_conn.close()

def main():
    pg_conn = get_supabase_conn()
    init_tables(pg_conn)

    # 1. Register and sync Root Workspace: TrackKaro Speed-to-Lead
    root_sheet = os.getenv("GOOGLE_SHEET_URL", "")
    root_webhook = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "")
    register_workspace(
        pg_conn,
        ws_id="trackkaro_speed_to_lead",
        client_name="Dubai & India Speed-to-Lead",
        industry="Real Estate & Aesthetic Clinics",
        port=5555,
        sheet_url=root_sheet,
        webhook_url=root_webhook
    )
    root_db = BASE_DIR / "data" / "harvey.db"
    sync_workspace(pg_conn, root_db, "trackkaro_speed_to_lead")

    # 2. Register and sync Workspace #2: Cold Email Outreach Retainer
    cold_dir = BASE_DIR / "workspaces" / "cold_email_outreach"
    cold_env = cold_dir / ".env"
    cold_sheet, cold_webhook = "", ""
    if cold_env.is_file():
        for line in cold_env.read_text().splitlines():
            if line.startswith("GOOGLE_SHEET_URL="):
                cold_sheet = line.split("=", 1)[1].strip()
            elif line.startswith("GOOGLE_SHEET_WEBHOOK_URL="):
                cold_webhook = line.split("=", 1)[1].strip()

    register_workspace(
        pg_conn,
        ws_id="cold_email_outreach",
        client_name="Cold Email Agency Retainer",
        industry="B2B SaaS & Dev Agencies",
        port=5556,
        sheet_url=cold_sheet,
        webhook_url=cold_webhook
    )
    cold_db = cold_dir / "data" / "harvey.db"
    sync_workspace(pg_conn, cold_db, "cold_email_outreach")

    # 3. Dynamic Auto-Discovery of any other client workspaces
    workspaces_dir = BASE_DIR / "workspaces"
    if workspaces_dir.is_dir():
        for client_path in workspaces_dir.iterdir():
            if client_path.is_dir() and client_path.name != "cold_email_outreach":
                client_db = client_path / "data" / "harvey.db"
                if client_db.is_file():
                    register_workspace(
                        pg_conn,
                        ws_id=client_path.name,
                        client_name=client_path.name.replace("_", " ").title(),
                        industry="Client Workspace",
                        port=0
                    )
                    sync_workspace(pg_conn, client_db, client_path.name)

    # 4. Print Summary from the Executive View
    with pg_conn.cursor() as cur:
        cur.execute("SELECT workspace_id, client_name, total_companies, total_prospects, emails_sent, emails_pending FROM public.view_workspace_summary")
        summary_rows = cur.fetchall()
        print("\n📊 --- LIVE SUPABASE MULTI-TENANT SUMMARY ---")
        for r in summary_rows:
            print(f"  • [{r[0]}] {r[1]}: {r[2]} Accounts, {r[3]} Prospects, {r[4]} Sent, {r[5]} In Outbox")

    pg_conn.close()
    print("\n🚀 All client workspaces successfully synchronized into Supabase!")

if __name__ == "__main__":
    main()
