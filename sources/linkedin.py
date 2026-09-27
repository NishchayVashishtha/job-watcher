"""JobSpy adapter for public LinkedIn job listings."""

from datetime import datetime
import logging
import math
import re

from config import LINKEDIN_LOCATION, LINKEDIN_RESULTS_PER_SEARCH, LINKEDIN_SEARCHES
from models import Job, canonical_url, job_id, parse_posted_at

LOGGER = logging.getLogger(__name__)


def _value(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return None if text.casefold() in {"", "nan", "nat", "none", "<na>"} else text


def normalize_record(record: dict) -> Job | None:
    title = _value(record.get("title"))
    raw_url = _value(record.get("job_url"))
    if not title or not raw_url:
        return None
    try:
        url = canonical_url(raw_url)
    except ValueError:
        return None
    match = re.search(r"linkedin\.com/jobs/view/(\d+)", url)
    source_id = match.group(1) if match else None
    if not source_id:
        source_id = _value(record.get("id"))
    location = ", ".join(filter(None, (_value(record.get("city")), _value(record.get("state")), _value(record.get("country"))))) or _value(record.get("location"))
    remote_value = record.get("is_remote")
    remote = str(remote_value).casefold() in {"true", "1"}
    raw_type = (_value(record.get("job_type")) or "").casefold()
    employment = "internship" if "intern" in raw_type else "fulltime" if "full" in raw_type else None
    posted = record.get("date_posted")
    return Job(
        id=job_id("linkedin", url, source_id), source="linkedin", title=title,
        url=url, company=_value(record.get("company")), location=location,
        compensation=None, description=_value(record.get("description")),
        posted_at=parse_posted_at(posted), employment_type=employment,
        workplace_type="remote" if remote else None,
    )


def fetch_linkedin() -> list[Job]:
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError("Install requirements.txt to enable the LinkedIn collector") from exc
    jobs = []
    failures = []
    for term in LINKEDIN_SEARCHES:
        options = dict(
            site_name=["linkedin"], search_term=term,
            results_wanted=LINKEDIN_RESULTS_PER_SEARCH,
            hours_old=72, linkedin_fetch_description=False, verbose=0,
        )
        if LINKEDIN_LOCATION:
            options["location"] = LINKEDIN_LOCATION
        try:
            frame = scrape_jobs(**options)
            for record in frame.to_dict("records"):
                job = normalize_record(record)
                if job:
                    jobs.append(job)
        except Exception as exc:
            failures.append(f"{term}: {type(exc).__name__}: {exc}")
    if not jobs:
        raise RuntimeError("No LinkedIn listings; " + "; ".join(failures or ["searches returned no results"]))
    for failure in failures:
        LOGGER.warning("LinkedIn query failed: %s", failure)
    return jobs
