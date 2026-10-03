"""Collect, score, alert, and record completed decisions for Jobs, Gigs, and Hackathons."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
from typing import Any, Callable

from config import (
    ALERT_THRESHOLD, ENABLED_SOURCES, GIG_ALERT_THRESHOLD, HACK_ALERT_THRESHOLD,
    MAX_ALERTS_PER_RUN, MAX_GIG_ALERTS_PER_RUN, MAX_HACK_ALERTS_PER_RUN,
    PROFILE_IS_EXAMPLE, TELEGRAM_TOPIC_GIGS, TELEGRAM_TOPIC_HACKS, TELEGRAM_TOPIC_JOBS,
)
from evaluate import evaluate as evaluate_job
from evaluators.evaluate_gigs import evaluate_gig
from evaluators.evaluate_hacks import evaluate_hackathon
from models import Evaluation, Job, merge_jobs
from sources.ats_api import fetch_ats_api
from sources.gigs import fetch_gigs
from sources.github_internships import fetch_github_internships
from sources.hackathons import fetch_hackathons
from sources.hackernews import fetch_hackernews
from sources.internshala import fetch_internshala
from sources.linkedin import fetch_linkedin
from sources.web3 import fetch_web3
from sources.wellfound import fetch_wellfound
from state import State, load_state, save_state
from telegram import send_telegram

LOGGER = logging.getLogger("job_watcher")

JOB_FETCHERS: dict[str, Callable[[], list[Job]]] = {
    "hackernews": fetch_hackernews,
    "web3": fetch_web3,
    "github_internships": fetch_github_internships,
    "ats_api": fetch_ats_api,
    "linkedin": fetch_linkedin,
    "internshala": fetch_internshala,
    "wellfound": fetch_wellfound,
}


@dataclass
class RunSummary:
    sources_ok: int = 0
    sources_failed: int = 0
    collected: int = 0
    new: int = 0
    rejected: int = 0
    below_threshold: int = 0
    selected: int = 0
    delivered: int = 0
    deferred: int = 0
    evaluation_failed: int = 0
    delivery_failed: int = 0
    details: list[str] = field(default_factory=list)


def _summary(summary: RunSummary, source_status: list[str], *, dry_run: bool, title: str = "Job watcher") -> None:
    mode = "dry run" if dry_run else "live"
    lines = [
        f"## {title} ({mode})",
        *[f"- {item}" for item in source_status],
        f"- Collected: {summary.collected}; new: {summary.new}",
        f"- Rejected: {summary.rejected}; below threshold: {summary.below_threshold}",
        f"- Selected: {summary.selected}; delivered: {summary.delivered}; deferred: {summary.deferred}",
        f"- Evaluation failures: {summary.evaluation_failed}; delivery failures: {summary.delivery_failed}",
    ]
    report = "\n".join(lines) + "\n"
    print(report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(report)


def run_pipeline(
    items: list[Any],
    evaluator_func: Callable[[Any], Evaluation],
    state: State,
    *,
    threshold: int,
    max_alerts: int,
    topic_id: str | int | None,
    dry_run: bool,
    sender: Callable[..., None],
    name: str = "Pipeline",
) -> tuple[int, RunSummary]:
    """Execute generic evaluate-rank-send pipeline for jobs, gigs, or hackathons."""
    summary = RunSummary(collected=len(items))
    selected: list[tuple[Any, Evaluation]] = []

    for item in items:
        item_id = item.id if hasattr(item, "id") else item.get("id")
        if not item_id or item_id in state.processed:
            continue

        summary.new += 1
        try:
            result = evaluator_func(item)
        except Exception:
            summary.evaluation_failed += 1
            LOGGER.exception("Evaluation failed for %s", item_id)
            continue

        if result.score is None:
            summary.rejected += 1
            LOGGER.info("Rejected %s: %s", item_id, "; ".join(result.reasons))
            if not dry_run:
                state.processed.add(item_id)
        elif result.score < threshold:
            summary.below_threshold += 1
            LOGGER.info("Below threshold %s (%d < %d): %s", item_id, result.score, threshold, "; ".join(result.reasons))
            if not dry_run:
                state.processed.add(item_id)
        else:
            selected.append((item, result))

    # Rank highest score first, then newest
    selected.sort(key=lambda pair: (
        pair[1].score or 0,
        (pair[0].posted_at if hasattr(pair[0], "posted_at") else None) or datetime.min.replace(tzinfo=timezone.utc),
    ), reverse=True)

    summary.selected = len(selected)
    summary.deferred = max(0, len(selected) - max_alerts)

    for item, result in selected[:max_alerts]:
        item_id = item.id if hasattr(item, "id") else item.get("id")
        item_title = item.title if hasattr(item, "title") else item.get("title", "")
        item_url = item.url if hasattr(item, "url") else item.get("url", "")
        item_org = (item.company if hasattr(item, "company") else None) or (item.get("organization") if isinstance(item, dict) else "")

        if dry_run:
            print(f"[{name} DRY RUN] Score: {result.score} | {item_title} | {item_org} | {item_url}")
            print("  " + "; ".join(result.reasons))
            continue

        try:
            sender(item, result, message_thread_id=topic_id)
        except TypeError:
            # Fallback if custom test sender doesn't accept message_thread_id
            try:
                sender(item, result)
            except Exception as exc:
                summary.delivery_failed += 1
                LOGGER.error("Delivery failed for %s: %s", item_id, exc)
                break
        except Exception as exc:
            summary.delivery_failed += 1
            LOGGER.error("Delivery failed for %s: %s", item_id, exc)
            break

        state.processed.add(item_id)
        summary.delivered += 1

    return (1 if summary.delivery_failed or summary.evaluation_failed else 0), summary


def run(
    state_path: Path,
    *,
    dry_run: bool = False,
    init_state: bool = False,
    fetchers: dict[str, Callable[[], list[Job]]] | None = None,
    sender: Callable[..., None] = send_telegram,
    include_gigs: bool | None = None,
    include_hackathons: bool | None = None,
) -> tuple[int, RunSummary]:
    """Execute all parallel pipelines (Jobs, Gigs, Hackathons) and update persistent state."""
    if PROFILE_IS_EXAMPLE and not dry_run:
        LOGGER.warning("Example profile is active; running without delivery or state changes")
        dry_run = True

    state: State = load_state(state_path, initialize=init_state or dry_run)
    is_custom_test_run = fetchers is not None
    job_fetchers = fetchers or {name: JOB_FETCHERS[name] for name in ENABLED_SOURCES if name in JOB_FETCHERS}

    overall_status = 0
    main_summary = RunSummary()
    source_status: list[str] = []

    # =========================================================================
    # 1. PIPELINE: Jobs & Internships
    # =========================================================================
    combined_jobs: dict[str, Job] = {}
    for name, fetcher in job_fetchers.items():
        try:
            jobs = fetcher()
            main_summary.sources_ok += 1
            source_status.append(f"{name}: {len(jobs)} listings")
            for job in jobs:
                if job.id in combined_jobs:
                    combined_jobs[job.id] = merge_jobs(combined_jobs[job.id], job)
                else:
                    combined_jobs[job.id] = job
        except Exception as exc:
            main_summary.sources_failed += 1
            source_status.append(f"{name}: failed ({type(exc).__name__})")
            LOGGER.error("Job source %s failed: %s: %s", name, type(exc).__name__, exc)

    main_summary.collected = len(combined_jobs)
    if not main_summary.sources_ok and not is_custom_test_run:
        _summary(main_summary, source_status, dry_run=dry_run, title="Jobs & Internships")
        return 1, main_summary

    job_status, job_summary = run_pipeline(
        list(combined_jobs.values()),
        evaluate_job,
        state,
        threshold=ALERT_THRESHOLD,
        max_alerts=MAX_ALERTS_PER_RUN,
        topic_id=TELEGRAM_TOPIC_JOBS,
        dry_run=dry_run,
        sender=sender,
        name="Jobs",
    )
    if job_status != 0:
        overall_status = 1

    # Merge stats into main summary
    main_summary.new += job_summary.new
    main_summary.rejected += job_summary.rejected
    main_summary.below_threshold += job_summary.below_threshold
    main_summary.selected += job_summary.selected
    main_summary.delivered += job_summary.delivered
    main_summary.deferred += job_summary.deferred
    main_summary.evaluation_failed += job_summary.evaluation_failed
    main_summary.delivery_failed += job_summary.delivery_failed

    _summary(job_summary, source_status, dry_run=dry_run, title="Jobs & Internships")

    # If this is a custom test run with injected fetchers, don't run external gigs/hackathons
    run_gigs_flag = include_gigs if include_gigs is not None else not is_custom_test_run
    run_hacks_flag = include_hackathons if include_hackathons is not None else not is_custom_test_run

    # =========================================================================
    # 2. PIPELINE: Freelance & Bounties (Gigs)
    # =========================================================================
    if run_gigs_flag:
        gig_source_status = []
        try:
            gigs = fetch_gigs()
            gig_source_status.append(f"gigs_collector: {len(gigs)} items")
            gig_status, gig_summary = run_pipeline(
                gigs,
                evaluate_gig,
                state,
                threshold=GIG_ALERT_THRESHOLD,
                max_alerts=MAX_GIG_ALERTS_PER_RUN,
                topic_id=TELEGRAM_TOPIC_GIGS,
                dry_run=dry_run,
                sender=sender,
                name="Gigs",
            )
            if gig_status != 0:
                overall_status = 1
            _summary(gig_summary, gig_source_status, dry_run=dry_run, title="Freelance & Bounties (Gigs)")
        except Exception as exc:
            LOGGER.error("Gigs pipeline failed: %s", exc)

    # =========================================================================
    # 3. PIPELINE: Hackathons (Prize money, PPO/PPI)
    # =========================================================================
    if run_hacks_flag:
        hack_source_status = []
        try:
            hacks = fetch_hackathons()
            hack_source_status.append(f"hackathons_collector: {len(hacks)} items")
            hack_status, hack_summary = run_pipeline(
                hacks,
                evaluate_hackathon,
                state,
                threshold=HACK_ALERT_THRESHOLD,
                max_alerts=MAX_HACK_ALERTS_PER_RUN,
                topic_id=TELEGRAM_TOPIC_HACKS,
                dry_run=dry_run,
                sender=sender,
                name="Hackathons",
            )
            if hack_status != 0:
                overall_status = 1
            _summary(hack_summary, hack_source_status, dry_run=dry_run, title="Hackathons")
        except Exception as exc:
            LOGGER.error("Hackathons pipeline failed: %s", exc)

    if not dry_run:
        save_state(state_path, state)

    return overall_status, main_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Job, Gig & Hackathon Intelligence Watcher")
    parser.add_argument("--dry-run", action="store_true", help="show decisions without sending or saving")
    parser.add_argument("--init-state", action="store_true", help="allow missing state on a new watcher only")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    state_path = Path(os.getenv("JOB_WATCHER_STATE_PATH", "seen.json"))
    try:
        status, _ = run(state_path, dry_run=args.dry_run, init_state=args.init_state)
        return status
    except (ValueError, FileNotFoundError, OSError) as exc:
        LOGGER.error("Watcher stopped before completion: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
