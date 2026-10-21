"""TandemSession：planner_led 决策状态机（组件全 mock，场景级）。"""

from __future__ import annotations

import json

import pytest

from tandem.config import SessionConfig
from tandem.protocol.models import CliAction, FailAction, FinishAction, GuiAction, WaitAction
from tandem.session import TandemSession

from .conftest import (
    FixedSelector,
    NullSelector,
    ScriptedPlanner,
    ScriptedVerifier,
    cli_receipt,
    gui_receipt,
    make_components,
    make_observation,
    valid_verifier_response,
)


def _gui_plan(**overrides):
    base = {
        "done": False,
        "task_status": "running",
        "current_goal": "点击确定",
        "expected_observation": "对话框发生变化",
        "action_proposals": [
            {"operation": "click", "target_id": "a11y:t0:0", "target_name": "确定",
             "target_role": "push_button"}
        ],
    }
    base.update(overrides)
    return base


def _done_plan(status="completed"):
    return {"done": True, "task_status": status, "current_goal": "任务完成",
            "expected_observation": ""}


def _session(plans, responses, selector=None):
    planner = ScriptedPlanner(list(plans))
    verifier = ScriptedVerifier(list(responses))
    return (
        TandemSession(make_components(planner, verifier, selector or FixedSelector())),
        planner,
        verifier,
    )


def test_gui_happy_path_to_finish(tmp_path):
    session, planner, verifier = _session(
        [_gui_plan(), _done_plan()],
        [
            valid_verifier_response(),
            valid_verifier_response(task_status="completed", requirement_checks=[]),
        ],
    )
    session.begin("整理表格", [])
    action = session.act(make_observation(tmp_path, 0))
    assert isinstance(action, GuiAction) and action.action_type == "click"
    assert action.parameters == {"x": 140, "y": 212}  # 确定: (100,200)+(80,24) 中心
    assert action.target_id == "a11y:t0:0"
    terminal = session.act(make_observation(tmp_path, 1, receipt=gui_receipt()))
    assert isinstance(terminal, FinishAction) and terminal.outputs == ()
    # 验证调用带 BEFORE/CURRENT，终态验证带 terminal_claim
    assert verifier.calls[0]["previous"] is not None
    assert verifier.calls[1]["terminal_claim"]["done"] is True
    assert session.recent[0]["operation"] == "click"
    assert planner.calls[1]["recent_tail"][0]["operation"] == "click"
    routes = [event["route"] for event in session.events]
    assert routes == ["planner", "gui", "gui_verified", "planner", "terminal"]


def test_cli_route_with_receipt_verification(tmp_path):
    session, _, verifier = _session(
        [_gui_plan(route="cli", command="ls -la", action_proposals=None), _done_plan()],
        [
            valid_verifier_response(),
            valid_verifier_response(task_status="completed", requirement_checks=[]),
        ],
    )
    session.begin("整理", [])
    action = session.act(make_observation(tmp_path, 0))
    assert isinstance(action, CliAction)
    assert action.command == "ls -la" and action.want_observation == "screenshot"
    assert action.timeout_s == 90
    terminal = session.act(
        make_observation(tmp_path, 1, receipt=cli_receipt(stdout="a.txt"))
    )
    assert isinstance(terminal, FinishAction)
    assert verifier.calls[0]["execution_result"]["stdout"] == "a.txt"
    assert session.recent[0]["operation"] == "cli"
    assert session.verified_focus is None


def test_cli_failure_forces_not_achieved(tmp_path):
    session, _, _verifier = _session(
        [_gui_plan(route="cli", command="oops", action_proposals=None), _done_plan()],
        [valid_verifier_response(), valid_verifier_response(task_status="completed")],
    )
    session.begin("整理", [])
    session.act(make_observation(tmp_path, 0))
    session.act(make_observation(tmp_path, 1, receipt=cli_receipt(returncode=127, stderr="not found")))
    entry = session.recent[0]
    assert entry["outcome"] == "not_achieved"
    assert entry["verification"]["task_status"] == "incomplete"


def test_no_action_limit_triggers_fail(tmp_path):
    session, planner, _ = _session(
        [_gui_plan(), _gui_plan(), _gui_plan()],
        [],
        selector=NullSelector(),
    )
    session.begin("整理", [])
    action = session.act(make_observation(tmp_path, 0))
    assert isinstance(action, FailAction) and action.reason == "no_action_limit"
    assert len(session.recent) == 3
    assert all(item["outcome"] == "no_action" for item in session.recent)
    assert len(planner.calls) == 3


def test_done_probe_and_finish_with_outputs(tmp_path):
    requirements = [{"id": "R1", "requirement": "保存报表", "output_path": "/home/user/报表.xlsx"}]
    session, _, verifier = _session(
        [_done_plan()],
        [valid_verifier_response(task_status="completed", requirement_checks=[
            {"id": "R1", "status": "met", "evidence": "文件存在"}])],
    )
    session.begin("整理", requirements)
    probe = session.act(make_observation(tmp_path, 0))
    assert isinstance(probe, CliAction)
    assert "报表.xlsx" in probe.command and probe.want_observation == "none"
    assert probe.timeout_s == 30
    exists = json.dumps({"/home/user/报表.xlsx": True})
    terminal = session.act(
        make_observation(tmp_path, 1, receipt=cli_receipt(stdout=exists))
    )
    assert isinstance(terminal, FinishAction)
    assert terminal.outputs == ("/home/user/报表.xlsx",)
    assert verifier.calls[0]["output_files"] == {"/home/user/报表.xlsx": True}
    assert verifier.calls[0]["terminal_claim"]["task_status"] == "completed"


