"""Tests for Gigs and Hackathons scrapers, evaluators, and Telegram topic routing."""

from datetime import datetime, timezone
import pytest

from evaluators.evaluate_gigs import evaluate_gig
from evaluators.evaluate_hacks import evaluate_hackathon
from models import Evaluation
from sources.gigs.superteam import parse_superteam_item
from sources.gigs.upwork_rss import parse_upwork_budget, parse_upwork_entry
from sources.gigs.wwr_rss import parse_wwr_entry
from sources.hackathons.devfolio import parse_devfolio_item
from sources.hackathons.devpost import parse_devpost_entry
from sources.hackathons.dorahacks import parse_dorahacks_item
from telegram import format_message, send_telegram

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# 1. Scraper Normalization Tests
# =============================================================================

def test_superteam_parser():
    raw = {
        "id": "st-101",
        "title": "Build Solana Agent for DeFi",
        "slug": "build-solana-agent-defi",
        "rewardAmount": 2500,
        "token": "USDC",
        "deadline": "2026-10-20T23:59:59.000Z",
        "type": "bounty",
        "isWinnersAnnounced": False,
        "sponsor": {"name": "Solana Foundation"},
    }
    parsed = parse_superteam_item(raw, now=NOW)
    assert parsed is not None
    assert parsed["id"] == "superteam:st-101"
    assert parsed["title"] == "Build Solana Agent for DeFi"
    assert parsed["organization"] == "Solana Foundation"
    assert parsed["has_cash_prize"] is True
    assert "$2,500 USDC" in parsed["prize_pool"]
    assert parsed["team_size"] == {"min_team": 1, "max_team": 1}
    assert parsed["is_remote"] is True


def test_upwork_parser_and_budget_extractor():
    pool, has_cash, rate = parse_upwork_budget("Hourly Range: $30.00 - $60.00 / hr")
    assert has_cash is True
    assert rate == 60.0

    pool_fixed, has_cash2, val2 = parse_upwork_budget("Budget: $1,200")
    assert has_cash2 is True
    assert val2 == 1200.0

    class DummyEntry:
        title = "Python and FastAPI Developer for RAG AI - Upwork"
        link = "https://www.upwork.com/jobs/~01abc"
        summary = "<p>Looking for a Python/FastAPI engineer to build RAG pipeline. Budget: $800. Long-term ongoing project.</p>"
        id = "upwork-test-1"

    parsed = parse_upwork_entry(DummyEntry(), now=NOW)
    assert parsed is not None
    assert parsed["title"] == "Python and FastAPI Developer for RAG AI"
    assert parsed["has_cash_prize"] is True
    assert parsed["career_incentives"] is True
    assert parsed["team_size"] == {"min_team": 1, "max_team": 1}


def test_wwr_parser_keeps_contracts_and_filters_fulltime():
    class ContractEntry:
        title = "Acme Corp: Remote Python Backend Contractor"
        link = "https://weworkremotely.com/jobs/1"
        type = "Contract"
        summary = "Contract role paying $50/hour for FastAPI and Docker development."
        id = "wwr-1"

    parsed_contract = parse_wwr_entry(ContractEntry(), now=NOW)
    assert parsed_contract is not None
    assert parsed_contract["organization"] == "Acme Corp"
    assert parsed_contract["title"] == "Remote Python Backend Contractor"
    assert parsed_contract["has_cash_prize"] is True

    class FulltimeEntry:
        title = "Beta Inc: Lead Architect"
        link = "https://weworkremotely.com/jobs/2"
        type = "Full-Time"
        summary = "Standard full-time employment."
        id = "wwr-2"

    assert parse_wwr_entry(FulltimeEntry(), now=NOW) is None


