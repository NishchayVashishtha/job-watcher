from datetime import datetime, timezone
from pathlib import Path

from models import merge_jobs
from sources.internshala import parse_cards as parse_internshala
from sources.linkedin import normalize_record
from sources.wellfound import parse_cards as parse_wellfound

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def test_internshala_card_from_observed_markup():
    html = (Path(__file__).parent / "fixtures/internshala_card.html").read_text()
    job, = parse_internshala(html, "https://internshala.com/internships/software-development-internship/", now=NOW)
    assert job.id == "internshala:3290001"
    assert job.url == "https://internshala.com/internship/detail/backend-engineer-example"
    assert job.title == "Backend Engineer"
    assert job.location == "Work from home"
    assert job.workplace_type == "remote"
    assert job.posted_at == datetime(2026, 9, 26, tzinfo=timezone.utc)
    assert job.skills == ("Python", "Go")


def test_linkedin_normalizes_stable_id_and_missing_fields():
    job = normalize_record({
        "title": "Software Engineer Intern", "company": "Example",
        "job_url": "https://www.linkedin.com/jobs/view/4123456789/?trk=abc",
        "date_posted": "2026-09-28", "is_remote": True,
    })
    assert job and job.id == "linkedin:4123456789"
    assert job.url == "https://www.linkedin.com/jobs/view/4123456789"
    assert job.workplace_type == "remote"
    assert job.posted_at == NOW


def test_overlap_keeps_richer_listing():
    first = normalize_record({"title": "Backend Intern", "job_url": "https://www.linkedin.com/jobs/view/42"})
    second = normalize_record({"title": "Backend Intern", "job_url": "https://www.linkedin.com/jobs/view/42", "company": "Example", "description": "Python APIs"})
    combined = merge_jobs(first, second)
    assert combined.company == "Example"
    assert combined.description == "Python APIs"


def test_wellfound_structured_public_listing():
    html = '''<script type="application/ld+json">{
      "@type":"JobPosting", "title":"Junior Software Engineer",
      "url":"https://wellfound.com/jobs/4760728-junior-software-engineer",
      "datePosted":"2026-09-27", "employmentType":"FULL_TIME",
      "hiringOrganization":{"name":"Example"},
      "jobLocation":{"address":{"addressLocality":"Pune","addressCountry":"India"}}
    }</script>'''
    job, = parse_wellfound(html, "https://wellfound.com/role/l/software-engineer/india", now=NOW)
    assert job.id == "wellfound:4760728"
    assert job.company == "Example"
    assert job.employment_type == "fulltime"
    assert job.location == "Pune, India"


def test_hackernews_comment_parsing():
    from sources.hackernews import parse_hn_comment, dict_to_job
    hit = {
        "objectID": "39991234",
        "author": "techfounder",
        "created_at": "2026-09-28T10:00:00Z",
        "comment_text": "<p>Acme Corp | Backend Engineer Intern | Remote (Global) | Full-time | $30/hr</p><p>We build GenAI RAG pipelines with Python and FastAPI. Apply: https://acme.com/jobs/123</p>",
    }
    parsed = parse_hn_comment(hit, now=NOW)
    assert parsed is not None
    assert parsed["company"] == "Acme Corp"
    assert "Backend Engineer Intern" in parsed["title"]
    assert parsed["workplace_type"] == "remote"
    assert parsed["url"] == "https://acme.com/jobs/123"

    job = dict_to_job(parsed, now=NOW)
    assert job is not None
    assert job.id == "hackernews:39991234"
    assert job.employment_type == "internship"


def test_web3_feed_parsing():
    from sources.web3 import parse_feed_entry, dict_to_job
    entry = {
        "title": "Solana Labs is hiring a Blockchain Engineer Intern",
        "link": "https://cryptojobslist.com/jobs/solana-intern",
        "summary": "<p>Build Solana smart contracts with Rust and Web3. ₹30,000/month stipend. Remote.</p>",
        "published": "2026-09-28T08:00:00Z",
    }
    parsed = parse_feed_entry(entry, "https://cryptojobslist.com/rss", now=NOW)
    assert parsed is not None
    assert parsed["company"] == "Solana Labs"
    assert "Blockchain Engineer Intern" in parsed["title"]
    assert parsed["workplace_type"] == "remote"

    job = dict_to_job(parsed, now=NOW)
    assert job is not None
    assert job.employment_type == "internship"
    assert job.source == "web3"


def test_github_internships_markdown_table_parsing():
    from sources.github_internships import parse_markdown_table, dict_to_job
    md = """
| Company | Role | Location | Application/Apply Link | Date Posted |
| :--- | :--- | :--- | :--- | :--- |
| **[Polygon](https://polygon.technology)** | Backend Intern | Bengaluru, India | [Apply](https://polygon.technology/careers/123) | Sep 28 |
| **[Anthropic](https://anthropic.com)** | AI Research Intern | Remote | [Apply](https://jobs.ashbyhq.com/anthropic/456) | Sep 27 |
"""
    records = parse_markdown_table(md, now=NOW)
    assert len(records) == 2
    assert records[0]["company"] == "Polygon"
    assert records[0]["title"] == "Backend Intern"
    assert records[0]["location"] == "Bengaluru, India"
    assert records[0]["url"] == "https://polygon.technology/careers/123"

    job = dict_to_job(records[0], now=NOW)
    assert job is not None
    assert job.employment_type == "internship"
    assert job.company == "Polygon"


def test_ats_api_parsers():
    from sources.ats_api import parse_ashby_job, parse_greenhouse_job, parse_lever_job, dict_to_job

    # Ashby
    ashby_raw = {
        "id": "ashby-101",
        "title": "Software Engineering Intern - Backend",
        "jobUrl": "https://jobs.ashbyhq.com/openai/ashby-101",
        "location": "Remote",
        "isRemote": True,
        "descriptionHtml": "<p>Python, FastAPI, RAG. Stipend: $50/hr</p>",
        "publishedAt": "2026-09-28T00:00:00Z",
    }
    ashby_parsed = parse_ashby_job(ashby_raw, "openai", now=NOW)
    assert ashby_parsed is not None
    assert ashby_parsed["workplace_type"] == "remote"
    assert ashby_parsed["company"] == "Openai"

    # Greenhouse
    gh_raw = {
        "id": 998877,
        "title": "AI Engineer Intern",
        "absolute_url": "https://boards.greenhouse.io/scaleai/jobs/998877",
        "location": {"name": "Bengaluru, India"},
        "content": "Stipend ₹50,000 / month. GenAI and LangChain.",
        "updated_at": "2026-09-28T00:00:00Z",
    }
    gh_parsed = parse_greenhouse_job(gh_raw, "scaleai", now=NOW)
    assert gh_parsed is not None
    assert gh_parsed["location"] == "Bengaluru, India"

    # Lever
    lever_raw = {
        "id": "lever-555",
        "text": "Full Stack Intern",
        "hostedUrl": "https://jobs.lever.co/ripple/lever-555",
        "categories": {"location": "Noida, India", "commitment": "Intern"},
        "workplaceType": "onsite",
        "descriptionPlain": "Web3 React and Node.js development.",
        "createdAt": 1790582400000,
    }
    lever_parsed = parse_lever_job(lever_raw, "ripple", now=NOW)
    assert lever_parsed is not None
    assert lever_parsed["location"] == "Noida, India"

    job = dict_to_job(ashby_parsed, now=NOW)
    assert job is not None
    assert job.source == "ats_api"
    assert job.employment_type == "internship"

