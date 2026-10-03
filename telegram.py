"""Telegram Bot API delivery client with forum supergroup topic support and bounded retries."""

from datetime import datetime
import html
import os
import time
from typing import Any

import requests

import config  # Ensures .env is loaded if present
from models import Evaluation, Job


class DeliveryError(RuntimeError):
    pass


def format_message(item: Job | dict[str, Any], evaluation: Evaluation) -> str:
    """Format alert message based on whether item is a Job, Gig, or Hackathon."""
    # Check if item is a dictionary (Gig or Hackathon) or Job dataclass
    if isinstance(item, dict):
        title = item.get("title") or "Opportunity"
        org = item.get("organization") or item.get("company") or "Unknown Organizer"
        url = item.get("url") or ""
        source = str(item.get("source") or "web").title()
        location = item.get("location") or "Remote"
        prize_pool = item.get("prize_pool") or ""
        deadline = item.get("deadline")
        team_size = item.get("team_size") or {}

        # Differentiate Hackathons vs Gigs
        is_hackathon = "team_size" in item and team_size.get("max_team", 1) > 1

        if is_hackathon:
            emoji = "🚀"
            header = f"{emoji} 🟢 {evaluation.score} — {title}"
            lines = [header, f"🏢 {org}"]
            loc_prize = f"📍 {location}"
            if prize_pool:
                loc_prize += f" • 🏆 {prize_pool}"
            lines.append(loc_prize)

            min_t = team_size.get("min_team", 1)
            max_t = team_size.get("max_team", 4)
            lines.append(f"👥 Team Size: {min_t}–{max_t} members")

            if deadline:
                lines.append(f"📅 Deadline: {deadline}")
            lines.extend(("", f"🌐 {source}", url))
        else:
            emoji = "⚡"
            header = f"{emoji} 🟢 {evaluation.score} — {title}"
            lines = [header, f"🏢 {org}"]
            loc_prize = f"📍 {location}"
            if prize_pool:
                loc_prize += f" • 💰 {prize_pool}"
            lines.append(loc_prize)
            if deadline:
                lines.append(f"📅 Deadline: {deadline}")
            lines.extend(("", f"🌐 {source}", url))

        if evaluation.reasons:
            lines.extend(("", "✅ Matched: " + "; ".join(evaluation.reasons[:3])))
        return "\n".join(lines)[:4096]

    # Standard Job dataclass
    lines = [f"🟢 {evaluation.score} — {item.title}"]
    lines.append(item.company or "Company unknown")
    lines.append(item.location or "Location unknown")
    if item.compensation:
        lines.append(item.compensation)
    lines.extend(("", item.source.title(), item.url))
    if evaluation.reasons:
        lines.extend(("", "Matched: " + "; ".join(evaluation.reasons[:3])))
    return "\n".join(lines)[:4096]


def send_telegram(
    item: Job | dict[str, Any],
    evaluation: Evaluation,
    *,
    message_thread_id: int | str | None = None,
) -> None:
    """Send alert to Telegram chat or dedicated forum supergroup topic thread."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise DeliveryError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": format_message(item, evaluation),
        "disable_web_page_preview": True,
    }

    # Add message_thread_id if routing to a forum topic (Topic 1 in Telegram is the General topic, which requires omitting message_thread_id)
    if message_thread_id is not None:
        try:
            tid = int(message_thread_id)
            if tid > 1:
                payload["message_thread_id"] = tid
        except (ValueError, TypeError):
            pass

    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=(5, 15))
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise DeliveryError(f"Telegram connection failed ({type(exc).__name__})") from None

        if response.ok and isinstance(result, dict) and result.get("ok") is True:
            return

        if response.status_code == 429 and attempt < 2:
            retry_after = result.get("parameters", {}).get("retry_after", 1) if isinstance(result, dict) else 1
            try:
                delay = int(retry_after)
            except (ValueError, TypeError):
                delay = 1
            if delay > 30:
                raise DeliveryError(f"Telegram rate limited delivery for {delay} seconds")
            time.sleep(max(1, delay))
            continue

        if response.status_code >= 500 and attempt < 2:
            time.sleep(attempt + 1)
            continue

        raise DeliveryError(f"Telegram rejected delivery (HTTP {response.status_code})")

    raise DeliveryError("Telegram delivery exhausted retries")
