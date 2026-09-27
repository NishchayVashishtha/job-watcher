import pytest

from models import Evaluation, Job
from telegram import DeliveryError, send_telegram


class Response:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self.body = body
        self.ok = 200 <= status < 300

    def json(self):
        return self.body


def _job() -> Job:
    return Job(id="test:1", source="test", title="Backend Intern", url="https://example.com/job/1")


def test_telegram_requires_api_confirmation(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    calls = []
    def post(url, *, json, timeout):
        calls.append((url, json))
        return Response(200, {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr("telegram.requests.post", post)
    send_telegram(_job(), Evaluation(70, ("preferred role",)))
    assert len(calls) == 1
    assert calls[0][1]["chat_id"] == "123"
    assert "Backend Intern" in calls[0][1]["text"]


def test_telegram_failure_does_not_expose_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr("telegram.requests.post", lambda *a, **k: Response(400, {"ok": False}))
    with pytest.raises(DeliveryError) as error:
        send_telegram(_job(), Evaluation(70))
    assert "400" in str(error.value)
    assert "secret-token" not in str(error.value)
