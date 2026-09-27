"""Shared bounded HTTP access for public listing pages."""

import time
import requests

from config import HTTP_TIMEOUT

USER_AGENT = "Mozilla/5.0 (compatible; PersonalJobWatcher/1.0; public listings only)"


def get_public_page(url: str) -> str:
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt or (status is not None and status < 500):
                raise
            time.sleep(1)
    raise AssertionError("unreachable")
