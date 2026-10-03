from datetime import datetime, timedelta, timezone

from config import Profile
from evaluate import evaluate
from models import Job

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def job(title: str, **changes) -> Job:
    fields = dict(id="linkedin:1", source="linkedin", title=title, url="https://example.com/1")
    fields.update(changes)
    return Job(**fields)


def test_sparse_backend_intern_exceeds_initial_threshold():
    assert evaluate(job("Backend Engineer Intern"), now=NOW).score == 70


def test_senior_mention_in_description_does_not_reject_intern():
    result = evaluate(job("Backend Engineer Intern", description="Work with senior engineers."), now=NOW)
    assert result.score == 70
    assert evaluate(job("Senior Backend Engineer"), now=NOW).score is None


def test_required_experience_rejected_but_preferred_is_not():
    assert evaluate(job("Backend Engineer", description="Minimum 5 years of experience required."), now=NOW).score is None
    assert evaluate(job("Backend Engineer", description="5 years of experience preferred."), now=NOW).score is not None


def test_go_does_not_match_prose_and_overlapping_career_terms_count_once():
    result = evaluate(job("Graduate Backend Engineer Intern", description="We go to market soon."), now=NOW)
    assert result.score == 70
    tagged = evaluate(job("Graduate Backend Engineer Intern", skills=("Go",)), now=NOW)
    assert tagged.score == 75


def test_missing_location_is_kept_but_known_mismatch_is_rejected():
    profile = Profile(allowed_locations=("Pune",))
    assert evaluate(job("Backend Intern"), profile, now=NOW).score is not None
    assert evaluate(job("Backend Intern", location="Mumbai"), profile, now=NOW).score is None


def test_old_posting_is_rejected():
    result = evaluate(job("Backend Intern", posted_at=NOW - timedelta(days=9)), now=NOW)
    assert result.score is None


def test_explicit_mandatory_years_in_title_is_rejected():
    assert evaluate(job("AI Engineer (3+ years mandatory)"), now=NOW).score is None


def test_remote_country_kept_when_only_city_preference_is_known():
    profile = Profile(allowed_locations=("Pune",))
    result = evaluate(job("Backend Intern", location="Remote only • India", workplace_type="remote"), profile, now=NOW)
    assert result.score is not None


def test_ai_engineer_with_rag_and_fastapi_qualifies():
    res = evaluate(
        job("AI Engineer Intern", description="Building RAG pipelines using FastAPI and LangChain", location="Gurugram, India"),
        now=NOW
    )
    assert res.score is not None
    assert res.score >= 80
    assert "preferred role" in res.reasons
    assert "early-career role" in res.reasons


def test_blockchain_web3_intern_qualifies():
    res = evaluate(
        job("Web3 Developer Intern", description="Smart contract development using Solidity and React", location="Remote"),
        now=NOW
    )
    assert res.score is not None
    assert res.score >= 75

