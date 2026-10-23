"""Automated ICP priority scoring engine for TrackKaro AI."""

import hashlib


def compute_icp_score(
    company: str = "",
    industry: str = "",
    title: str = "",
    domain: str = "",
    email_status: str = "verified",
) -> tuple[int, str]:
    """Computes a calibrated, realistic ICP fit score (65 - 99) and detects industry.
    
    Weighted factors:
    - Target Niche conversion margin & speed-to-lead value
    - Decision maker title & seniority
    - Geography / Market (Dubai / UAE luxury vs domestic)
    - Deliverability confidence
    """
    company_lower = (company or "").lower()
    industry_lower = (industry or "").lower()
    title_lower = (title or "").lower()
    domain_lower = (domain or "").lower()

    # 1. Base Score by Niche
    if any(k in domain_lower for k in [".ae", "dubai", "uae", "damac", "emaar", "sobha", "binghatti", "danube"]) or any(
        k in industry_lower for k in ["dubai", "luxury real estate"]
    ) or any(k in company_lower for k in ["dubai", "uae", "damac", "emaar", "sobha", "sotheby", "christie", "estate", "luxury homes"]):
        score = 93
        detected_industry = "Dubai Luxury Real Estate"
    elif any(k in industry_lower for k in ["agency", "marketing", "lead-gen"]) or any(
        k in domain_lower for k in ["agency", "media", "scale", "digital", "leads", "ads", "ad", "growth", "performance"]
    ):
        score = 89
        detected_industry = "Performance Marketing & Lead-Gen Agencies"
    elif any(k in industry_lower for k in ["real estate", "realty", "property", "properties", "homes", "residences"]) or any(
        k in domain_lower for k in ["realty", "realtor", "property", "properties", "estates", "villas", "penthouses", "brokerage"]
    ):
        score = 86
        detected_industry = "Luxury Real Estate"
    elif any(k in industry_lower for k in ["saas", "software"]) or any(
        k in domain_lower for k in ["saas", "software", "tech", "app"]
    ):
        score = 82
        detected_industry = "High-Ticket B2B SaaS"
    elif any(k in industry_lower for k in ["clinic", "aesthetic", "medspa", "doctor", "skin", "derma"]) or any(
        k in domain_lower for k in ["clinic", "aesthetic", "medspa", "derma", "skin"]
    ):
        score = 81
        detected_industry = "Aesthetic Clinics & MedSpas"
    elif any(k in industry_lower for k in ["solar", "roof", "contractor", "energy"]) or any(
        k in domain_lower for k in ["solar", "roof", "roofing", "energy"]
    ):
        score = 76
        detected_industry = "Solar & Roofing Contractors"
    else:
        score = 80
        detected_industry = "High-Ticket Services"

    # 2. Decision Maker Title / Seniority (+2 to +5)
    if any(k in title_lower for k in ["founder", "ceo", "owner", "principal broker", "chairman"]):
        score += 5
    elif any(k in title_lower for k in ["managing director", "managing partner", "president"]):
        score += 4
    elif any(k in title_lower for k in ["director", "head of", "vp", "partner", "clinic director"]):
        score += 3
    elif any(k in title_lower for k in ["manager", "lead"]):
        score += 1

    # 3. Geo bonus (+2 for high-ticket international markets)
    if any(k in domain_lower for k in [".ae", "dubai", "uae", ".co.uk"]):
        score += 2

    # 4. Deliverability confidence
    if email_status == "verified":
        score += 1
    elif email_status == "risky":
        score -= 2

    # 5. Deterministic micro-variance (-1, 0, +1) so scores are distinct per brand
    seed_str = f"{company_lower}:{domain_lower}"
    h = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:4], 16) % 3 - 1
    score += h

    return max(65, min(99, score)), detected_industry
