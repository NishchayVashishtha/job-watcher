# Personal Job Watcher

A small Python watcher for public LinkedIn and Internshala listings. It filters and scores jobs against one editable profile, then sends selected jobs to Telegram. An optional Wellfound adapter is included but disabled by default because a public HTTP request returned 403 during development. Applications stay manual.

The full design and tradeoffs are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Set your profile

Edit `PROFILE` and the search settings in `config.py`. The committed values are **examples for testing**, not a claim about the user's experience or location. The script automatically uses dry-run mode while `PROFILE_IS_EXAMPLE = True`, so it cannot send generic-profile alerts. Set it to `False` only after entering your real preferences and reviewing a dry run.

In particular, configure the roles, skills, job types, maximum required experience, acceptable locations, remote/workplace preferences, LinkedIn search location, and Internshala pages. An empty `allowed_locations` means no location exclusion. Internshala itself targets India. The default searches and weights are starting points.

## Local use

Python 3.12 is recommended because the pinned JobSpy release requires NumPy 1.26.3. With `uv`:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python main.py --dry-run
```

Alternatively, create a Python 3.12 virtual environment with `venv` and use its `pip`. The first dry run can start without a state file; it neither saves state nor sends messages.

Once the profile is real, create a Telegram bot, get its bot token and your chat ID, and supply them as environment variables. The first local live run needs `--init-state` if `seen.json` does not exist. Subsequent runs use the existing state file.

```sh
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
.venv/bin/python main.py --dry-run
.venv/bin/python main.py --init-state
```

The bot must be able to message the selected chat. Keep the token out of commits and shell history. The token and chat ID are GitHub Actions secrets for remote execution.

## GitHub Actions

Create a GitHub repository for this directory and push the code to its default branch. Add repository secrets named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. The workflow in `.github/workflows/collect.yml` supports a manual run. It runs in dry-run mode while the example profile flag remains set. The four-hour schedule (minute 17 UTC) is gated by the repository variable `JOB_WATCHER_ENABLED=true`, so scheduled collection stays inactive until you configure the real profile and Telegram secrets.

The workflow creates a `state` branch on its first run. Later runs read `seen.json` from that branch and write completed IDs back to it. The workflow grants itself `contents: write`; repository settings must allow its token to write. Runs are serialized with GitHub Actions concurrency. Do not delete or rename `state` casually, because that would make old listings look new.

Run the workflow manually and inspect its Actions summary before relying on the schedule. Public job sites may block GitHub-hosted runners; a local successful request cannot prove remote collection will work. The enabled LinkedIn and Internshala collectors report failures independently. Enable Wellfound in `ENABLED_SOURCES` only after confirming public requests and parsing work from the runner.

Scheduled GitHub Actions may run late or be dropped. The searches overlap previous runs, and stable IDs suppress normal repeats. In an inactive public repository, GitHub can disable scheduled workflows after 60 days.

## Tuning and limits

The initial threshold is 60. Role and early-career fit can supply 70 points, so a good listing with no technology detail can qualify. Skills, work arrangement, and freshness provide additional points. A maximum of 10 selected jobs are considered per run. Change these values in `config.py` or the documented `JOB_WATCHER_*` environment variables.

The state records rejected, below-threshold, and successfully delivered listings. Failed delivery leaves a listing unprocessed, so it can be retried if the source returns it again. A crash between sending and saving state can produce a duplicate alert. A listing that disappears before retry can be missed. Those limits keep the project small; add durable pending alerts only if they cause a real problem.

Changing scoring rules does not revisit old processed jobs. Use saved fixtures and dry runs to tune the evaluator. Set `JOB_WATCHER_STATE_PATH` to use a different state file locally.

## Tests

```sh
.venv/bin/python -m pytest -q
```

Tests use saved listing samples and mocks; they do not need personal accounts, Telegram credentials, or live collection.