def test_devfolio_parser():
    raw = {
        "uuid": "df-hack-1",
        "slug": "eth-delhi-2026",
        "name": "ETH Delhi 2026",
        "tagline": "Build the future of Web3 and AI",
        "desc": "Prize pool of ₹5,00,000 for top builders with PPO fast-track.",
        "team_min": 1,
        "team_size": 4,
        "is_online": True,
        "status": "publish",
        "themes": [{"name": "AI"}, {"name": "Web3"}],
    }
    parsed = parse_devfolio_item(raw, now=NOW)
    assert parsed is not None
    assert parsed["id"] == "devfolio:df-hack-1"
    assert parsed["team_size"] == {"min_team": 1, "max_team": 4}
    assert parsed["has_cash_prize"] is True
    assert parsed["career_incentives"] is True
    assert parsed["is_remote"] is True


def test_devpost_parser():
    class DummyDevpost:
        title = "Global Generative AI Hackathon"
        link = "https://genai.devpost.com"
        summary = "Virtual event with $50,000 in prizes. Teams of up to 4. Hiring partner interviews available."
        id = "devpost-1"

    parsed = parse_devpost_entry(DummyDevpost(), now=NOW)
    assert parsed is not None
    assert parsed["has_cash_prize"] is True
    assert parsed["is_remote"] is True
    assert parsed["career_incentives"] is True
    assert parsed["team_size"]["max_team"] == 4


def test_dorahacks_parser():
    raw = {
        "id": "dora-99",
        "name": "Solana Frontier Hackathon",
        "slug": "solana-frontier",
        "prize": "$20,000 USDC",
        "prize_amount": 20000,
        "description": "Build high-speed DeFi and AI agents. Venture grant and recruitment tracks.",
        "min_team": 1,
        "max_team": 4,
        "status": "active",
    }
    parsed = parse_dorahacks_item(raw, now=NOW)
    assert parsed is not None
    assert parsed["has_cash_prize"] is True
    assert parsed["career_incentives"] is True


# =============================================================================
# 2. Gigs Evaluator Tests
# =============================================================================

def test_gig_evaluator_passes_qualifying_remote_gig():
    gig = {
        "id": "g1",
        "title": "Build LangChain RAG agent with FastAPI and Python",
        "description": "Remote contract paying $40/hr for AI and FastAPI microservice development.",
        "is_remote": True,
        "location": "Remote",
        "hourly_rate": 40.0,
        "prize_pool": "$40/hr",
        "has_cash_prize": True,
    }
    result = evaluate_gig(gig)
    assert result.score is not None
    assert result.score >= 80  # Tech match (up to 50) + High rate (35) = 85
    assert any("high hourly rate" in r for r in result.reasons)


def test_gig_evaluator_rejects_onsite_and_us_only():
    onsite_gig = {
        "id": "g2",
        "title": "Python Developer",
        "description": "Onsite presence required in London office.",
        "is_remote": False,
        "location": "London, UK",
        "hourly_rate": 50.0,
    }
    assert evaluate_gig(onsite_gig).score is None

    us_only_gig = {
        "id": "g3",
        "title": "FastAPI & RAG Developer",
        "description": "Must be US citizens only or US freelancers only.",
        "is_remote": True,
        "location": "Remote",
        "hourly_rate": 60.0,
    }
    assert evaluate_gig(us_only_gig).score is None


# =============================================================================
# 3. Hackathons Evaluator Tests
# =============================================================================

