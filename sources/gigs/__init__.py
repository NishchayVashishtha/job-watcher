"""Gigs, freelance bounties, and contract scrapers."""

import logging
from typing import Any

from sources.gigs.superteam import fetch_superteam
from sources.gigs.upwork_rss import fetch_upwork_rss
from sources.gigs.wwr_rss import fetch_wwr_rss

LOGGER = logging.getLogger(__name__)


def fetch_gigs() -> list[dict[str, Any]]:
    """Aggregate gigs, bounties, and freelance opportunities from all gig sources."""
    all_gigs = []
    seen_ids = set()

    for name, fetcher in (
        ("superteam", fetch_superteam),
        ("upwork", fetch_upwork_rss),
        ("wwr", fetch_wwr_rss),
    ):
        try:
            items = fetcher()
            for item in items:
                item_id = item.get("id")
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_gigs.append(item)
        except Exception as exc:
            LOGGER.error("Gig fetcher %s failed: %s", name, exc)

    LOGGER.info("Total collected gigs: %d", len(all_gigs))
    return all_gigs


__all__ = ["fetch_gigs", "fetch_superteam", "fetch_upwork_rss", "fetch_wwr_rss"]
