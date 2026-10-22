"""demo 层的单测：合成结果目录 → 文档。

不依赖 `rjob_logs/` 里的真实 run（CI 上没有），也不 import `tandem` /
`tandem_eval`——demo 与 harness 完全解耦，这条边界本身就是被测项之一。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "demo"))

from adapter import build_steps, load_run, scrub_paths  # noqa: E402
from helpers import make_run, scored, usage, write_jsonl  # noqa: E402
from metrics import build_comparison, llm_cost  # noqa: E402


def test_llm_cost_aggregates_by_role():
    cost = llm_cost(
        [
            {"role": "plan_step", "response": {"usage": usage(100, 200, 50)}},
            {"role": "plan_step", "response": {"usage": usage(1, 2, 0)}},
            {"role": "verify_observation", "response": {"usage": usage(10, 20, 0)}},
            {"role": "plan_step", "response": {}},
        ]
    )
    assert cost["total"]["calls"] == 4
    assert cost["total"]["prompt_tokens"] == 111
    assert cost["total"]["completion_tokens"] == 222
    assert cost["total"]["reasoning_tokens"] == 50
    assert cost["by_role"]["plan_step"]["calls"] == 3


def test_build_steps_offsets_verification_and_frames(tmp_path):
    episode = tmp_path / "ep"
    (episode / "screenshots").mkdir(parents=True)
    for name in ("step_00.png", "step_01.png"):
        (episode / "screenshots" / name).write_bytes(b"x")
    write_jsonl(
        episode / "events.jsonl",
        [
            {"step": 0, "route": "gui", "action": {"kind": "gui", "action_type": "click"}},
            {"step": 1, "route": "gui_verified", "verification": {"outcome": "achieved"}},
        ],
    )
    steps = build_steps(episode)
    assert len(steps) == 1
    # 第 0 步的裁决来自第 1 步的验证事件
    assert steps[0]["verification"]["outcome"] == "achieved"
    # 帧语义：step_NN.png 是动作 N 执行后的屏幕
    assert steps[0]["after_frame"] == "step_00.png"
    assert steps[0]["before_frame"] is None


def test_scrub_paths_hides_cluster_mounts_but_keeps_vm_paths():
    raw = "see /mnt/cluster-share/example/rjob_logs/run/episodes/tasks-001/a11y.xml"
    assert "/mnt/" not in scrub_paths(raw)
    assert "a11y.xml" in scrub_paths(raw)
    # VM 内部路径是任务语义，保留
    assert scrub_paths("/home/user/Desktop/report.pdf") == "/home/user/Desktop/report.pdf"
    assert scrub_paths(["/mnt/a/b/c.png"]) == ["<cluster-path>/c.png"]


def test_load_run_reports_unscored_without_counting_as_zero(tmp_path):
    run_dir = make_run(
        tmp_path,
        "run-a",
        [
            {"task_id": "001", "score": 1.0, "status": "scored", "steps": 2, "wall": 100.0},
            {"task_id": "002", "score": 0.25, "status": "scored", "steps": 1, "wall": 50.0},
            {
                "task_id": "003",
                "score": None,
                "status": "failed_unscored",
                "steps": 0,
                "wall": 0.001,
                "stop_reason": "exception",
                "exception_type": "ValueError",
            },
        ],
    )
    run = load_run(run_dir)
    totals = run["totals"]
    assert totals["total"] == 3
    assert totals["scored"] == 2
    assert totals["failed_unscored"] == 1
    assert totals["average_score"] == 0.625  # 未出分不计入均分
    assert totals["failures"] == {"ValueError": 1}
    assert run["fast_model"] == "kev"
    assert run["slow_model"] == "kimi-k3"


def test_build_comparison_aligns_runs_by_task(tmp_path):
    make_run(tmp_path, "run-a", [scored("001", 1.0, wall=10.0)])
    make_run(tmp_path, "run-b", [scored("001", 0.5, wall=20.0)])
    runs = [load_run(tmp_path / "run-a"), load_run(tmp_path / "run-b")]
    comparison = build_comparison(runs)
    assert len(comparison["tasks"]) == 1
    cells = comparison["tasks"][0]["runs"]
    assert cells["run-a"]["score"] == 1.0
    assert cells["run-b"]["score"] == 0.5
    assert cells["run-a"]["wall_seconds"] == 10.0
    assert cells["run-a"]["tokens"] == 330  # (10+20) + (100+200)