def test_hackathon_hard_exclusions():
    # 1. Certificate-only / free-swag with no cash or career incentive
    cert_only = {
        "id": "h1",
        "title": "College Code Fest",
        "description": "Participate for certificates and free swag! No cash prizes.",
        "has_cash_prize": False,
        "career_incentives": False,
        "team_size": {"min_team": 1, "max_team": 4},
        "is_remote": True,
    }
    res = evaluate_hackathon(cert_only)
    assert res.score is None
    assert "certificate-only" in res.reasons[0] or "no tangible cash prize" in res.reasons[0]

    # 2. Strictly 3-member team restriction (min_team == 3 and max_team == 3)
    strictly_3 = {
        "id": "h2",
        "title": "Trio Hackathon",
        "description": "$10,000 cash prizes for Web3 builders.",
        "has_cash_prize": True,
        "career_incentives": False,
        "prize_pool": "$10,000",
        "team_size": {"min_team": 3, "max_team": 3},
        "is_remote": True,
    }
    res3 = evaluate_hackathon(strictly_3)
    assert res3.score is None
    assert "strictly 3-member" in res3.reasons[0]

    # 3. In-person outside Delhi-NCR
    bangalore_offline = {
        "id": "h3",
        "title": "Bangalore In-Person Hack",
        "description": "$5,000 prizes",
        "has_cash_prize": True,
        "career_incentives": False,
        "team_size": {"min_team": 1, "max_team": 4},
        "is_remote": False,
        "location": "Bengaluru, Karnataka",
    }
    assert evaluate_hackathon(bangalore_offline).score is None

    # Delhi-NCR offline accepted
    ncr_offline = {
        "id": "h4",
        "title": "Gurugram Tech Hack",
        "description": "₹2,00,000 cash prize with PPO interviews for top performers.",
        "has_cash_prize": True,
        "career_incentives": True,
        "prize_pool": "₹2,00,000",
        "team_size": {"min_team": 1, "max_team": 4},
        "is_remote": False,
        "location": "Gurugram, Haryana, Delhi NCR",
    }
    ncr_res = evaluate_hackathon(ncr_offline)
    assert ncr_res.score is not None
    assert ncr_res.score >= 80

    # 4. Working professionals only rejected
    pro_only = {
        "id": "h5",
        "title": "Corporate AI Challenge",
        "description": "$20,000 prizes. Restricted to working professionals only.",
        "has_cash_prize": True,
        "career_incentives": False,
        "team_size": {"min_team": 1, "max_team": 4},
        "is_remote": True,
    }
    assert evaluate_hackathon(pro_only).score is None


def test_hackathon_scoring_and_team_priority():
    # Qualifies with: Career Incentive (+35), Cash Prize > $1k (+25), Domain AI (+20), 4 members allowed (+25)
    hack = {
        "id": "h-top",
        "title": "GenAI Summit Hackathon",
        "description": "Build RAG applications. $25,000 in prizes. Winners receive PPO and interview fast-track.",
        "has_cash_prize": True,
        "career_incentives": True,
        "prize_pool": "$25,000",
        "team_size": {"min_team": 1, "max_team": 4},
        "is_remote": True,
        "location": "Online",
        "tags": ["AI", "GenAI"],
    }
    res = evaluate_hackathon(hack)
    assert res.score is not None
    assert res.score >= 80
    assert any("career incentives" in r for r in res.reasons)
    assert any("verified cash prize pool" in r for r in res.reasons)
    assert any("allows 4+ members" in r for r in res.reasons)


# =============================================================================
# 4. Telegram Topic Thread Tests
# =============================================================================

def test_telegram_topic_thread_routing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    captured_payloads = []

    def mock_post(url, *, json, timeout):
        captured_payloads.append(json)
        class MockResp:
            status_code = 200
            ok = True
            def json(self):
                return {"ok": True}
        return MockResp()

    monkeypatch.setattr("telegram.requests.post", mock_post)

    gig_item = {
        "id": "g-topic-1",
        "title": "Build Solana DeFi App",
        "organization": "Superteam",
        "url": "https://earn.superteam.fun/1",
        "prize_pool": "$3,000 USDC",
        "location": "Remote",
        "source": "superteam",
    }
    send_telegram(gig_item, Evaluation(85, ("high budget",)), message_thread_id=777)

    assert len(captured_payloads) == 1
    assert captured_payloads[0]["chat_id"] == "12345"
    assert captured_payloads[0]["message_thread_id"] == 777
    assert "⚡" in captured_payloads[0]["text"]
    assert "Build Solana DeFi App" in captured_payloads[0]["text"]