def test_done_probe_missing_file_rejects_and_replans(tmp_path):
    requirements = [{"id": "R1", "requirement": "保存报表", "output_path": "/home/user/报表.xlsx"}]
    replan = _gui_plan(
        action_proposals=[
            # 重规划发生在 step 1，引用当帧 target（真实 planner 只会看到当帧 visible_controls）
            {"operation": "click", "target_id": "a11y:t1:0", "target_name": "确定",
             "target_role": "push_button"}
        ]
    )
    session, planner, _ = _session(
        [_done_plan(), replan],
        [
            valid_verifier_response(task_status="incomplete"),
            valid_verifier_response(),
        ],
    )
    session.begin("整理", requirements)
    probe = session.act(make_observation(tmp_path, 0))
    assert isinstance(probe, CliAction)
    missing = json.dumps({"/home/user/报表.xlsx": False})
    action = session.act(make_observation(tmp_path, 1, receipt=cli_receipt(stdout=missing)))
    assert isinstance(action, GuiAction)  # 完成被拒 → 重新规划出 GUI 动作
    assert session.done_probe is None
    assert session.recent[0]["operation"] == "completion_rejected"
    assert len(planner.calls) == 2


def test_budget_exhaustion_short_circuits(tmp_path):
    session, planner, _ = _session([_gui_plan()], [])
    session.begin("整理", [])
    action = session.act(make_observation(tmp_path, 0, steps=0))
    assert isinstance(action, FailAction) and action.reason == "max_steps"
    assert planner.calls == []
    wall = session.act(make_observation(tmp_path, 1, wall=0.0))
    assert isinstance(wall, FailAction) and wall.reason == "wall_time_limit"


def test_completion_rejected_replans_within_same_observation(tmp_path):
    session, planner, _ = _session(
        [_done_plan(), _gui_plan()],
        [valid_verifier_response(task_status="incomplete")],
    )
    session.begin("整理", [])
    action = session.act(make_observation(tmp_path, 0))
    assert isinstance(action, GuiAction)
    assert len(planner.calls) == 2
    assert session.recent[0]["operation"] == "completion_rejected"


def test_verified_focus_set_after_ctrl_l(tmp_path):
    plan = _gui_plan(
        current_goal="聚焦地址栏",
        action_proposals=[{"operation": "keypress", "key_sequence": [["ctrl", "l"]]}],
    )
    follow_up = _gui_plan(
        action_proposals=[
            {"operation": "click", "target_id": "a11y:t1:0", "target_name": "确定",
             "target_role": "push_button"}
        ]
    )
    session, planner, _ = _session(
        [plan, follow_up, _done_plan()],
        [
            valid_verifier_response(path_input_focused=True),
            valid_verifier_response(),
            valid_verifier_response(task_status="completed"),
        ],
    )
    session.begin("整理", [])
    action = session.act(make_observation(tmp_path, 0))
    assert isinstance(action, GuiAction) and action.action_type == "hotkey"
    assert action.parameters == {"sequence": [["ctrl", "l"]]}
    session.act(make_observation(tmp_path, 1, receipt=gui_receipt()))
    assert session.verified_focus is not None
    assert session.verified_focus["role"] == "entry"
    assert planner.calls[1]["verified_focus"] is not None


def test_missing_receipt_raises(tmp_path):
    session, _, _ = _session(
        [_gui_plan(route="cli", command="ls", action_proposals=None)],
        [valid_verifier_response()],
    )
    session.begin("整理", [])
    session.act(make_observation(tmp_path, 0))
    with pytest.raises(RuntimeError, match="执行回执"):
        session.act(make_observation(tmp_path, 1, receipt=None))


def test_wait_candidate_emits_wait_action(tmp_path):
    plan = _gui_plan(action_proposals=[{"operation": "wait"}])
    session, _, _ = _session([plan], [])
    session.begin("整理", [])
    action = session.act(make_observation(tmp_path, 0))
    assert isinstance(action, WaitAction)


def test_cli_timeout_clamped_to_protocol_limit():
    with pytest.raises(ValueError, match="cli_timeout_seconds"):
        SessionConfig(cli_timeout_seconds=200)
    assert SessionConfig(cli_timeout_seconds=120).cli_timeout_seconds == 120


def test_truncated_reasoning_raises_actionable_error(tmp_path):
    """finish_reason=length（推理吃满 max_tokens、正文为空）必须报可定位的错误。"""
    from tandem.config import SessionConfig
    from tandem.providers import KimiClient

    class TruncatingOpener:
        def __call__(self, request, timeout=None):
            return _FakeRawResponse()

    class _FakeRawResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"completion_tokens": 4099},
            }).encode()

    client = KimiClient({"base_url": "http://x"}, SessionConfig(),
                        tmp_path / "audit.jsonl")
    import urllib.request
    opener_holder = TruncatingOpener()
    original_urlopen = urllib.request.urlopen
    urllib.request.urlopen = opener_holder
    try:
        with pytest.raises(ValueError, match="raise kimi_max_tokens"):
            client.json_request([{"role": "user", "content": "hi"}], lambda v: True,
                                role="plan_step")
    finally:
        urllib.request.urlopen = original_urlopen
