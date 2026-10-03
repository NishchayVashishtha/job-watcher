"""Deterministic eligibility and personal relevance scoring with advanced geo-fencing & stipend parsing."""

from datetime import datetime, timezone
import re

from config import MAX_POSTING_AGE_DAYS, PROFILE, Profile
from models import Evaluation, Job

SENIOR_TITLE = re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|architect|manager|director|head of|vp)\b", re.I)
ENTRY_TITLE = re.compile(r"\b(?:intern|internship|graduate|new grad|fresher|junior|entry.level|associate|trainee)\b", re.I)
EXPERIENCE_REQUIREMENT = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)\b", re.I
)
MANDATORY_YEARS = re.compile(r"\b(\d{1,2})\s*\+\s*years?\s+(?:mandatory|required)\b", re.I)

HOME_REGION_KEYWORDS = (
    "delhi", "ncr", "gurgaon", "gurugram", "noida", "greater noida",
    "uttar pradesh", "up", "haryana", "faridabad", "ghaziabad",
)

INDIA_LOCATION_KEYWORDS = (
    "india", "delhi", "ncr", "gurgaon", "gurugram", "noida", "greater noida",
    "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "chennai", "kolkata",
    "ahmedabad", "jaipur", "chandigarh", "kochi", "coimbatore", "indore", "surat",
    "uttar pradesh", "haryana", "karnataka", "maharashtra", "telangana", "tamil nadu",
    "kerala", "gujarat", "rajasthan", "punjab", "west bengal", "faridabad", "ghaziabad",
)

INTERNATIONAL_NON_INDIA_PATTERNS = re.compile(
    r"\b(?:"
    r"united states|usa|u\.s\.a\.|u\.s\.|united kingdom|uk|u\.k\.|canada|germany|france|"
    r"singapore|australia|netherlands|ireland|switzerland|israel|japan|sweden|"
    r"san francisco|new york|nyc|seattle|austin|boston|chicago|los angeles|london|berlin|"
    r"paris|toronto|vancouver|amsterdam|dublin|sydney|melbourne|tokyo|zurich"
    r")\b",
    re.I
)

RESTRICTED_REMOTE_PATTERNS = re.compile(
    r"\b(?:"
    r"us\s+only|usa\s+only|united\s+states\s+only|uk\s+only|united\s+kingdom\s+only|"
    r"europe\s+only|eu\s+only|emea\s+only|americas?\s+only|latam\s+only|north\s+america\s+only|"
    r"us\s*[/,&]\s*canada\s+only|canada\s+only|"
    r"must\s+be\s+(?:located\s+in|based\s+in|living\s+in|resident\s+of)\s+(?:the\s+)?(?:us|usa|united\s+states|uk|europe|eu|canada|americas?|north\s+america)|"
    r"timezone\s+restricted\s+to\s+(?:americas?|emea|us|eu|est|pst|cst|mst)|"
    r"only\s+(?:us|usa|uk|eu)\s+citizens|us\s+work\s+authorization\s+required"
    r")\b",
    re.I
)

TECH_ALIASES = {
    "node.js": (r"\bnode(?:\.js|js)\b",),
    "go": (r"\bgo\b", r"\bgolang\b"),
    "postgresql": (r"\bpostgres(?:ql)?\b",),
    "fastapi": (r"\bfastapi\b",),
    "python": (r"\bpython\b",),
    "docker": (r"\bdocker\b",),
    "linux": (r"\blinux\b",),
    "flask": (r"\bflask\b",),
    "react": (r"\breact(?:\.js|js)?\b",),
    "typescript": (r"\btypescript\b",),
    "javascript": (r"\bjavascript\b",),
    "pytorch": (r"\bpytorch\b",),
    "langchain": (r"\blangchain\b",),
    "rag": (r"\brag\b", r"\bretrieval[- ]augmented\b"),
    "solidity": (r"\bsolidity\b",),
    "web3": (r"\bweb3(?:\.js)?\b", r"\bblockchain\b", r"\bsolana\b", r"\balgorand\b", r"\bethereum\b"),
    "java": (r"\bjava\b",),
    "pgvector": (r"\bpgvector\b",),
}


