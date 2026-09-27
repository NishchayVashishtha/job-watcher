# Personal Job Watcher — Implementation Plan

## Purpose and boundaries

Build a small personal Python script that collects public job listings, checks them against one person's preferences, scores suitable matches, and sends useful opportunities to Telegram. Applications remain manual.

The initial sources are LinkedIn, Internshala, and Wellfound. Scheduled collection runs on GitHub-hosted Actions runners, without personal platform accounts, cookies, or sessions. Wellfound is optional if its public pages are difficult to collect reliably.

Keep the project easy to understand and maintain. The useful outcome is a manageable stream of jobs worth opening, ranked for the user's profile. Comprehensive coverage of every vacancy is not a requirement.

## 1. Personal profile and configuration

Keep the profile and operational settings in `config.py`; no profile database or configuration UI.

The user should be able to change:

- Preferred role families and search keywords.
- Career stage, actual experience, and maximum required experience they want to consider.
- Current skills and technologies they want to work with.
- Eligible countries, acceptable cities, relocation preferences, and remote/hybrid/onsite preferences.
- Internship versus full-time preferences.
- Any firm requirements, such as paid internships or internship duration, if relevant.
- Enabled sources, search limits, and alert threshold.

Separate firm requirements from preferences: an explicitly incompatible location can exclude a job; a preferred technology increases its score. Missing information remains unknown.

The earlier plan suggests backend/software roles, internships and early-career jobs, and technologies such as Python, Go, Node.js, FastAPI, PostgreSQL, Docker, and Linux. Treat these as a draft preference list, not verified skills or a complete personal profile. Confirm the actual profile before tuning live alerts. Do not assume India-only eligibility or remote-only work from example messages.

For v1, encode the profile manually. Resume parsing and automatic skill inference are unnecessary.

## 2. Pipeline

```text
Load configuration and validated state
    → Collect a bounded set of public listings
    → Normalize and combine duplicates within each source
    → Skip previously processed IDs
    → Apply explicit eligibility filters
    → Score against the personal profile
    → Sort qualifying jobs by score
    → Send individual Telegram alerts
    → Persist completed work
```

Start with one execution approximately every four hours. Keep collection sequential and bounded; concurrency inside the application is unnecessary initially.

## 3. Files

```text
job-watcher/
├── main.py
├── config.py
├── models.py
├── evaluate.py
├── state.py
├── telegram.py
├── sources/
│   ├── linkedin.py
│   ├── internshala.py
│   └── wellfound.py
├── tests/
│   └── fixtures/
├── requirements.txt
├── README.md
├── .gitignore
└── .github/workflows/collect.yml
```

Add files only when implementation needs them. Keep evaluation in one module and source-specific parsing in the corresponding adapter.

## 4. Normalized jobs

Every collector returns `list[Job]`.

Required fields: `id`, `source`, `title`, and `url`.

Optional fields: `company`, `location`, `compensation`, `description`, and `posted_at`.

Also preserve `employment_type`, `workplace_type`, and `experience_min_years` when the source explicitly provides them. These directly support personal filtering. Add internship duration only if it becomes a configured requirement.

Normalize posting dates where possible; unknown or unparseable dates remain unknown. Do not invent a posting date from the collection time. Keep compensation as display text until a real requirement calls for numeric comparison.

Use source-provided IDs with a source prefix. Otherwise, use a deterministic hash of the source and a canonical listing URL. Remove known tracking parameters without removing parameters that identify the job. Skip and report entries without a usable title or stable identity.

Merge duplicate IDs from overlapping queries before evaluation, retaining the richer available fields. Do not add fuzzy cross-source deduplication.

## 5. Collection

### LinkedIn

Try JobSpy's public LinkedIn collector, with explicit location and bounded search results. Pin the dependency version that has been verified.

Start with searches matching the configured profile, for example backend intern, software engineer intern, junior software engineer, associate software engineer, and graduate software engineer. Avoid expanding to every role or technology combination.

Initially collect listing metadata. Fetch descriptions selectively only if actual results show that missing details prevent useful evaluation.

### Internshala

Try ordinary HTTP requests and HTML parsing on configured public category/search pages. Extract listing-card information first, including snippets or skills if supplied there.

Include internship or fresher-job pages according to the profile. Avoid assuming every software listing is an internship or every Python listing is a desired engineering role.

### Wellfound

