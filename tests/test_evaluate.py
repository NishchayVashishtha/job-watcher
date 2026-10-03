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


def test_stipend_parser():
    from evaluate import parse_stipend_amount
    assert parse_stipend_amount("25k/month") == 25000
    assert parse_stipend_amount("₹20,000") == 20000
    assert parse_stipend_amount("20000") == 20000
    assert parse_stipend_amount("₹ 25,000 - 30,000 / month") == 25000
    assert parse_stipend_amount("15k pm") == 15000
    assert parse_stipend_amount("Unpaid") == 0
    assert parse_stipend_amount("No stipend") == 0
    assert parse_stipend_amount("$500/month") == 500 * 83
    assert parse_stipend_amount("3.6 LPA") == 30000


def test_geo_fenced_stipend_relocation_rule():
    # Home region (Noida / Delhi / Gurgaon): any paid amount passes
    delhi_job = job("Backend Intern", location="Noida, India", workplace_type="onsite", compensation="₹10,000 / month")
    assert evaluate(delhi_job, now=NOW).score is not None

    # Home region unpaid rejected
    delhi_unpaid = job("Backend Intern", location="Gurugram, India", workplace_type="onsite", compensation="Unpaid")
    assert evaluate(delhi_unpaid, now=NOW).score is None

    # Outside home region (Bengaluru / Pune): < 20k or unspecified is rejected
    blr_low_pay = job("Backend Intern", location="Bengaluru, India", workplace_type="onsite", compensation="₹15,000 / month")
    assert evaluate(blr_low_pay, now=NOW).score is None

    blr_no_pay_info = job("Backend Intern", location="Bengaluru, India", workplace_type="onsite", compensation=None)
    assert evaluate(blr_no_pay_info, now=NOW).score is None

    # Outside home region: >= 20k passes
    blr_good_pay = job("Backend Intern", location="Bengaluru, India", workplace_type="onsite", compensation="₹25,000 / month")
    assert evaluate(blr_good_pay, now=NOW).score is not None
    assert evaluate(blr_good_pay, now=NOW).score >= 70


def test_remote_restricted_rejection():
    # Global remote accepted
    remote_global = job("AI Engineer", location="Remote", workplace_type="remote", description="Work from anywhere on GenAI")
    assert evaluate(remote_global, now=NOW).score is not None

    # US Only remote rejected
    remote_us_only = job("AI Engineer", location="Remote", workplace_type="remote", description="This role is open to US Only candidates")
    assert evaluate(remote_us_only, now=NOW).score is None

    # Timezone restricted to Americas rejected
    remote_tz = job("Backend Engineer", location="Remote", workplace_type="remote", description="Timezone restricted to Americas")
    assert evaluate(remote_tz, now=NOW).score is None


def test_international_onsite_rejected():
    sf_job = job("Software Engineer Intern", location="San Francisco, CA", workplace_type="onsite", compensation="$40/hr")
    assert evaluate(sf_job, now=NOW).score is None

    london_job = job("Backend Engineer", location="London, UK", workplace_type="onsite")
    assert evaluate(london_job, now=NOW).score is None


