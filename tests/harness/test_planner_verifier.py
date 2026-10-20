"""planner / verifier：LLM 组件的 prompt 构造与结果整形（client 全 mock）。"""

from __future__ import annotations

import base64
import json

import pytest

from tandem.planner import plan_step
from tandem.verifier import task_requirements, verify_observation

from .conftest import A11Y_XML, build_targets


class FakeClient:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def json_request(self, messages, validate, *, role):
        self.calls.append({"messages": messages, "role": role})
        assert validate(self.value), "mock 返回值必须通过组件自身的 valid_plan/校验"
        return self.value


def _running_plan(**overrides):
    base = {
        "done": False,
        "task_status": "running",
        "current_goal": "点击确定",
        "expected_observation": "对话框关闭",
        "action_proposals": [
            {"operation": "click", "target_id": "a11y:snap:0", "target_name": "确定",
             "target_role": "push_button"}
        ],
    }
    base.update(overrides)
    return base


def test_plan_step_prompt_structure(tmp_path):
    screenshot = tmp_path / "s.png"
    screenshot.write_bytes(b"img")
    client = FakeClient(_running_plan())
    plan = plan_step(client, "整理表格", screenshot, build_targets(), [], A11Y_XML)
    assert plan == _running_plan()
    messages = client.calls[0]["messages"]
    assert client.calls[0]["role"] == "plan_step"
    system = messages[0]["content"]
    user_content = messages[1]["content"]
    assert "You plan one GUI state transition at a time" in system
    assert "Do not give coordinates" in system
    prompt = json.loads(user_content[0]["text"])
    assert prompt["task"] == "整理表格"
    assert prompt["visible_controls"][0]["id"].startswith("a11y:snap:")
    assert prompt["visible_controls"][0]["focused"] is True  # focused 目标排序优先
    assert prompt["recent_actions"] == []
    image_url = user_content[1]["image_url"]["url"]
    assert image_url.endswith(base64.b64encode(b"img").decode())


def test_plan_step_cli_allowed_patches_system_prompt(tmp_path):
    screenshot = tmp_path / "s.png"
    screenshot.write_bytes(b"img")
    client = FakeClient(
        _running_plan(route="cli", command="ls", action_proposals=None)
    )
    plan_step(client, "t", screenshot, build_targets(), [], A11Y_XML, allow_cli=True)
    system = client.calls[0]["messages"][0]["content"]
    assert "Do not give coordinates" not in system
    assert "You may instead choose route=cli" in system


def test_plan_step_recent_tail_and_remaining_steps(tmp_path):
    screenshot = tmp_path / "s.png"
    screenshot.write_bytes(b"img")
    client = FakeClient(_running_plan())
    recent = [{"goal": f"g{i}", "expected_observation": f"e{i}"} for i in range(6)]
    plan_step(client, "t", screenshot, build_targets(), recent, A11Y_XML,
              remaining_steps=7)
    prompt = json.loads(client.calls[0]["messages"][1]["content"][0]["text"])
    assert prompt["recent_actions"] == recent[-4:]
    assert prompt["remaining_decisions"] == 7


def _verified(**overrides):
    base = {
        "outcome": "achieved",
        "evidence": "ok",
        "task_status": "incomplete",
        "path_input_focused": False,
        "state_changed": True,
    }
    base.update(overrides)
    return base


def test_verify_observation_includes_execution_result_for_cli(tmp_path):
    before, after = tmp_path / "b.png", tmp_path / "a.png"
    before.write_bytes(b"b")
    after.write_bytes(b"a")
    client = FakeClient(_verified())
    execution = {"returncode": 0, "stdout": "x", "stderr": "", "kind": "cli", "acknowledged": True}
    verify_observation(client, "t", after, previous=before, expected="变化",
                       action={"kind": "cli"}, recent=[], execution_result=execution)
    context = json.loads(client.calls[0]["messages"][1]["content"][0]["text"])
    assert context["execution_result"] == execution
    labels = [part["text"] for part in client.calls[0]["messages"][1]["content"]
              if part.get("type") == "text" and part["text"] in ("BEFORE", "CURRENT")]
    assert labels == ["BEFORE", "CURRENT"]


def test_verify_observation_control_check_override(tmp_path):
    after = tmp_path / "a.png"
    after.write_bytes(b"a")
    client = FakeClient(_verified())
    result = verify_observation(
        client, "t", after,
        control_state_check={"target": "启用", "before": "false", "after": "false", "changed": False},
    )
    assert result["outcome"] == "not_achieved"
    assert result["task_status"] == "incomplete"
    assert result["evidence"].startswith("A11y toggle state did not change")


def test_verify_terminal_downgrades_when_output_file_missing(tmp_path):
    after = tmp_path / "a.png"
    after.write_bytes(b"a")
    client = FakeClient(
        _verified(task_status="completed", requirement_checks=[
            {"id": "R1", "status": "met", "evidence": "ok"},
        ])
    )
    result = verify_observation(
        client, "t", after, terminal_claim={"done": True},
        requirements=[{"id": "R1", "requirement": "保存文件", "output_path": "/home/user/out.xlsx"}],
        output_files={"/home/user/out.xlsx": False},
    )
    assert result["task_status"] == "incomplete"
    assert result["outcome"] == "not_achieved"


@pytest.mark.parametrize(
    "instruction,raw_path,expected",
    [
        # 路径绝对且出现在任务指令中 → 保留
        ("保存到 /home/user/报表.xlsx", "/home/user/报表.xlsx", "/home/user/报表.xlsx"),
        # 路径未出现在指令中（模型杜撰）→ 置空
        ("保存一个报表", "/home/user/报表.xlsx", None),
        # 相对路径 → 置空
        ("保存到报表.xlsx", "报表.xlsx", None),
    ],
)
def test_task_requirements_output_path_sanitization(instruction, raw_path, expected):
    client = FakeClient(
        {"requirements": [{"id": "R1", "requirement": "保存", "output_path": raw_path}]}
    )
    result = task_requirements(client, instruction)
    assert result[0]["output_path"] == expected
