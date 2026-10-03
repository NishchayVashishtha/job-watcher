"""Generic fetcher for unauthenticated ATS JSON endpoints (AshbyHQ, Greenhouse, Lever)."""

from datetime import datetime, timezone
import html
import logging
import re
from typing import Any
import requests

from config import HTTP_TIMEOUT
from models import Job, canonical_url, job_id, parse_posted_at

LOGGER = logging.getLogger(__name__)

# Curated tech companies in AI, Web3, Backend & High Growth Infrastructure
DEFAULT_ASHBY_SLUGS = (
    "openai", "anthropic", "cohere", "supabase", "posthog", "replicate", "cursor",
    "perplexity", "togetherai", "mistral", "modal", "langchain", "groq",
)

DEFAULT_GREENHOUSE_SLUGS = (
    "figma", "stripe", "scaleai", "databricks", "vercel", "cloudflare", "discord",
    "razorpay", "swiggy", "zepto", "browserstack", "polygon", "matterlabs",
)

DEFAULT_LEVER_SLUGS = (
    "palantir", "ripple", "consensys", "kraken", "wintermute", "jumpcrypto",
    "zerodha", "cred",
)


def _clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(" ".join(text.split())).strip()


def parse_ashby_job(job_data: dict[str, Any], company_slug: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Parse a single job record from AshbyHQ public API."""
    now = now or datetime.now(timezone.utc)
    job_id_val = str(job_data.get("id") or "")
    title = job_data.get("title") or ""
    apply_url = job_data.get("jobUrl") or f"https://jobs.ashbyhq.com/{company_slug}/{job_id_val}"

    if not title or not apply_url:
        return None

    try:
        url = canonical_url(apply_url)
    except (ValueError, Exception):
        url = apply_url

    location = job_data.get("location") or ""
    secondary = job_data.get("secondaryLocations") or []
    if secondary:
        sec_names = [s.get("location", "") for s in secondary if isinstance(s, dict)]
        if sec_names:
            location = f"{location}, {', '.join(filter(None, sec_names))}".strip(", ")

    is_remote = job_data.get("isRemote", False)
    workplace_type = "remote" if is_remote else "unknown"
    if not is_remote and location:
        if "remote" in location.lower():
            workplace_type = "remote"
        elif "hybrid" in location.lower():
            workplace_type = "hybrid"
        else:
            workplace_type = "onsite"

    # Compensation parsing from Ashby structured field or text
    stipend = None
    comp = job_data.get("compensation")
    if isinstance(comp, dict):
        summary = comp.get("compensationSummary")
        if summary:
            stipend = str(summary)
    
    desc = _clean_html(job_data.get("descriptionHtml") or "")
    posted_date = job_data.get("publishedAt") or now.isoformat()

    return {
        "id": job_id("ashby", url, job_id_val),
        "title": title,
        "company": company_slug.title(),
        "location": location or ("Remote" if is_remote else "Unspecified"),
        "stipend": stipend,
        "url": url,
        "workplace_type": workplace_type,
        "posted_date": posted_date,
        "description": desc,
    }


def parse_greenhouse_job(job_data: dict[str, Any], company_slug: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Parse a single job record from Greenhouse public API."""
    now = now or datetime.now(timezone.utc)
    job_id_val = str(job_data.get("id") or "")
    title = job_data.get("title") or ""
    apply_url = job_data.get("absolute_url") or ""

    if not title or not apply_url:
        return None

    try:
        url = canonical_url(apply_url)
    except (ValueError, Exception):
        url = apply_url

    loc_obj = job_data.get("location")
    location = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj or "")

    workplace_type = "unknown"
    loc_lower = (location + " " + title).lower()
    if "remote" in loc_lower or "anywhere" in loc_lower:
        workplace_type = "remote"
    elif "hybrid" in loc_lower:
        workplace_type = "hybrid"
    elif location:
        workplace_type = "onsite"

    desc = _clean_html(job_data.get("content") or "")
    posted_date = job_data.get("updated_at") or now.isoformat()

    stipend = None
    stipend_match = re.search(r"(?:₹|\$|INR|USD)\s*[\d,kK\.]+(?:\s*(?:-|to)\s*(?:₹|\$|INR|USD)?\s*[\d,kK\.]+)?(?:\s*(?:per|/)\s*(?:month|mo|pm|year|yr|hr))?", desc, re.I)
    if stipend_match:
        stipend = stipend_match.group(0).strip()

    return {
        "id": job_id("greenhouse", url, job_id_val),
        "title": title,
        "company": company_slug.title(),
        "location": location or ("Remote" if workplace_type == "remote" else "Unspecified"),
        "stipend": stipend,
        "url": url,
        "workplace_type": workplace_type,
        "posted_date": posted_date,
        "description": desc,
    }


