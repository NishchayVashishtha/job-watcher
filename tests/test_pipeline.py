import json

import main
from models import Job
from state import State, load_state, save_state


def _job(number: int, title: str = "Backend Engineer Intern", description: str = "Python and FastAPI backend role") -> Job:
    return Job(id=f"test:{number}", source="test", title=title, description=description, url=f"https://example.com/jobs/{number}")


def test_delivery_failure_preserves_completed_ids_and_retries_later(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", False)
    path = tmp_path / "seen.json"
    sent = []

    def send_once(job, evaluation):
        if job.id == "test:2":
            raise RuntimeError("delivery unavailable")
        sent.append(job.id)

    fetchers = {"test": lambda: [_job(1), _job(2), _job(1)]}
    status, summary = main.run(path, init_state=True, fetchers=fetchers, sender=send_once)
    assert status == 1 and summary.delivered == 1
    assert load_state(path).processed == {"test:1"}

    status, summary = main.run(path, fetchers=fetchers, sender=lambda job, _: sent.append(job.id))
    assert status == 0 and summary.delivered == 1
    assert sent == ["test:1", "test:2"]
    assert load_state(path).processed == {"test:1", "test:2"}


def test_rejected_and_below_threshold_are_not_reprocessed(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", False)
    path = tmp_path / "seen.json"
    fetchers = {"test": lambda: [_job(1, "Senior Backend Engineer"), _job(2, "Office Assistant")]}
    status, summary = main.run(path, init_state=True, fetchers=fetchers, sender=lambda *_: None)
    assert status == 0 and summary.rejected == 1 and summary.below_threshold == 1
    assert load_state(path).processed == {"test:1", "test:2"}
    _, repeat = main.run(path, fetchers=fetchers, sender=lambda *_: None)
    assert repeat.new == 0


def test_bad_state_stops_before_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", False)
    path = tmp_path / "seen.json"
    path.write_text("{broken")
    called = []
    try:
        main.run(path, fetchers={"test": lambda: called.append(True)})
        assert False, "expected corrupt state to fail"
    except ValueError:
        pass
    assert not called


def test_dry_run_does_not_write_state_or_send(tmp_path):
    path = tmp_path / "seen.json"
    status, summary = main.run(path, dry_run=True, fetchers={"test": lambda: [_job(1)]}, sender=lambda *_: 1 / 0)
    assert status == 0 and summary.selected == 1
    assert not path.exists()


def test_one_failing_source_does_not_block_another(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", False)
    path = tmp_path / "seen.json"
    def fail():
        raise RuntimeError("blocked")
    status, summary = main.run(path, init_state=True, fetchers={"bad": fail, "good": lambda: [_job(1)]}, sender=lambda *_: None)
    assert status == 0 and summary.sources_failed == 1 and summary.delivered == 1


def test_state_format_is_sorted_and_versioned(tmp_path):
    path = tmp_path / "seen.json"
    save_state(path, State({"b", "a"}))
    assert json.loads(path.read_text()) == {"version": 1, "processed": ["a", "b"]}
