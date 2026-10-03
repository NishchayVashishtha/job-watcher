"""Deterministic eligibility and personal relevance scoring."""

from datetime import datetime, timezone
import re

from config import MAX_POSTING_AGE_DAYS, PROFILE, Profile
from models import Evaluation, Job

SENIOR_TITLE = re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|head of)\b", re.I)
ENTRY_TITLE = re.compile(r"\b(?:intern|internship|graduate|new grad|fresher|junior|entry.level|associate)\b", re.I)
EXPERIENCE_REQUIREMENT = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)\b", re.I
)
MANDATORY_YEARS = re.compile(r"\b(\d{1,2})\s*\+\s*years?\s+(?:mandatory|required)\b", re.I)
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
    "web3": (r"\bweb3(?:\.js)?\b", r"\bblockchain\b", r"\bsolana\b", r"\balgorand\b"),
    "java": (r"\bjava\b",),
    "pgvector": (r"\bpgvector\b",),
}


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
    if SENIOR_TITLE.search(title):
        return Evaluation(None, ("senior role title",))

    years = job.experience_min_years
    if years is None:
        years = _mandatory_years(title + "\n" + (job.description or ""))
    if years is not None and years > profile.max_required_years:
        return Evaluation(None, (f"requires {years}+ years",))

    if job.employment_type and job.employment_type not in profile.job_types:
        return Evaluation(None, (f"{job.employment_type} is outside selected job types",))
    if (job.employment_type == "internship" and not profile.accept_unpaid_internships
            and job.compensation and re.search(r"\b(?:unpaid|no stipend)\b", job.compensation, re.I)):
        return Evaluation(None, ("unpaid internship",))

    if profile.allowed_locations and job.location:
        location = job.location.casefold()
        # "Remote" alone does not say where a person is eligible to work.
        if not any(place.casefold() in location for place in profile.allowed_locations):
            # A city-only preference cannot establish eligibility for a remote
            # role labelled with a country, so keep it for manual review.
            if "remote" not in location and "everywhere" not in location:
                return Evaluation(None, ("location outside selected places",))

    if job.posted_at and (now - job.posted_at).total_seconds() > MAX_POSTING_AGE_DAYS * 86400:
        return Evaluation(None, ("older than posting-age limit",))

    score = 0
    reasons = []
    if any(_contains(title, term) for term in profile.role_terms):
        score += 45
        reasons.append("preferred role")
    elif re.search(r"\b(?:software|developer|engineering)\b", title, re.I):
        score += 15
        reasons.append("related engineering role")

    if job.employment_type == "internship" or ENTRY_TITLE.search(title):
        score += 25
        reasons.append("early-career role")
    elif years is not None and years <= 1:
        score += 25
        reasons.append("0–1 years experience")
    elif years == 2:
        score += 15
        reasons.append("2 years experience")

    skills = _technology_matches(job, profile)
    if skills:
        score += min(20, len(skills) * 5)
        reasons.append("skills: " + ", ".join(skills[:4]))

    if job.workplace_type and job.workplace_type in profile.preferred_workplaces:
        score += 5
        reasons.append(f"preferred {job.workplace_type} work")

    if job.posted_at and 0 <= (now - job.posted_at).total_seconds() <= 3 * 86400:
        score += 5
        reasons.append("posted recently")
    return Evaluation(score, tuple(reasons))
