"""Optional parser for publicly accessible Wellfound listing pages."""

from datetime import datetime, timezone
import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import WELLFOUND_MAX_CARDS_PER_URL, WELLFOUND_URLS
from models import Job, canonical_url, job_id, parse_posted_at
from sources import get_public_page

LOGGER = logging.getLogger(__name__)
JOB_HREF = re.compile(r"^/jobs/(\d+)-")


def _structured_jobs(soup: BeautifulSoup, page_url: str) -> list[Job]:
    jobs = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            document = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        queue = document if isinstance(document, list) else [document]
        while queue:
            item = queue.pop()
            if not isinstance(item, dict):
                continue
            queue.extend(item.get("@graph", []))
            if item.get("@type") != "JobPosting":
                continue
            title = item.get("title")
            raw_url = item.get("url")
            if not isinstance(title, str) or not isinstance(raw_url, str):
                continue
            url = canonical_url(urljoin(page_url, raw_url))
            organization = item.get("hiringOrganization") or {}
            place = item.get("jobLocation") or {}
            if isinstance(place, list):
                place = place[0] if place else {}
            address = place.get("address", {}) if isinstance(place, dict) else {}
            location = ", ".join(filter(None, (address.get("addressLocality"), address.get("addressCountry")))) if isinstance(address, dict) else None
            jobs.append(Job(
                id=job_id("wellfound", url, _id_from_url(url)), source="wellfound",
                title=title.strip(), url=url,
                company=organization.get("name") if isinstance(organization, dict) else None,
                location=location or None, posted_at=parse_posted_at(item.get("datePosted")),
                employment_type=_employment(item.get("employmentType")),
            ))
    return jobs


def _id_from_url(url: str) -> str | None:
    match = re.search(r"/jobs/(\d+)-", url)
    return match.group(1) if match else None


def _employment(value: object) -> str | None:
    text = str(value or "").casefold()
    return "internship" if "intern" in text else "fulltime" if "full" in text else None


def parse_cards(html: str, page_url: str, *, now: datetime | None = None) -> list[Job]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    jobs = _structured_jobs(soup, page_url)
    if jobs:
        return jobs[:WELLFOUND_MAX_CARDS_PER_URL]
    # The public search page has, when accessible, job links grouped with a
    # company and short listing text. Keep this fallback conservative.
    for anchor in soup.select('a[href^="/jobs/"]'):
        href = anchor.get("href", "")
        match = JOB_HREF.match(href)
        title = anchor.get_text(" ", strip=True)
        if not match or not title or len(title) > 120:
            continue
        card = anchor
        for parent in anchor.parents:
            if parent.name not in {"div", "article", "li"}:
                continue
            card = parent
            if parent.select_one('a[href^="/company/"]'):
                break
            if len(parent.get_text(" ", strip=True)) > 600:
                card = anchor.parent
                break
        company_link = card.select_one('a[href^="/company/"]') if card else None
        card_text = card.get_text(" ", strip=True) if card else title
        experience = re.search(r"\b(\d+)\s+years?\s+of\s+exp\b", card_text, re.I)
        posted = re.search(r"\b(?:today|yesterday|\d+\s+(?:hours?|days?|weeks?|months?)\s+ago)\b", card_text, re.I)
        location = None
        workplace = None
        place = re.search(r"\b(Remote only|Onsite or remote|In office)\s*[•|]??\s*([^•\n]{2,70})", card_text, re.I)
        if place:
            location = place.group(0).strip()
            workplace = "remote" if "remote only" in location.casefold() else "hybrid" if "onsite or remote" in location.casefold() else "onsite"
        url = canonical_url(urljoin(page_url, href))
        jobs.append(Job(
            id=job_id("wellfound", url, match.group(1)), source="wellfound", title=title,
            url=url, company=company_link.get_text(" ", strip=True) if company_link else None,
            location=location, posted_at=parse_posted_at(posted.group(0), now) if posted else None,
            experience_min_years=int(experience.group(1)) if experience else None,
            employment_type=_employment(card_text[:200]), workplace_type=workplace,
        ))
        if len(jobs) >= WELLFOUND_MAX_CARDS_PER_URL:
            break
    if not jobs:
        raise ValueError("Wellfound page had no recognizable public listing cards")
    return jobs


def fetch_wellfound() -> list[Job]:
    jobs = []
    failures = []
    for url in WELLFOUND_URLS:
        try:
            jobs.extend(parse_cards(get_public_page(url), url))
        except Exception as exc:
            failures.append(f"{url}: {type(exc).__name__}: {exc}")
    if not jobs and failures:
        raise RuntimeError("; ".join(failures))
    for failure in failures:
        LOGGER.warning("Wellfound query failed: %s", failure)
    return jobs
