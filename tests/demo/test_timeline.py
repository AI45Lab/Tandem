"""demo 时间轴 / 需求章节 / 页面渲染的单测。

这些是 v2 的核心：真实时钟泳道、结构化需求章节、对比页。
不依赖 `rjob_logs/` 里的真实 run，也不 import `tandem` / `tandem_eval`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "demo"))

from pages import render_compare, render_index  # noqa: E402
from timeline import (  # noqa: E402
    build_chapters,
    build_timeline,
    parse_requirements,
)


def _call(role: str, time_value: float) -> dict:
    return {"role": role, "time": time_value, "attempt": 1}


def _step(index: int, obs_time: float, ranking: dict | None = None) -> dict:
    return {
        "step": index,
        "wall_time": obs_time,
        "ranking": ranking or {},
        "candidates": [],
        "verification": {},
        "action": {"kind": "gui"},
    }


def test_parse_requirements_reads_structured_list():
    payload = {"requirements": [{"id": "R1", "requirement": "做 A"}, {"id": "R2", "requirement": "做 B"}]}
    calls = [
        {
            "role": "task_requirements",
            "time": 1.0,
            "response": {"choices": [{"message": {"content": json.dumps(payload)}}]},
        }
    ]
    items = parse_requirements(calls)
    assert [item["id"] for item in items] == ["R1", "R2"]
    assert items[0]["requirement"] == "做 A"


def test_parse_requirements_survives_bad_json():
    calls = [
        {
            "role": "task_requirements",
            "time": 1.0,
            "response": {"choices": [{"message": {"content": "not json"}}]},
        }
    ]
    assert parse_requirements(calls) == []


def test_build_timeline_lanes_are_real_and_normalized():
    steps = [
        _step(0, 100.0, {"latency_ms": 800}),
        _step(1, 130.0),
    ]
    calls = [
        _call("task_requirements", 0.0),
        _call("plan_step", 80.0),
        _call("verify_observation", 110.0),
        _call("plan_step", 120.0),
        _call("verify_observation", 150.0),
    ]
    timeline = build_timeline(steps, calls, wall_seconds=160.0)
    assert timeline["duration"] > 0
    spans = timeline["spans"]
    assert len(spans) == 2
    # 区间以回放起点为原点
    assert spans[0]["at"] == 0.0
    assert spans[1]["at"] > 0
    first = spans[0]["lanes"]
    assert first["plan"] == [0.0, 0.0] or first["plan"][1] >= first["plan"][0]
    # 排序服务泳道用的是服务端实测延迟（秒）
    assert spans[0]["lanes"]["rank"][1] - spans[0]["lanes"]["rank"][0] == 0.8
    # 四条泳道都要有名字
    assert [lane["key"] for lane in timeline["lanes"]] == ["plan", "rank", "act", "verify"]


def test_build_timeline_handles_episode_without_llm_calls():
    timeline = build_timeline([_step(0, 10.0)], [], wall_seconds=None)
    assert timeline["spans"] == []
    assert timeline["duration"] == 0.0


def test_build_chapters_maps_requirements_to_steps_without_duplicates():
    steps = [
        {
            "step": 0,
            "verification": {"requirement_checks": [{"id": "R1", "status": "not_met"}]},
            "terminal": {},
        },
        {
            "step": 1,
            "verification": {"requirement_checks": [{"id": "R1", "status": "not_met"}]},
            "terminal": {
                "completion_check": {
                    "requirement_checks": [{"id": "R1", "status": "met", "evidence": "已加日历"}]
                }
            },
        },
    ]
    requirements = [{"id": "R1", "requirement": "做 A"}, {"id": "R2", "requirement": "做 B"}]
    chapters = build_chapters(steps, requirements)
    ids = [chapter["id"] for chapter in chapters]
    assert ids == ["R1", "R2"], "同一条需求不能因多次核验而重复出现"
    first = chapters[0]
    assert first["final"] == "met"
    assert first["final_evidence"] == "已加日历"
    assert first["steps"] == [0, 1]
    assert first["requirement"] == "做 A"


def _cell(score, wall, tokens, steps, calls, jev):
    return {
        "status": "scored",
        "score": score,
        "scored": True,
        "stop_reason": "done",
        "exception_type": None,
        "wall_seconds": wall,
        "steps": steps,
        "tokens": tokens,
        "llm_calls": calls,
        "jev_calls": jev,
    }


def test_render_index_and_compare_contain_expected_blocks():
    comparison = {
        "runs": [
            {
                "run_id": "run-a",
                "benchmark": "osworld2",
                "git_describe": "abc",
                "selector_backend": "jev",
                "budget": {},
                "totals": {},
            },
            {
                "run_id": "run-b",
                "benchmark": "osworld2",
                "git_describe": "def",
                "selector_backend": "kev",
                "budget": {},
                "totals": {},
            },
        ],
        "tasks": [
            {
                "task_id": "001",
                "runs": {
                    "run-a": _cell(1.0, 500.0, 300000, 10, 24, 2),
                    "run-b": _cell(1.0, 550.0, 230000, 9, 19, 0),
                },
            }
        ],
    }
    index = render_index([], comparison)
    assert "成本 × 准确率" in index
    assert "class=\"scatter\"" in index
    compare = render_compare(comparison)
    assert 'id="cmp-a"' in compare
    assert 'id="cmp-b"' in compare
    assert "两个 run 对比" in compare


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))  # noqa: F821
