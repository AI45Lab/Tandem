"""Slow-model transport failures use the existing bounded retry path."""

import http.client
import json
import urllib.request

from tandem.config import SessionConfig
from tandem.models.slow import SlowModelClient


class _Response:
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": '{"done": true}'}, "finish_reason": "stop"}],
        }).encode()


def test_remote_disconnect_is_retried(tmp_path, monkeypatch):
    attempts = []

    def opener(request, timeout=None):
        attempts.append(request)
        if len(attempts) == 1:
            raise http.client.RemoteDisconnected("remote closed")
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", opener)
    monkeypatch.setattr("tandem.models.slow.time.sleep", lambda seconds: None)
    client = SlowModelClient({"base_url": "http://slow"}, SessionConfig(), tmp_path / "audit.jsonl")
    value = client.json_request([{"role": "user", "content": "x"}], lambda value: True, role="plan_stage")
    assert value == {"done": True}
    assert len(attempts) == 2
    events = [json.loads(line)["event"] for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert events.count("request_start") == 2
    assert "transport_or_validation_error" in events
