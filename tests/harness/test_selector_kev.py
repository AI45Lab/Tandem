"""KevPolicy：System One 协议映射 / 两阶段排序 / 快速失败 / 后端切换。"""

from __future__ import annotations

import json

import pytest

from tandem.components import build_default
from tandem.config import SessionConfig
from tandem.selector import ranking_dict
from tandem.selector_kev import KevPolicy

from ..harness.conftest import build_space, build_targets


class FakeKepOpener:
    """按调用序返回 /v1/systemone 响应；记录请求供断言。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(json.loads(request.data.decode("utf-8")))
        payload = self.responses.pop(0)
        return _FakeResponse(payload)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _policy(tmp_path, responses):
    del tmp_path
    opener = FakeKepOpener(responses)
    return KevPolicy("http://kev-fake:8008", timeout_seconds=5, opener=opener), opener


def _answer(probabilities):
    return {"model": "kev-latest", "answers": {"q": {
        "type": "choice", "choice": max(probabilities, key=probabilities.get),
        "confidence": 0.5, "probabilities": probabilities}}}


def test_rank_two_stage_with_probabilities(tmp_path):
    targets = build_targets()
    space = build_space(targets)
    space.target_heads = {"click": space.target_heads["click"][:2]}
    space.controls = {}
    first_id, second_id = [c.id for c in space.target_heads["click"]]
    policy, opener = _policy(tmp_path, [
        _answer({"click": 0.1, "type_text": 0.9}),          # operation 阶段
        _answer({first_id: 0.2, second_id: 0.8}),           # action 阶段（真实候选 id）
    ])
    ranking = policy.rank(stage_goal="任务", intent="打开", active_window="",
                          targets=targets, action_space=space, recent_actions=[])
    assert ranking.winner.operation == "click"
    assert ranking.winner.id == second_id
    assert ranking.target_margin == pytest.approx(0.8 - 0.2)
    assert ranking.used_image is False
    assert ranking_dict(ranking)["score_type"] == "jev_omni_choice_softmax"
    # 请求体符合 System One：state 为对象、criteria 为选项→描述
    first = opener.requests[0]
    assert first["model"] == "kev-latest"
    assert first["questions"]["q"]["type"] == "choice"
    # 空间已裁剪为 click-only：criteria 只含实际候选的操作
    assert set(first["questions"]["q"]["criteria"]) == {"click"}
    # 响应里的多余键（type_text）按缺失处理为 0 分，不影响结果
    assert isinstance(first["state"], dict) and first["state"]["stage_goal"] == "任务"


def test_rank_single_candidate_skips_action_request(tmp_path):
    policy, opener = _policy(tmp_path, [_answer({"click": 1.0})])
    targets = build_targets()
    space = build_space(targets)
    space.target_heads = {"click": space.target_heads["click"][:1]}
    space.controls = {}
    ranking = policy.rank(stage_goal="t", intent="i", active_window="",
                          targets=targets, action_space=space, recent_actions=[])
    assert ranking.winner is not None
    assert ranking.action_ranked[0]["score"] == 1.0
    assert len(opener.requests) == 1


def test_missing_probability_counts_as_zero(tmp_path):
    from tandem.candidates import ActionCandidate

    policy, _ = _policy(tmp_path, [_answer({"type_text": 1.0})])
    targets = build_targets()
    space = build_space(targets)
    space.target_heads = {"click": space.target_heads["click"][:2]}
    space.controls = {"type_text": ActionCandidate(
        id="TYPE_TEXT", operation="type_text", description="输入文本", source="global")}
    ranking = policy.rank(stage_goal="t", intent="i", active_window="",
                          targets=targets, action_space=space, recent_actions=[])
    assert ranking.winner.operation == "type_text"


def test_malformed_response_raises(tmp_path):
    policy, _ = _policy(tmp_path, [{"answers": {}}])
    with pytest.raises(ValueError, match="probabilities"):
        policy.rank(stage_goal="t", intent="i", active_window="",
                    targets=build_targets(), action_space=build_space(build_targets()),
                    recent_actions=[])


def test_config_and_build_default_backend_switch(tmp_path):
    with pytest.raises(ValueError, match="selector_backend"):
        SessionConfig(selector_backend="omni")
    class NullClient:
        pass

    kev_components = build_default(client=NullClient(), endpoint="http://kev:8008",
                                   config=SessionConfig(selector_backend="kev"))
    assert isinstance(kev_components.selector, KevPolicy)
    jev_components = build_default(client=NullClient(), endpoint="http://jev:8891",
                                   config=SessionConfig())
    assert not isinstance(jev_components.selector, KevPolicy)
