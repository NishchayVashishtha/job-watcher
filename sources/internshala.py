"""Parse public Internshala search cards without visiting every detail page."""

from datetime import datetime, timezone
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import INTERNSHALA_MAX_CARDS_PER_URL, INTERNSHALA_URLS
from models import Job, canonical_url, job_id, parse_posted_at
from sources import get_public_page

LOGGER = logging.getLogger(__name__)


def _text(card, selector: str) -> str | None:
    element = card.select_one(selector)
    return element.get_text(" ", strip=True) if element else None


def parse_cards(html: str, page_url: str, *, now: datetime | None = None) -> list[Job]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".individual_internship")
    if not cards:
        if re.search(r"no\s+(?:matching\s+)?(?:internships|jobs)\s+found", soup.get_text(" ", strip=True), re.I):
            return []
        raise ValueError("Internshala page had no recognizable listing cards")
    jobs = []
    for card in cards[:INTERNSHALA_MAX_CARDS_PER_URL]:
        anchor = card.select_one("a.job-title-href")
        title = anchor.get_text(" ", strip=True) if anchor else None
        href = (anchor.get("href") if anchor else None) or card.get("data-href")
        if not title or not href:
            LOGGER.warning("Skipping Internshala card with missing title or URL")
            continue
        try:
            url = canonical_url(urljoin(page_url, href))
        except ValueError:
            LOGGER.warning("Skipping Internshala card with invalid URL")
            continue
        source_id = card.get("internshipid") or (card.get("id") or "").removeprefix("individual_internship_")
        location = _text(card, ".locations")
        workplace = None
        if location:
            if re.search(r"work from home|remote", location, re.I):
                workplace = "remote"
            elif re.search(r"hybrid", location, re.I):
                workplace = "hybrid"
            else:
                workplace = "onsite"
        employment = card.get("employment_type", "").casefold()
        if employment in {"job", "fulltime", "full_time"}:
            employment = "fulltime"
        elif employment != "internship":
            employment = None
        date_label = _text(card, ".color-labels [class*='status-'] span")
        skills = tuple(tag.get_text(" ", strip=True) for tag in card.select(".job_skills .job_skill"))
        jobs.append(Job(
            id=job_id("internshala", url, source_id), source="internshala",
            title=title, url=url, company=_text(card, ".company-name"),
            location=location, compensation=_text(card, ".stipend"),
            description=_text(card, ".about_job .text"),
            posted_at=parse_posted_at(date_label, now), employment_type=employment,
            workplace_type=workplace, skills=skills,
        ))
    if not jobs:
        raise ValueError("Internshala listing cards could not be normalized")
    return jobs


def fetch_internshala() -> list[Job]:
    jobs = []
    failures = []
    for url in INTERNSHALA_URLS:
        try:
            jobs.extend(parse_cards(get_public_page(url), url))
        except Exception as exc:
            failures.append(f"{url}: {type(exc).__name__}: {exc}")
    if not jobs and failures:
        raise RuntimeError("; ".join(failures))
    for failure in failures:
        LOGGER.warning("Internshala query failed: %s", failure)
    return jobs
