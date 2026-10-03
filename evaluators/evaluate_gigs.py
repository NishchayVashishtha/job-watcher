"""Evaluation and filtering for freelance gigs, bounties, and contracts."""

import html
import re
from typing import Any

from models import Evaluation

ALERT_THRESHOLD = 80

GEOGRAPHIC_EXCLUSIONS = re.compile(
    r"\b(?:"
    r"us\s+(?:only|freelancers?\s+only|citizens?\s+only)|"
    r"usa\s+only|united\s+states\s+only|"
    r"must\s+be\s+located\s+in\s+the\s+(?:us|usa|united\s+states|uk|europe)|"
    r"north\s+america\s+only|latam\s+only|europe\s+only|emea\s+only|"
    r"canada\s+only|uk\s+only|australia\s+only"
    r")\b",
    re.I
)

ONSITE_PATTERNS = re.compile(
    r"\b(?:onsite\s+required|must\s+relocate|in[- ]office\s+required|hybrid\s+required|in[- ]person\s+required)\b",
    re.I
)

TECH_KEYWORDS = {
    "AI/GenAI/RAG": (
        r"\bgenai\b", r"\bgenerative\s+ai\b", r"\brag\b", r"\blangchain\b",
        r"\bllm\b", r"\bai\s+agent[s]?\b", r"\bpytorch\b", r"\bopenai\b",
        r"\bvector\b", r"\bpgvector\b", r"\bhuggingface\b", r"\bartificial\s+intelligence\b"
    ),
    "Web3/Blockchain": (
        r"\bweb3\b", r"\bsolana\b", r"\bsolidity\b", r"\bsmart\s+contract[s]?\b",
        r"\bethereum\b", r"\bblockchain\b", r"\brust\b", r"\bdefi\b", r"\bcrypto\b"
    ),
    "Backend/DevOps": (
        r"\bbackend\b", r"\bfastapi\b", r"\bpython\b", r"\bdocker\b",
        r"\bpostgresql\b", r"\bpostgres\b", r"\bnode(?:\.js)?\b", r"\bflask\b",
        r"\bdevops\b", r"\blinux\b", r"\brest\s+api\b", r"\bmicroservices\b"
    ),
}


def _extract_budget_amount(gig: dict[str, Any]) -> tuple[float | None, bool]:
    """Extract numeric compensation value and whether it is hourly."""
    if gig.get("hourly_rate") is not None:
        return float(gig["hourly_rate"]), True
    if gig.get("fixed_budget") is not None:
        return float(gig["fixed_budget"]), False

    prize = str(gig.get("prize_pool") or "").strip()
    desc = str(gig.get("description") or "")
    text = f"{prize} {desc}"

    # Hourly check
    hourly_match = re.search(r"\$([\d\.]+)\s*(?:/(?:hr|hour)|per\s+hour)", text, re.I)
    if hourly_match:
        return float(hourly_match.group(1)), True

    # Hourly range
    range_match = re.search(r"\$([\d\.]+)\s*(?:-|to)\s*\$([\d\.]+)\s*(?:/(?:hr|hour)|per\s+hour)", text, re.I)
    if range_match:
        return float(range_match.group(2)), True

    # Fixed dollar budget: e.g. "$1,500 USDC", "$500"
    fixed_match = re.search(r"\$([\d,]+(?:\.\d+)?)\s*(?:usdc|usdt|usd)?", text, re.I)
    if fixed_match:
        return float(fixed_match.group(1).replace(",", "")), False

    # INR budget: e.g. "₹25,000"
    inr_match = re.search(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)", text, re.I)
    if inr_match:
        try:
            val = float(inr_match.group(1).replace(",", ""))
            return val / 83.0, False  # normalized to USD
        except (ValueError, TypeError):
            pass

    return None, False


def evaluate_gig(gig: dict[str, Any]) -> Evaluation:
    """Evaluate a freelance gig/bounty against target criteria. Threshold >= 80 to pass."""
    title = str(gig.get("title") or "")
    desc = str(gig.get("description") or "")
    location = str(gig.get("location") or "")
    is_remote = gig.get("is_remote")
    full_text = f"{title} {desc} {location}".lower()

    # 1. Location Constraint: MUST be strictly 100% Remote
    if is_remote is False:
        return Evaluation(None, ("onsite presence required",))
    if ONSITE_PATTERNS.search(full_text):
        return Evaluation(None, ("onsite presence required",))
    if location and "remote" not in location.lower() and "online" not in location.lower():
        return Evaluation(None, ("location is not 100% remote",))

    # 2. Eligibility check: Reject geographic restrictions (e.g. US freelancers only)
    if GEOGRAPHIC_EXCLUSIONS.search(full_text):
        return Evaluation(None, ("geographically restricted (e.g. US-only)",))

    score = 0
    reasons = []

    # 3. Base Tech Stack Match (Up to +50 points)
    matched_domains = []
    matched_skills = []
    for domain, patterns in TECH_KEYWORDS.items():
        domain_matched = False
        for pat in patterns:
            match = re.search(pat, full_text)
            if match:
                domain_matched = True
                matched_skills.append(match.group(0))
        if domain_matched:
            matched_domains.append(domain)

    if matched_skills:
        # +15 points per matched skill or domain, capped at +50
        tech_score = min(50, len(matched_skills) * 15)
        score += tech_score
        reasons.append(f"tech match ({', '.join(matched_domains)}): {', '.join(matched_skills[:3])}")
    else:
        # No tech stack match
        return Evaluation(None, ("no matching tech stack for AI/Web3/Backend",))

    # 4. High Budget / Hourly Rate > $15 (+35 points)
    amount, is_hourly = _extract_budget_amount(gig)
    if is_hourly:
        if amount and amount >= 15:
            score += 35
            reasons.append(f"high hourly rate (${amount:g}/hr)")
        elif amount and amount < 15:
            reasons.append(f"low hourly rate (${amount:g}/hr)")
    elif amount is not None:
        if amount >= 100:  # >= $100 fixed bounty/contract
            score += 35
            reasons.append(f"verified budget (${amount:g})")
        else:
            reasons.append(f"budget under $100 (${amount:g})")
    elif gig.get("has_cash_prize"):
        # Verified cash / contract rate
        score += 25
        reasons.append("paid contract/bounty")

    # 5. Career incentives / Long-term potential (+10 bonus)
    if gig.get("career_incentives"):
        score += 10
        reasons.append("career incentive / contract-to-hire")

    return Evaluation(score, tuple(reasons))
