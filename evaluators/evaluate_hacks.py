"""Evaluation and hard exclusion logic for Hackathons (Cash prizes, PPO/PPI, Team Sizes)."""

from datetime import datetime, timezone
import re
from typing import Any

from models import Evaluation

ALERT_THRESHOLD = 80

DELHI_NCR_KEYWORDS = (
    "delhi", "ncr", "gurgaon", "gurugram", "noida", "greater noida",
    "faridabad", "ghaziabad", "new delhi"
)

THEME_KEYWORDS = {
    "AI/GenAI": (r"\bai\b", r"\bgenai\b", r"\bllm\b", r"\brag\b", r"\bmachine\s+learning\b", r"\bdeep\s+learning\b", r"\bdata\s+science\b"),
    "Web3/Blockchain": (r"\bweb3\b", r"\bblockchain\b", r"\bsolana\b", r"\bethereum\b", r"\bcrypto\b", r"\bdefi\b", r"\bsmart\s+contracts?\b"),
    "Backend/Systems": (r"\bbackend\b", r"\bdevops\b", r"\bcloud\b", r"\bdistributed\b", r"\bsystems\b", r"\bapi\b", r"\bcybersecurity\b"),
}


def _parse_cash_prize_amount(text: str) -> float | None:
    """Parse cash prize amount normalized to USD."""
    if not text:
        return None

    # Check USD / USDC / USDT
    usd_match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(k)?", text, re.I)
    if usd_match:
        try:
            val = float(usd_match.group(1).replace(",", ""))
            if usd_match.group(2) or ("k" in usd_match.group(0).lower() and val < 500):
                val *= 1000
            return val
        except (ValueError, TypeError):
            pass

    # Check INR: e.g. "₹5,00,000", "5 Lakhs", "₹1,50,000"
    inr_lakh_match = re.search(r"([\d\.]+)\s*(?:lakhs?|lac|lpa)", text, re.I)
    if inr_lakh_match:
        try:
            lakhs = float(inr_lakh_match.group(1))
            inr_val = lakhs * 100000
            return inr_val / 83.0
        except (ValueError, TypeError):
            pass

    inr_match = re.search(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)", text, re.I)
    if inr_match:
        try:
            val = float(inr_match.group(1).replace(",", ""))
            return val / 83.0
        except (ValueError, TypeError):
            pass

    return None


def evaluate_hackathon(hackathon: dict[str, Any], *, now: datetime | None = None) -> Evaluation:
    """Evaluate a hackathon using strict exclusion rules and tiered scoring."""
    now = now or datetime.now(timezone.utc)
    title = str(hackathon.get("title") or "")
    desc = str(hackathon.get("description") or "")
    prize_pool = str(hackathon.get("prize_pool") or "")
    location = str(hackathon.get("location") or "")
    is_remote = bool(hackathon.get("is_remote"))
    full_text = f"{title} {desc} {prize_pool} {location}".lower()

    # --- HARD EXCLUSIONS (Zero Tolerance) ---

    # 1. No Certificate-Only / Free Swag Hackathons
    has_cash = bool(hackathon.get("has_cash_prize"))
    has_career = bool(hackathon.get("career_incentives"))
    is_cert_swag_only = bool(re.search(
        r"\b(?:certificates?\s+only|only\s+certificates?|swags?\s+only|free\s+swag\s+only|no\s+cash\s+prize)\b",
        full_text,
        re.I
    ))

    # Reject if explicit certificate-only without career incentives OR if neither cash prize nor career track exists
    if is_cert_swag_only and not has_career:
        return Evaluation(None, ("certificate-only/free swag with no cash pool or recruitment track",))
    if not has_cash and not has_career:
        return Evaluation(None, ("no tangible cash prize and no career/recruitment incentives",))

    # 2. Team Size Restriction: Reject hackathons where team size is STRICTLY 3 members (min == 3 and max == 3)
    team = hackathon.get("team_size") or {}
    min_team = int(team.get("min_team") or 1)
    max_team = int(team.get("max_team") or 4)

    if min_team == 3 and max_team == 3:
        return Evaluation(None, ("strictly 3-member team size restricted",))

    # 3. Location Constraint: Must be Online/Remote, unless hosted locally in Delhi-NCR
    if not is_remote and "online" not in location.lower() and "virtual" not in location.lower():
        is_delhi_ncr = any(kw in location.lower() for kw in DELHI_NCR_KEYWORDS)
        if not is_delhi_ncr:
            return Evaluation(None, (f"in-person event outside Delhi-NCR ({location})",))

    # 4. Student Eligibility: Must be open to University Students (Graduating 2027)
    if re.search(r"\b(?:working\s+professionals?\s+only|industry\s+professionals?\s+only|employees\s+only)\b", full_text, re.I):
        return Evaluation(None, ("restricted to working professionals only",))

    # --- SCORING PIPELINE (Threshold >= 80) ---
    score = 0
    reasons = []

    # A. Career Incentives (Highest Weight): +35 points
    career_match = re.search(
        r"\b(?:ppo|ppi|job\s+offer|interview\s+fast-?track|pre-?placement\s+offer|pre-?placement\s+interview|recruitment\s+track|hiring\s+partner)\b",
        full_text,
        re.I
    )
    if has_career or career_match:
        score += 35
        reasons.append("career incentives (PPO/PPI/Job fast-track)")

    # B. Cash Prize: Verified cash prize pool (> $1,000 or > ₹1,00,000): +25 points
    usd_val = _parse_cash_prize_amount(f"{prize_pool} {desc}")
    if usd_val is not None:
        if usd_val >= 1000:  # > $1,000 USD (~ ₹83,000 - ₹1,00,000 INR)
            score += 25
            reasons.append(f"verified cash prize pool (${usd_val:,.0f})")
        elif usd_val > 0:
            score += 15
            reasons.append(f"cash prize pool (${usd_val:,.0f})")
    elif has_cash:
        score += 20
        reasons.append(f"cash prize announced ({prize_pool or 'verified'})")

    # C. Theme / Domain Match (AI/GenAI, Web3/Blockchain, Backend/Systems): +20 points
    matched_themes = []
    for theme_name, patterns in THEME_KEYWORDS.items():
        if any(re.search(pat, full_text) for pat in patterns):
            matched_themes.append(theme_name)

    # Check tags as well
    tags_text = " ".join(hackathon.get("tags") or []).lower()
    for theme_name, patterns in THEME_KEYWORDS.items():
        if theme_name not in matched_themes and any(re.search(pat, tags_text) for pat in patterns):
            matched_themes.append(theme_name)

    if matched_themes:
        score += 20
        reasons.append(f"domain match: {', '.join(matched_themes)}")

    # D. Team Size Priority (Tiered Weighting)
    # Priority 1: Allows 4 members (or 4+ members allowed, e.g. max_team >= 4): +25 points
    # Priority 2: Allows 2 members (e.g. min_team <= 2 <= max_team): +15 points
    # Priority 3: Allows Solo Participation (min_team == 1): +10 points
    team_points = 0
    if max_team >= 4:
        team_points += 25
        reasons.append("allows 4+ members")
    elif min_team <= 2 <= max_team:
        team_points += 15
        reasons.append("allows 2 members")

    # If solo participation is also permitted
    if min_team == 1:
        if team_points > 0:
            # Flexible team (solo or group)
            score += team_points + 10
            reasons.append("solo participation allowed")
        else:
            score += 10
            reasons.append("solo participation allowed")
    else:
        score += team_points

    return Evaluation(score, tuple(reasons))
