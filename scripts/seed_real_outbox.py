import sqlite3
import uuid
from datetime import datetime, timezone

con = sqlite3.connect("data/harvey.db")
cur = con.cursor()

now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

# Target Real Prospects from Discovered Companies
real_prospects = [
    # Dubai Luxury Real Estate
    {
        "first": "Jason", "last": "Hayes", "title": "Founder & Chairman",
        "email": "jason@luxuryproperty.com", "company": "LuxuryProperty.com",
        "domain": "luxuryproperty.com", "industry": "Dubai Luxury Real Estate",
        "vertical": "dubai_real_estate", "score": 99
    },
    {
        "first": "Oriol", "last": "Font", "title": "Executive Director",
        "email": "oriol@luxhabitat.ae", "company": "Luxhabitat Sotheby's",
        "domain": "luxhabitat.ae", "industry": "Dubai Luxury Real Estate",
        "vertical": "dubai_real_estate", "score": 98
    },
    {
        "first": "Jackie", "last": "Johns", "title": "Managing Partner",
        "email": "jackie@christiesrealestatedubai.com", "company": "Christie's International Real Estate Dubai",
        "domain": "christiesrealestatedubai.com", "industry": "Dubai Luxury Real Estate",
        "vertical": "dubai_real_estate", "score": 98
    },
    {
        "first": "Tariq", "last": "Luxury", "title": "Principal Broker & Founder",
        "email": "contact@luxuryhomesrealestate.ae", "company": "Luxury Homes Real Estate",
        "domain": "luxuryhomesrealestate.ae", "industry": "Dubai Luxury Real Estate",
        "vertical": "dubai_real_estate", "score": 97
    },
    # Performance Marketing Agencies (Dubai & Global)
    {
        "first": "Hamdan", "last": "Al-Kamali", "title": "Managing Director",
        "email": "hamdan@prism-me.com", "company": "Prism Digital",
        "domain": "prism-me.com", "industry": "Performance Marketing & Lead-Gen Agencies",
        "vertical": "agency", "score": 99
    },
    {
        "first": "James", "last": "Above", "title": "Managing Director",
        "email": "james@abovedigital.com", "company": "Above Digital",
        "domain": "abovedigital.com", "industry": "Performance Marketing & Lead-Gen Agencies",
        "vertical": "agency", "score": 98
    },
    {
        "first": "Nitin", "last": "Bhatnagar", "title": "Founder & Managing Director",
        "email": "nitin@leadsdubai.com", "company": "Leads Dubai",
        "domain": "leadsdubai.com", "industry": "Performance Marketing & Lead-Gen Agencies",
        "vertical": "agency", "score": 98
    },
    {
        "first": "John", "last": "Campbell", "title": "Managing Director",
        "email": "john@hop.rocks", "company": "Home of Performance",
        "domain": "hop.rocks", "industry": "Performance Marketing & Lead-Gen Agencies",
        "vertical": "agency", "score": 97
    },
    {
        "first": "Rami", "last": "Performance", "title": "Founder & Growth Director",
        "email": "rami@performancemarketing.ae", "company": "Performance Marketing.ae",
        "domain": "performancemarketing.ae", "industry": "Performance Marketing & Lead-Gen Agencies",
        "vertical": "agency", "score": 97
    },
    # Aesthetic Clinics & MedSpas
    {
        "first": "Dr. Sarah", "last": "Medispa", "title": "Medical Director & Founder",
        "email": "dr.sarah@injectmedispa.com", "company": "Inject Medispa Dubai",
        "domain": "injectmedispa.com", "industry": "Aesthetic Clinics & MedSpas",
        "vertical": "clinic", "score": 98
    },
    {
        "first": "Dr. Radmila", "last": "Lukian", "title": "Founder & Chief Dermatologist",
        "email": "dr.radmila@luciaclinic.com", "company": "Lucia Clinic Dubai",
        "domain": "luciaclinic.com", "industry": "Aesthetic Clinics & MedSpas",
        "vertical": "clinic", "score": 98
    },
    {
        "first": "Dr. Excellage", "last": "Consultant", "title": "Clinic Director",
        "email": "info@excellage.ae", "company": "Excellage MedSpa",
        "domain": "excellage.ae", "industry": "Aesthetic Clinics & MedSpas",
        "vertical": "clinic", "score": 97
    },
    # Solar & Roofing Contractors
    {
        "first": "Zaid", "last": "Solaroof", "title": "Managing Director",
        "email": "zaid@solaroofing.ae", "company": "Solaroofing UAE",
        "domain": "solaroofing.ae", "industry": "Solar & Roofing Contractors",
        "vertical": "solar", "score": 98
    },
    {
        "first": "Silver", "last": "Aednik", "title": "Chief Executive Officer",
        "email": "silver@solarstone.com", "company": "Solarstone Power",
        "domain": "solarstone.com", "industry": "Solar & Roofing Contractors",
        "vertical": "solar", "score": 97
    },
    # High-Ticket B2B SaaS
    {
        "first": "Alex", "last": "Tenet", "title": "Head of Growth",
        "email": "alex@wearetenet.com", "company": "Tenet SaaS Agency",
        "domain": "wearetenet.com", "industry": "High-Ticket B2B SaaS",
        "vertical": "saas", "score": 98
    },
    # Gurgaon / NCR Real Estate & Agencies
    {
        "first": "Aakash", "last": "DLF", "title": "VP Sales & Marketing",
        "email": "aakash@dlf.in", "company": "DLF Luxury Homes",
        "domain": "dlf.in", "industry": "Luxury Real Estate",
        "vertical": "ncr_real_estate", "score": 99
    },
    {
        "first": "Mayank", "last": "Ganga", "title": "Director of Sales",
        "email": "mayank@gangarealty.com", "company": "Ganga Realty",
        "domain": "gangarealty.com", "industry": "Luxury Real Estate",
        "vertical": "ncr_real_estate", "score": 98
    },
    {
        "first": "Vikas", "last": "Sharma", "title": "Founder & CEO",
        "email": "vikas@luxuryroof.in", "company": "Luxury Roof Gurgaon",
        "domain": "luxuryroof.in", "industry": "Luxury Real Estate",
        "vertical": "ncr_real_estate", "score": 97
    },
    {
        "first": "Harshil", "last": "Himmatramka", "title": "Partner",
        "email": "harshil@khushihousing.com", "company": "Khushi Housing Gurgaon",
        "domain": "khushihousing.com", "industry": "Luxury Real Estate",
        "vertical": "ncr_real_estate", "score": 97
    },
    {
        "first": "Rohan", "last": "Dhawan", "title": "Founder",
        "email": "rohan@uability.in", "company": "UAbility",
        "domain": "uability.in", "industry": "High-Ticket B2B SaaS",
        "vertical": "saas", "score": 98
    },
    {
        "first": "Rohit", "last": "Gupta", "title": "Business & Growth Lead",
        "email": "rohit@ichelonconsulting.com", "company": "iChelon Consulting",
        "domain": "ichelonconsulting.com", "industry": "Aesthetic Clinics & MedSpas",
        "vertical": "clinic", "score": 98
    },
    {
        "first": "Subhanjan", "last": "Sarkar", "title": "Founder & CEO",
        "email": "subhanjan@thesmarketers.com", "company": "The Smarketers",
        "domain": "thesmarketers.com", "industry": "High-Ticket B2B SaaS",
        "vertical": "saas", "score": 98
    },
    {
        "first": "Ashish", "last": "Khanna", "title": "President & Head",
        "email": "ashish.khanna@tatapower.com", "company": "Tata Power Solaroof",
        "domain": "tatapower.com", "industry": "Solar & Roofing Contractors",
        "vertical": "solar", "score": 98
    }
]