def parse_stipend_amount(text: str | None) -> int | None:
    """Parse numerical stipend amount normalized to monthly INR."""
    if not text:
        return None
    cleaned = str(text).strip()
    if not cleaned:
        return None

    # Check for explicit unpaid mentions
    if re.search(r"\b(?:unpaid|no\s+stipend|volunteer|expenses\s+only|certificate\s+only|0\s*inr|0\s*per|free)\b", cleaned, re.I):
        return 0

    # Check for USD / foreign currencies (convert 1 USD ~ 83 INR)
    usd_match = re.search(r"(?:\$|usd)\s*([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:/(?:mo|month|pm|hr|hour)|per\s+(?:month|hr))?", cleaned, re.I)
    if usd_match:
        try:
            val = float(usd_match.group(1).replace(",", ""))
            if usd_match.group(2) or ("k" in usd_match.group(0).lower() and val < 500):
                val *= 1000
            if "/hr" in usd_match.group(0).lower() or "per hr" in usd_match.group(0).lower():
                val *= 160  # ~160 hours/month
            return int(val * 83)
        except (ValueError, Exception):
            pass

    # Check for LPA / Lakhs per annum (e.g. "3.6 LPA", "6 Lakhs/year")
    lpa_match = re.search(r"([\d\.]+)\s*(?:lpa|lakhs?(?:\s*per\s*annum|\s*/\s*yr|\s*/\s*year)?)", cleaned, re.I)
    if lpa_match and ("lpa" in cleaned.lower() or "lakh" in cleaned.lower() or "annum" in cleaned.lower() or "year" in cleaned.lower()):
        try:
            lakhs = float(lpa_match.group(1))
            monthly = (lakhs * 100_000) / 12
            return int(monthly)
        except (ValueError, Exception):
            pass

    # Look for 'k' notation: e.g. "25k/month", "20k", "₹20k - ₹30k", "25K"
    k_matches = re.findall(r"(\d+(?:\.\d+)?)\s*k\b", cleaned, re.I)
    if k_matches:
        try:
            amounts = [int(float(m) * 1000) for m in k_matches]
            return min(amounts)
        except (ValueError, Exception):
            pass

    # Look for full numerical numbers: "25,000", "₹20,000", "20000"
    num_matches = re.findall(r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})+|\d{4,7})", cleaned, re.I)
    if num_matches:
        try:
            amounts = [int(m.replace(",", "")) for m in num_matches]
            # Exclude current calendar years (2023-2030) if matched as isolated numbers
            valid = [a for a in amounts if not (2023 <= a <= 2030)]
            if valid:
                val = min(valid)
                if val > 150_000 and re.search(r"\b(?:year|yr|annum|pa)\b", cleaned, re.I):
                    return int(val / 12)
                return val
        except (ValueError, Exception):
            pass

    return None


def _contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))


def _technology_matches(job: Job, profile: Profile) -> list[str]:
    # The word "go" in prose is ambiguous. Only a title or explicit skill tag
    # can count it; "Golang" can count anywhere.
    explicit = " ".join((job.title, *job.skills))
    full = " ".join((explicit, job.description or ""))
    found = []
    for skill in profile.skills:
        key = skill.casefold()
        aliases = TECH_ALIASES.get(key, (r"(?<!\w)" + re.escape(skill) + r"(?!\w)",))
        haystack = explicit if key == "go" else full
        if any(re.search(pattern, haystack, re.I) for pattern in aliases):
            found.append(skill)
        elif key == "go" and re.search(r"\bgolang\b", full, re.I):
            found.append(skill)
    return found


def _mandatory_years(description: str | None) -> int | None:
    if not description:
        return None
    years = []
    for line in description.splitlines():
        if re.search(r"\b(?:preferred|nice to have|plus)\b", line, re.I):
            continue
        if re.search(r"\b(?:required|mandatory|must have|minimum|at least)\b", line, re.I):
            years.extend(int(m.group(1)) for m in EXPERIENCE_REQUIREMENT.finditer(line))
            years.extend(int(m.group(1)) for m in MANDATORY_YEARS.finditer(line))
    return min(years) if years else None