Attempt ordinary HTTP collection of public listing pages with a small request budget. Keep it only if it works cleanly from the remote runner. Disable it if collection requires authenticated sessions or substantial browser tooling.

### Shared collection rules

- Use explicit request timeouts and a small retry limit for transient failures.
- Stop a source for that run if access is blocked; report it and continue.
- Set per-source limits on queries, pages, and results.
- Where supported, start with an overlapping search window of about 72 hours, rather than only the four hours since the expected previous run.
- Use a configurable posting-age cutoff, provisionally seven days, to reduce stale alerts. Unknown dates remain eligible and are shown as unknown.
- Distinguish an explicit empty-results page from an unexpected page that failed to parse.
- Preserve valid results when one query or listing fails where practical.

The lookback and result limits provide useful coverage, not a guarantee that no jobs are missed. Adjust them based on observed volume.

## 6. Filtering and personal scoring

Expose one function in `evaluate.py`, returning an `Evaluation` with an optional numeric score and short reasons. A missing score means rejection. Keep this small result type in `models.py`.

### Hard filters

Reject only explicit conflicts with the configured profile, such as a senior role title, a clearly excessive minimum experience requirement, or a clearly incompatible work location.

Apply seniority rules to titles and experience rules to actual requirement statements. “Work with senior engineers” must not reject an internship. Distinguish mandatory experience from preferred experience where the wording is clear; keep ambiguous cases.

Use token-aware matching and common aliases. A substring such as `Go` inside another word is not evidence of the Go language. Treat remote location restrictions separately from the preference for remote work.

### Initial scoring proposal

| Category | Maximum | Interpretation |
| --- | ---: | --- |
| Role match | 45 | Strong fit with the user's preferred role families |
| Career-stage match | 25 | Explicitly suitable internship, graduate, junior, or experience level |
| Technology match | 20 | Matches to configured skills and desired technologies |
| Work arrangement/location preference | 5 | Explicit match with a preference |
| Freshness | 5 | Recent known posting date, initially within three days |

Use the strongest applicable match within overlapping role/career categories, and count each technology once up to the cap. Unknown fields earn no bonus but do not cause rejection.

Start by testing a threshold of 60. A strongly matching backend internship can score 70 from role and career stage alone, so sparse listings can qualify. A role with unknown career level can still qualify through other strong matches.

These are initial weights, not a probability of suitability. Calibrate them against roughly 20–30 real listings that the user would or would not open. Review both selected and rejected examples. Keep a few representative examples as regression tests.

Prefer one threshold initially. Add source-specific behavior only if observed data quality makes it necessary.

## 7. State and delivery behavior

Use a JSON file on a dedicated `state` branch. A version number and a set/list of processed IDs are sufficient initially. In code, use a set for membership checks and write sorted IDs for stable diffs.

“Processed” means the listing received a completed decision:

| Outcome | Record as processed? |
| --- | --- |
| Rejected by an explicit filter | Yes |
| Scored below the threshold | Yes |
| Telegram confirms delivery | Yes |
| Telegram fails or the outcome is uncertain | No |
| Evaluation fails unexpectedly | No |
| Qualified but deferred by the alert limit | No |

An explicitly initialized first run may start empty. Failure to retrieve existing state, invalid JSON, or an unsupported state version must stop processing before alerts are sent.

Write local state atomically. Preserve completed decisions when later work fails, and attempt to push valid updated state even if the processing step reports a failure. Only commit when state changes. A failed push makes the workflow fail visibly.

Accept these small-project limits:

- A crash between Telegram delivery and remote state persistence can cause duplicate alerts.
- A failed or deferred alert is retried on a later run only if the source returns that listing again. Persistent storage of unsent jobs can be added if actual losses justify it.
- Previously processed jobs are not automatically reconsidered when their content or scoring rules change. Use saved samples to tune the evaluator; do not routinely clear live state.

These limitations avoid introducing a database or durable delivery system in v1.

## 8. Telegram and first-run behavior

Store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as GitHub Actions secrets. Keep credentials out of code and redact tokens from error output.

Send one message per selected job containing score, title, company, location, compensation if known, source, link, and up to three matching reasons. Use plain text initially to avoid formatting-escape failures.

Validate Telegram's success response. Pace messages, respect rate-limit retry instructions, and use bounded retries. Keep text within the API's message limit.

