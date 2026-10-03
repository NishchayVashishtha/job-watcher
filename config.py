"""Configuration tuned for Nishchay Vashishtha's job and internship search."""

from dataclasses import dataclass
import os
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

from os import getenv


@dataclass(frozen=True)
class Profile:
    role_terms: tuple[str, ...] = (
        "backend", "software engineer", "software engineering",
        "software developer", "software development", "sde",
        "platform engineer", "infrastructure engineer", "full stack",
        "ai engineer", "machine learning", "ml engineer", "genai", "ai",
        "blockchain", "web3",
    )
    skills: tuple[str, ...] = (
        "python", "fastapi", "node.js", "docker", "postgresql", "flask",
        "langchain", "pytorch", "rag", "react", "solidity", "web3",
        "java", "typescript", "go", "pgvector", "linux",
    )
    job_types: tuple[str, ...] = ("internship", "fulltime")
    max_required_years: int = 2
    # Targeted geographic locations (India & Remote)
    allowed_locations: tuple[str, ...] = (
        "india", "remote", "delhi", "gurgaon", "gurugram", "noida",
        "bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
    )
    preferred_workplaces: tuple[str, ...] = ("remote", "hybrid", "onsite")
    accept_unpaid_internships: bool = False


PROFILE = Profile()
PROFILE_IS_EXAMPLE = False  # Real profile configured

# Targeted searches matching Nishchay's background
LINKEDIN_SEARCHES = (
    "backend intern",
    "software engineer intern",
    "ai engineer intern",
    "machine learning intern",
    "full stack intern",
    "junior software engineer",
    "junior backend developer",
)
LINKEDIN_LOCATION = "India"
INTERNSHALA_URLS = (
    "https://internshala.com/internships/software-development-internship/",
    "https://internshala.com/internships/backend-development-internship/",
    "https://internshala.com/internships/python-internship/",
    "https://internshala.com/internships/artificial-intelligence-ai-internship/",
    "https://internshala.com/internships/machine-learning-internship/",
    "https://internshala.com/internships/web-development-internship/",
)
WELLFOUND_URLS = (
    "https://wellfound.com/role/l/software-engineer/india",
    "https://wellfound.com/role/l/backend-engineer/india",
    "https://wellfound.com/role/l/artificial-intelligence-engineer/india",
)

ENABLED_SOURCES = tuple(
    name.strip() for name in (getenv("JOB_WATCHER_SOURCES") or "linkedin,internshala,wellfound").split(",")
    if name.strip()
)

ALERT_THRESHOLD = int(getenv("JOB_WATCHER_ALERT_THRESHOLD", "60"))
MAX_ALERTS_PER_RUN = int(getenv("JOB_WATCHER_MAX_ALERTS", "10"))
MAX_POSTING_AGE_DAYS = int(getenv("JOB_WATCHER_MAX_AGE_DAYS", "7"))
LINKEDIN_RESULTS_PER_SEARCH = 20
INTERNSHALA_MAX_CARDS_PER_URL = 50
WELLFOUND_MAX_CARDS_PER_URL = 50
HTTP_TIMEOUT = (5, 20)