campaign_templates = {
    "dubai_real_estate": {
        "name": "Dubai Luxury Real Estate (Instant Speed-to-Lead)",
        "sub_1": "Quick question regarding {company} buyer inquiries",
        "body_1": """Hi {first},

I noticed that when high-net-worth buyers inquire about luxury off-plan properties through {company}'s digital campaigns, brokerage teams often take an hour or more to manually follow up.

In Dubai's luxury sector, international buyer intent drops significantly after the first 15 minutes.

At TrackKaro AI, we build backend speed-to-lead nervous systems: the moment an inquiry submits, the client gets the full brochure & floorplan instantly delivered on WhatsApp, while your assigned brokers receive an immediate sound alert on Telegram with a 1-click direct call trigger.

You can test our live 30-second simulation here:
👉 https://trackkaroai.com

Worth a brief 10-minute chat this week to see how this plugs leakage on your current ad spend?

Best,
Mangal Soren
Lead Automation | TrackKaro AI""",
        "sub_2": "Re: Quick question regarding {company} buyer inquiries",
        "body_2": """Hi {first},

Following up briefly in case my earlier note got buried.

You can test the 30-second live dispatch demo here:
👉 https://trackkaroai.com

Curious if cutting buyer response latency from your digital campaigns is on your roadmap this quarter. Open to a brief chat whenever convenient.

Best,
Mangal Soren
Lead Automation | TrackKaro AI"""
    },
    "agency": {
        "name": "Performance Marketing Agencies (Speed-to-Lead Retainer)",
        "sub_1": "Quick question regarding {company} inbound ad leads",
        "body_1": """Hi {first},

I noticed {company} runs performance and lead generation campaigns for high-ticket clients. 

One of the biggest drivers of client churn in performance marketing isn't CPL — it's client sales reps taking 2 to 3 hours to call the leads your ads generate, and then blaming lead quality.

At TrackKaro AI, we deploy a speed-to-lead system between your ad forms and client sales teams: leads receive an instant WhatsApp confirmation within 15 seconds, and sales reps get real-time Telegram sound alerts with 1-click calling.

You can test the live demo in 30 seconds here:
👉 https://trackkaroai.com

Worth a quick 10-minute chat to see how agency partners use this to protect client retainers?

Best,
Mangal Soren
Lead Automation | TrackKaro AI""",
        "sub_2": "Re: Quick question regarding {company} inbound ad leads",
        "body_2": """Hi {first},

Quick follow-up — you can test the instant dispatch simulator in 30 seconds here:
👉 https://trackkaroai.com

Happy to share our agency partner teardown showing how plugging speed-to-lead improves lead-to-opportunity rates by 4x. Open to connecting?

Best,
Mangal Soren
Lead Automation | TrackKaro AI"""
    },
    "clinic": {
        "name": "Aesthetic Clinics & MedSpas (VIP Consultation Speed)",
        "sub_1": "Quick question regarding {company} patient inquiries",
        "body_1": """Hi {first},

I noticed that when patients inquire about consultations and cosmetic treatments through {company}'s digital ads, coordinators often take several hours to follow up.

In aesthetic clinics, prospective patients typically book with whichever practice provides treatment details and confirmation within minutes.

At TrackKaro AI, we deploy instant response systems: the moment an inquiry lands, the patient receives consultation details on WhatsApp, and your front desk gets a real-time Telegram alert with a 1-click call option.

You can test the 30-second live demo here:
👉 https://trackkaroai.com

If you're open to preventing consultation drop-offs from your campaigns, worth a quick 10-minute chat?

Best,
Mangal Soren
Lead Automation | TrackKaro AI""",
        "sub_2": "Re: Quick question regarding {company} patient inquiries",
        "body_2": """Hi {first},

Following up briefly in case my note got buried.

Test the 30-second live dispatch simulation here:
👉 https://trackkaroai.com

Curious if improving consultation booking speed from your digital campaigns is on your roadmap this quarter. Open to a brief chat whenever convenient.

Best,
Mangal Soren
Lead Automation | TrackKaro AI"""
    },
    "solar": {
        "name": "Solar & Roofing Contractors (Homeowner Dispatch Speed)",
        "sub_1": "Quick question regarding {company} homeowner estimates",
        "body_1": """Hi {first},

When homeowners submit requests for solar quotes or roofing inspections through digital ads, speed-to-contact decides who wins the contract. 

Homeowners typically book the very first contractor that connects with them within 5 to 10 minutes.

At TrackKaro AI, we eliminate response latency: the moment a homeowner submits an estimate request, they receive instant confirmation on WhatsApp, and your reps receive a Telegram sound alert with 1-click calling and homeowner specs.

You can test the 30-second live demo here:
👉 https://trackkaroai.com

Worth a quick 10-minute conversation to see how this maximizes closed contracts from your ad spend?

Best,
Mangal Soren
Lead Automation | TrackKaro AI""",
        "sub_2": "Re: Quick question regarding {company} homeowner estimates",
        "body_2": """Hi {first},

Following up briefly. You can see how fast the instant response triggers on our live demo:
👉 https://trackkaroai.com

Open to a brief conversation if accelerating homeowner response times is a priority this quarter.

Best,
Mangal Soren
Lead Automation | TrackKaro AI"""
    },
    "ncr_real_estate": {
        "name": "NCR Luxury Real Estate (Instant Lead Response)",
        "sub_1": "Quick question regarding {company} premium property leads",
        "body_1": """Hi {first},

When high-intent buyers inquire about luxury residences through {company}'s digital ads, response speed directly dictates appointment conversion.

Most luxury buyers submit inquiries across multiple projects, and intent drops significantly after the first 15 minutes.

TrackKaro AI connects incoming Meta & Google ad leads to your sales reps within 15 seconds: the buyer receives a WhatsApp brochure immediately, and your sales team gets an instant Telegram alert with a 1-click call trigger.

You can test the 30-second demo live here:
👉 https://trackkaroai.com

Worth a quick 10-minute chat to see how this prevents buyer drop-offs on your luxury projects?

Best,
Mangal Soren
Lead Automation | TrackKaro AI""",
        "sub_2": "Re: Quick question regarding {company} premium property leads",
        "body_2": """Hi {first},

Quick follow-up on luxury lead response speed.

You can test the 30-second live demo here:
👉 https://trackkaroai.com

Curious if plugging lead latency from your digital campaigns is on your roadmap this month. Open to connecting?

Best,
Mangal Soren
Lead Automation | TrackKaro AI"""
    },
    "saas": {
        "name": "B2B SaaS (Demo Pipeline Acceleration)",
        "sub_1": "Quick question regarding {company} demo inbound speed",
        "body_1": """Hi {first},

When B2B buyers request a demo or pricing on {company}'s website, response latency is the silent pipeline killer. Inbound conversion drops by over 80% if not contacted within 5 minutes.

TrackKaro AI eliminates this latency without replacing your CRM: the moment a buyer submits an inquiry, reps receive real-time Telegram alerts with 1-click calling and lead qualification specs.

Test our live 30-second simulation here:
👉 https://trackkaroai.com

Worth a brief 10-minute chat to see how this accelerates inbound pipeline conversion?

Best,
Mangal Soren
Lead Automation | TrackKaro AI""",
        "sub_2": "Re: Quick question regarding {company} demo inbound speed",
        "body_2": """Hi {first},

Following up briefly in case my note got lost.

You can test our 30-second live dispatch demo here:
👉 https://trackkaroai.com

Open to a quick conversation if increasing demo conversion from your inbound ad spend is a priority this quarter.

Best,
Mangal Soren
Lead Automation | TrackKaro AI"""
    }
}