def evaluate(job: Job, profile: Profile = PROFILE, *, now: datetime | None = None) -> Evaluation:
    now = now or datetime.now(timezone.utc)
    title = job.title.strip()
    full_text = f"{job.title}\n{job.company or ''}\n{job.location or ''}\n{job.description or ''}\n{job.compensation or ''}"

    # 1. Senior hard exclusion
    if SENIOR_TITLE.search(title):
        return Evaluation(None, ("senior role title",))

    # 2. Mandatory experience exclusion
    years = job.experience_min_years
    if years is None:
        years = _mandatory_years(title + "\n" + (job.description or ""))
    if years is not None and years > profile.max_required_years:
        return Evaluation(None, (f"requires {years}+ years",))

    # 3. Employment type exclusion
    if job.employment_type and job.employment_type not in profile.job_types:
        return Evaluation(None, (f"{job.employment_type} is outside selected job types",))

    # 4. Determine workplace type & location characteristics
    location_str = (job.location or "").strip()
    location_lower = location_str.casefold()
    is_remote = (
        (job.workplace_type == "remote")
        or ("remote" in location_lower)
        or ("work from home" in location_lower)
        or ("anywhere" in location_lower)
        or ("everywhere" in location_lower)
    )

    # 5. Remote Roles Rule: Globally accepted unless explicitly restricted to outside regions
    if is_remote:
        if RESTRICTED_REMOTE_PATTERNS.search(full_text):
            return Evaluation(None, ("remote restricted to outside region",))
    else:
        # 6. Onsite / Hybrid Roles Rule: Must STRICTLY be in India
        if location_str:
            is_india = any(kw in location_lower for kw in INDIA_LOCATION_KEYWORDS)
            has_intl = bool(INTERNATIONAL_NON_INDIA_PATTERNS.search(location_str))
            if has_intl and not is_india:
                return Evaluation(None, ("international onsite/hybrid role",))
            if not is_india and not is_remote:
                # If location does not match any known Indian place and is not remote
                if any(INTERNATIONAL_NON_INDIA_PATTERNS.search(part) for part in location_str.split(",")):
                    return Evaluation(None, ("international onsite/hybrid role",))

    # 7. Internship & Geo-Fenced Stipend Filter
    is_internship = (job.employment_type == "internship") or bool(ENTRY_TITLE.search(title))
    stipend_val = parse_stipend_amount(f"{job.compensation or ''} {job.description or ''}")

    if is_internship:
        if not profile.accept_unpaid_internships:
            # Reject explicitly unpaid internships
            if stipend_val == 0 or (job.compensation and re.search(r"\b(?:unpaid|no stipend)\b", job.compensation, re.I)):
                return Evaluation(None, ("unpaid internship",))

        # Check Onsite / Hybrid internship relocation rule
        if not is_remote and (job.workplace_type in ("onsite", "hybrid") or location_str):
            is_home_region = any(k in location_lower for k in HOME_REGION_KEYWORDS)
            if not is_home_region and location_str:
                # Outside home region (Bengaluru, Pune, Hyderabad, Mumbai, etc.) requires >= ₹20,000/month
                if stipend_val is None or stipend_val < 20000:
                    return Evaluation(None, ("relocation requires stipend >= 20k/month (unspecified or below threshold)",))

    # 8. Posting age limit
    if job.posted_at and (now - job.posted_at).total_seconds() > MAX_POSTING_AGE_DAYS * 86400:
        return Evaluation(None, ("older than posting-age limit",))

    # 9. Relevance Scoring (Deterministic >= 80 to pass)
    score = 0
    reasons = []

    # Role relevance
    if any(_contains(title, term) for term in profile.role_terms):
        score += 45
        reasons.append("preferred role")
    elif re.search(r"\b(?:software|developer|engineering)\b", title, re.I):
        score += 15
        reasons.append("related engineering role")

    # Early-career / experience level
    if is_internship or ENTRY_TITLE.search(title):
        score += 25
        reasons.append("early-career role")
    elif years is not None and years <= 1:
        score += 25
        reasons.append("0–1 years experience")
    elif years == 2:
        score += 15
        reasons.append("2 years experience")

    # Tech stack matching (AI/GenAI/RAG, Web3/Blockchain, Backend, etc.)
    skills = _technology_matches(job, profile)
    if skills:
        score += min(20, len(skills) * 5)
        reasons.append("skills: " + ", ".join(skills[:4]))

    # Workplace type preference
    if job.workplace_type and job.workplace_type in profile.preferred_workplaces:
        score += 5
        reasons.append(f"preferred {job.workplace_type} work")

    # Recency bonus
    if job.posted_at and 0 <= (now - job.posted_at).total_seconds() <= 3 * 86400:
        score += 5
        reasons.append("posted recently")

    return Evaluation(score, tuple(reasons))