def parse_lever_job(job_data: dict[str, Any], company_slug: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Parse a single job record from Lever public API."""
    now = now or datetime.now(timezone.utc)
    job_id_val = str(job_data.get("id") or "")
    title = job_data.get("text") or ""
    apply_url = job_data.get("hostedUrl") or job_data.get("applyUrl") or ""

    if not title or not apply_url:
        return None

    try:
        url = canonical_url(apply_url)
    except (ValueError, Exception):
        url = apply_url

    categories = job_data.get("categories") or {}
    location = categories.get("location") or ""
    raw_workplace = str(job_data.get("workplaceType") or "").lower()

    workplace_type = "unknown"
    if "remote" in raw_workplace or "remote" in location.lower():
        workplace_type = "remote"
    elif "hybrid" in raw_workplace or "hybrid" in location.lower():
        workplace_type = "hybrid"
    elif location:
        workplace_type = "onsite"

    desc = job_data.get("descriptionPlain") or ""
    created_ts = job_data.get("createdAt")
    posted_date = datetime.fromtimestamp(created_ts / 1000, tz=timezone.utc).isoformat() if created_ts else now.isoformat()

    stipend = None
    stipend_match = re.search(r"(?:₹|\$|INR|USD)\s*[\d,kK\.]+(?:\s*(?:-|to)\s*(?:₹|\$|INR|USD)?\s*[\d,kK\.]+)?(?:\s*(?:per|/)\s*(?:month|mo|pm|year|yr|hr))?", desc, re.I)
    if stipend_match:
        stipend = stipend_match.group(0).strip()

    return {
        "id": job_id("lever", url, job_id_val),
        "title": title,
        "company": company_slug.title(),
        "location": location or ("Remote" if workplace_type == "remote" else "Unspecified"),
        "stipend": stipend,
        "url": url,
        "workplace_type": workplace_type,
        "posted_date": posted_date,
        "description": desc,
    }


def dict_to_job(record: dict[str, Any], *, now: datetime | None = None) -> Job | None:
    """Convert normalized dictionary to models.Job instance."""
    now = now or datetime.now(timezone.utc)
    raw_title = record.get("title") or "Software Engineer"
    url = record.get("url")
    if not url or not url.startswith("http"):
        return None

    employment = "internship" if re.search(r"\bintern(?:ship)?\b", raw_title, re.I) else "fulltime"

    return Job(
        id=record.get("id") or job_id("ats", url),
        source="ats_api",
        title=raw_title,
        url=url,
        company=record.get("company"),
        location=record.get("location"),
        compensation=record.get("stipend"),
        description=record.get("description"),
        posted_at=parse_posted_at(record.get("posted_date"), now),
        employment_type=employment,
        workplace_type=record.get("workplace_type") or "unknown",
    )


def fetch_ashby_slug(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs for a single Ashby company slug."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        resp = requests.get(url, headers={"User-Agent": "PersonalJobWatcher/1.0"}, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            jobs = data.get("jobs", [])
            return [parsed for j in jobs if (parsed := parse_ashby_job(j, slug))]
    except Exception as exc:
        LOGGER.debug("Ashby slug '%s' failed: %s: %s", slug, type(exc).__name__, exc)
    return []


def fetch_greenhouse_slug(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs for a single Greenhouse company slug."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        resp = requests.get(url, headers={"User-Agent": "PersonalJobWatcher/1.0"}, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            jobs = data.get("jobs", [])
            return [parsed for j in jobs if (parsed := parse_greenhouse_job(j, slug))]
    except Exception as exc:
        LOGGER.debug("Greenhouse slug '%s' failed: %s: %s", slug, type(exc).__name__, exc)
    return []


def fetch_lever_slug(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs for a single Lever company slug."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = requests.get(url, headers={"User-Agent": "PersonalJobWatcher/1.0"}, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            jobs = resp.json()
            if isinstance(jobs, list):
                return [parsed for j in jobs if isinstance(j, dict) and (parsed := parse_lever_job(j, slug))]
    except Exception as exc:
        LOGGER.debug("Lever slug '%s' failed: %s: %s", slug, type(exc).__name__, exc)
    return []


def fetch_ats_jobs(
    ashby_slugs: tuple[str, ...] = DEFAULT_ASHBY_SLUGS,
    greenhouse_slugs: tuple[str, ...] = DEFAULT_GREENHOUSE_SLUGS,
    lever_slugs: tuple[str, ...] = DEFAULT_LEVER_SLUGS,
) -> list[dict[str, Any]]:
    """Fetch all unauthenticated ATS job boards across Ashby, Greenhouse, and Lever."""
    results = []
    for slug in ashby_slugs:
        results.extend(fetch_ashby_slug(slug))
    for slug in greenhouse_slugs:
        results.extend(fetch_greenhouse_slug(slug))
    for slug in lever_slugs:
        results.extend(fetch_lever_slug(slug))
    return results


def fetch_ats_api() -> list[Job]:
    """Scraper entrypoint returning a list of Job instances."""
    records = fetch_ats_jobs()
    jobs = []
    for rec in records:
        job = dict_to_job(rec)
        if job:
            jobs.append(job)
    return jobs