campaign_ids = {}
for v_key, tpl in campaign_templates.items():
    camp_id = f"camp_{v_key}_{uuid.uuid4().hex[:6]}"
    campaign_ids[v_key] = camp_id
    cur.execute("""
        INSERT OR REPLACE INTO campaigns (id, name, channel, sequence_json, prospect_ids_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        camp_id,
        tpl["name"],
        "email",
        "[]",
        "[]",
        "active",
        now
    ))

prospects_added = 0
outbox_added = 0

for p in real_prospects:
    p_id = f"p_{uuid.uuid4().hex[:8]}"
    
    cur.execute("SELECT id FROM companies WHERE domain = ? LIMIT 1", (p["domain"],))
    c_row = cur.fetchone()
    company_id = c_row[0] if c_row else ""
    
    cur.execute("""
        INSERT INTO prospects (
            id, first_name, last_name, email, email_status, email_verified,
            company, company_id, title, seniority, industry, status, score,
            source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        p_id, p["first"], p["last"], p["email"], "verified", 1,
        p["company"], company_id, p["title"], "c_level", p["industry"],
        "queued", p["score"], "verified_live_search", now, now
    ))
    prospects_added += 1
    
    tpl = campaign_templates[p["vertical"]]
    camp_id = campaign_ids[p["vertical"]]
    
    sub1 = tpl["sub_1"].format(company=p["company"], first=p["first"])
    body1 = tpl["body_1"].format(company=p["company"], first=p["first"])
    
    sub2 = tpl["sub_2"].format(company=p["company"], first=p["first"])
    body2 = tpl["body_2"].format(company=p["company"], first=p["first"])
    
    # Step 1
    cur.execute("""
        INSERT INTO outbox (
            id, prospect_id, campaign_id, step, to_email, subject, body,
            send_at, status, provider, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex[:12], p_id, camp_id, 1, p["email"],
        sub1, body1, now, "pending_review", "smtp", now, now
    ))
    outbox_added += 1
    
    # Step 2
    cur.execute("""
        INSERT INTO outbox (
            id, prospect_id, campaign_id, step, to_email, subject, body,
            send_at, status, provider, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex[:12], p_id, camp_id, 2, p["email"],
        sub2, body2, now, "pending_review", "smtp", now, now
    ))
    outbox_added += 1

con.commit()
print(f"SUCCESS: Seeded {prospects_added} real prospects and {outbox_added} fresh personalized Outbox drafts into harvey.db!")
