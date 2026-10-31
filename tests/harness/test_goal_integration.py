"""Synthetic compatibility tests against main's semantic pipeline and JEV recovery."""

import base64
import io
import json
import urllib.error
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from tandem.config import SessionConfig
from tandem.memory.state import TaskMemory
from tandem.models.jev import JevOmniPolicy
from tandem.models.ranking import Ranking
from tandem.models.slow import SlowModelClient
from tandem.protocol.models import BrowserSnapshot
from tandem.runtime.goal_stage import ObservationRequired

from .conftest import build_space, build_targets, make_observation
from .test_goal_memory import session
from .test_goal_stage import plan, requirements
from .test_selector_compile import ScriptedOpener
from .test_slow_transport import _Response


def test_goal_passes_cdp_enriched_semantics_to_planner_and_selector(tmp_path):
    s = session()
    s.begin("Enter the receipt date", requirements())
    tree = ('<desktop-frame><application name="Google Chrome" active="true">'
            '<entry name="Address and search bar" screencoord="(10,40)" size="(600,30)"/>'
            '<entry editable="true" screencoord="(250,293)" size="(218,18)"/>'
            '</application></desktop-frame>')
    observation = make_observation(tmp_path, 0, tree_xml=tree)
    snapshot = tmp_path / "browser.json"
    snapshot.write_text(json.dumps({"elements": [{
        "index": 1, "role": "entry", "name": "Receipt Date", "description": "dd/mm/yyyy",
        "value": "", "x": 250, "y": 293, "width": 218, "height": 18,
        "label_source": "dom_label", "operations": ["click", "type_text"],
    }]}))
    observation = replace(observation, browser_snapshot=BrowserSnapshot(
        present=True, source="cdp", path=str(snapshot), node_count=1))

    def planner(*args, **kwargs):
        target = next(t for t in args[2] if t.name == "Receipt Date")
        assert target.source == "dom" and target.scope == "web_content"
        return {**plan(), "inputs": [{"label": "Receipt Date", "target_hint": "Receipt Date",
                                      "text": "11/12/2025", "input_mode": "replace"}]}

    s.components.planner = planner
    with pytest.raises(ObservationRequired, match="planner_returned"):
        s.act(observation)

    def rank(**kwargs):
        winner = kwargs["action_space"].target_heads["type_text"][0]
        target = next(t for t in kwargs["targets"] if t.id == winner.target_id)
        assert target.name == "Receipt Date" and target.description == "dd/mm/yyyy"
        return Ranking(winner, [], [], 0, 0, 1, True)

    s.components.selector.rank = rank
    action = s.act(observation)
    assert action.action_type == "type" and action.parameters["click"] == [359, 302]


def test_joint_goal_choices_retain_main_endpoint_recovery(monkeypatch):
    monkeypatch.setattr("tandem.models.jev.time.sleep", lambda seconds: None)
    targets = build_targets()
    space = build_space(targets)
    space.target_heads = {"click": space.target_heads["click"][:1]}
    space.controls = {"done": space.controls["done"]}
    click, done = space.candidates()
    opener = ScriptedOpener([
        urllib.error.URLError("old endpoint unavailable"), {"status": "ok"},
        {"scores": [0.9, 0.1], "used_image": True}, {"status": "ok"},
        {"scores": [0.1, 0.9], "used_image": True},
    ])
    endpoints = iter(["http://old", "http://new", "http://new"])
    policy = JevOmniPolicy("http://old", opener=opener, joint_actions=True,
                           endpoint_provider=lambda: next(endpoints))
    ranking = policy.rank(stage_goal="Goal", intent="Intent", active_window="Chrome",
                          targets=targets, action_space=space, recent_actions=[])
    assert ranking.operation_ranked[0]["operation"] == click.operation
    assert ranking.winner is done and policy.endpoint == "http://new"
    assert opener.requests[-2:] == ["http://new/", "http://new/rank"]


def test_goal_image_budget_and_verify_override_do_not_change_step_transport(tmp_path):
    encoded = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(encoded, format="PNG")
    image_url = "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode()
    for mode in ("step", "goal"):
        config = SessionConfig(execution_mode=mode, slow_max_tokens=32768,
                               slow_verify_max_tokens=8192, slow_reasoning_effort="max",
                               slow_verify_reasoning_effort="low")
        client = SlowModelClient({"base_url": "https://test.invalid"}, config, tmp_path / "audit.jsonl")
        messages = [{"role": "user", "content": [{"type": "image_url",
                     "image_url": {"url": image_url}}]}]
        with patch("urllib.request.urlopen", return_value=_Response()) as opener:
            client.json_request(messages, bool, role="verify_stage")
        payload = json.loads(opener.call_args.args[0].data)
        sent_url = payload["messages"][0]["content"][0]["image_url"]["url"]
        assert sent_url.startswith("data:image/jpeg" if mode == "goal" else "data:image/png")
        assert payload["max_tokens"] == 8192 and payload["reasoning_effort"] == "low"


def test_goal_memory_and_stage_verifier_are_replaceable():
    s = session()
    factory = Mock(return_value=TaskMemory("Edit", requirements()))
    s.components.memory_factory = factory
    s.components.stage_verifier = Mock()
    s.begin("Edit", requirements())
    factory.assert_called_once_with("Edit", requirements())
    assert s.goal.memory is factory.return_value
