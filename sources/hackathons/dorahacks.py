"""Scraper for Web3 & AI hackathons and grants via DoraHacks JSON API."""

from datetime import datetime, timezone
import logging
import re
from typing import Any
import requests

from config import HTTP_TIMEOUT

LOGGER = logging.getLogger(__name__)

DEFAULT_DORAHACKS_API_URL = "https://dorahacks.io/api/hackathon/explore"


def parse_dorahacks_item(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Normalize a DoraHacks hackathon/grant record."""
    now = now or datetime.now(timezone.utc)
    item_id = str(item.get("id") or item.get("uuid") or item.get("slug") or "").strip()
    title = str(item.get("name") or item.get("title") or "").strip()
    slug = str(item.get("slug") or item_id).strip()

    if not item_id or not title:
        return None

    # Check status if present
    status = str(item.get("status") or "").lower()
    if status in {"closed", "finished", "completed", "draft"}:
        return None

    # Check deadline
    deadline = item.get("end_time") or item.get("deadline") or item.get("ends_at")
    if deadline:
        try:
            deadline_str = str(deadline).replace("Z", "+00:00")
            deadline_dt = datetime.fromisoformat(deadline_str)
            if deadline_dt < now:
                return None
        except (ValueError, TypeError):
            pass

    organizer = item.get("organizer") or item.get("brand") or {}
    organization = organizer.get("name") if isinstance(organizer, dict) else "DoraHacks"

    url = f"https://dorahacks.io/hackathon/{slug}"

    prize = str(item.get("prize") or item.get("reward") or item.get("grant_amount") or "").strip()
    prize_amount = item.get("prize_amount") or item.get("total_prize") or 0
    token = str(item.get("token") or "USD").strip()

    if prize_amount:
        prize_pool = f"${prize_amount:,} {token}"
        has_cash_prize = True
    elif prize:
        prize_pool = prize
        has_cash_prize = bool(re.search(r"[\$\d]|inr|usdt|usdc|eth|sol", prize.lower()))
    else:
        prize_pool = "Grants & Bounties"
        has_cash_prize = True

    desc = str(item.get("description") or item.get("brief") or "").strip()
    full_text = f"{title} {prize} {desc}".lower()

    # Team size parsing
    min_team = int(item.get("min_team") or 1)
    max_team = int(item.get("max_team") or 5)

    # Career Incentives
    career_incentives = bool(re.search(
        r"\b(?:ppo|ppi|job|hiring|grant|venture|accelerator|recruitment|fast-?track)\b",
        full_text,
        re.I
    ))

    # Tags
    tags = ["Web3", "Blockchain"]
    ecosystem = item.get("ecosystem") or item.get("track")
    if ecosystem and isinstance(ecosystem, str):
        tags.append(ecosystem)
    for kw in ("AI", "Solana", "Ethereum", "ZK", "DeFi", "DePIN", "Rust"):
        if re.search(rf"\b{kw}\b", full_text, re.I) and kw not in tags:
            tags.append(kw)

    return {
        "id": f"dorahacks:{item_id}",
        "title": title,
        "organization": organization,
        "url": url,
        "tags": tags[:6],
        "deadline": deadline,
        "prize_pool": prize_pool,
        "has_cash_prize": has_cash_prize,
        "career_incentives": career_incentives,
        "team_size": {"min_team": min_team, "max_team": max_team},
        "description": desc or f"{title} on DoraHacks. Prize pool: {prize_pool}",
        "location": "Online",
        "is_remote": True,
        "source": "dorahacks",
    }


def fetch_dorahacks(api_url: str = DEFAULT_DORAHACKS_API_URL) -> list[dict[str, Any]]:
    """Fetch active Web3/AI hackathons from DoraHacks JSON endpoint."""
    try:
        response = requests.get(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            LOGGER.warning("DoraHacks API returned status %s; skipping safely", response.status_code)
            return []
        data = response.json()
    except Exception as exc:
        LOGGER.warning("Failed to fetch DoraHacks API (%s): %s", api_url, exc)
        return []

    items = data if isinstance(data, list) else data.get("hackathons") or data.get("items") or data.get("result") or []
    results = []
    for raw in items:
        if isinstance(raw, dict):
            normalized = parse_dorahacks_item(raw)
            if normalized:
                results.append(normalized)

    LOGGER.info("Fetched %d hackathons from DoraHacks", len(results))
    return results
