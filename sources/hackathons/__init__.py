"""Hackathon scrapers (Devfolio, Devpost, DoraHacks)."""

import logging
from typing import Any

from sources.hackathons.devfolio import fetch_devfolio
from sources.hackathons.devpost import fetch_devpost
from sources.hackathons.dorahacks import fetch_dorahacks

LOGGER = logging.getLogger(__name__)


def fetch_hackathons() -> list[dict[str, Any]]:
    """Aggregate hackathons from Devfolio, Devpost, and DoraHacks."""
    all_hackathons = []
    seen_ids = set()

    for name, fetcher in (
        ("devfolio", fetch_devfolio),
        ("devpost", fetch_devpost),
        ("dorahacks", fetch_dorahacks),
    ):
        try:
            items = fetcher()
            for item in items:
                item_id = item.get("id")
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_hackathons.append(item)
        except Exception as exc:
            LOGGER.error("Hackathon fetcher %s failed: %s", name, exc)

    LOGGER.info("Total collected hackathons: %d", len(all_hackathons))
    return all_hackathons


__all__ = ["fetch_hackathons", "fetch_devfolio", "fetch_devpost", "fetch_dorahacks"]