Start with a configurable maximum of 10 alerts per run, sorted by score with known recency as a tie-breaker. Record deferred counts and leave deferred jobs unprocessed. Adjust this limit to the user's preferred volume after observing results.

Before enabling delivery, run a dry run that prints proposed alerts and rejection reasons without sending messages or changing state. On the first live run, send qualifying recent jobs within the same alert limit; a separate silent baseline mode is unnecessary initially.

If Telegram has a persistent delivery failure, stop further send attempts for that run, preserve completed work, and report the failure.

## 9. GitHub Actions

Use a GitHub-hosted Linux runner, a pinned supported Python version, and dependency caching. Keep scheduling on the default branch and state on the separate branch.

```yaml
on:
  workflow_dispatch:
  schedule:
    - cron: "17 */4 * * *"

concurrency:
  group: job-watcher
  cancel-in-progress: false
```

The workflow checks out code, restores state into a separate directory, runs the script, and persists valid updated state. Grant the workflow the repository contents permission needed to update the state branch. Configure a total execution timeout.

Scheduling is approximate; overlapping searches accommodate ordinary delays. Scheduled runs must not depend on the user's PC. Local live collection is optional development activity and would use the local network; fixture-based tests can run without accessing job portals.

Each run writes a concise Actions summary: source successes/failures, collected jobs, new jobs, rejection/selection counts, delivered/deferred alerts, and persistence status. Continue with healthy sources after a partial source failure. If every enabled source fails, or state/delivery fails, report an unsuccessful run. Legitimately empty results can still be successful.

No routine Telegram health messages are needed. Use Actions logs and failure notifications for operational problems.

## 10. Implementation order

1. **Confirm the draft personal profile.** Fill in preferences and firm constraints in `config.py`.
2. **Check remote feasibility.** Add a manually triggered Actions workflow and bounded probes for the three sources. Report sample fields and failures before investing in complete adapters. Do not enable the recurring schedule yet.
3. **Normalize viable sources.** Implement stable IDs and save a few representative response fixtures for parser tests.
4. **Implement and calibrate evaluation.** Run against collected examples; inspect good matches, sparse listings, and obvious mismatches.
5. **Implement JSON state and Telegram.** Check consecutive runs, delivery failures, state failures, and dry-run behavior.
6. **Complete one source end to end remotely.** Verify delivery and deduplication across two manual Actions executions, then enable the other viable adapters.
7. **Enable scheduling and observe for several days.** Adjust only demonstrated issues with keywords, limits, filters, or weights.

## 11. Focused verification and completion criteria

Use saved fixtures for routine tests and a small number of live checks. Verify:

- A strong match with sparse metadata can qualify.
- An irrelevant or explicitly ineligible role is filtered for the right reason.
- Mentions of senior colleagues and accidental technology substrings do not create false matches.
- Stable IDs prevent repeated alerts across normal runs and overlapping queries.
- A delivery failure does not discard earlier completed work or mark failed messages processed.
- Corrupt/unavailable state cannot trigger a fresh flood of alerts.
- A broken source does not block healthy sources or appear as a healthy empty result.
- Scheduled runs work without the local PC or personal platform sessions.

Target LinkedIn and Internshala as the core sources. Wellfound can be enabled or explicitly disabled based on feasibility. If a core source cannot work within the public-access constraints, document that gap before calling the planned source coverage complete.

The practical acceptance test is several days of useful alerts with little intervention. Tune toward the user's judgment of relevance and preferred alert volume; do not optimize an abstract score for its own sake.

## 12. Out of scope

No dashboard, website, multi-user support, automatic applications, database, LLM ranking, embeddings, resume parsing, browser automation, authenticated scraping, proxy infrastructure, cross-source fuzzy deduplication, message digests, interactive bot commands, microservices, or separate monitoring service.

Add complexity only when an observed problem matters to this user's job search. Keep fixes inside the existing modules whenever practical.

## Reference notes

- [JobSpy documentation](https://github.com/speedyapply/JobSpy/blob/main/README.md): LinkedIn options and the extra requests required for full descriptions.
- [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): default-branch execution, possible delays/dropped runs, and automatic schedule disabling after 60 days of inactivity in public repositories.
- [Telegram Bot API](https://core.telegram.org/bots/api): sendMessage responses, message limits, and rate-limit retry parameters.

Public-page visibility and library documentation do not establish reliable collection from Actions. The initial remote feasibility check remains necessary.
