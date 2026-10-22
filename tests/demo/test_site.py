"""demo 站点构建的单测：渲染载荷 + 索引/任务页产出。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "demo"))

from adapter import load_run  # noqa: E402
from build_site import build  # noqa: E402
from helpers import make_run, scored  # noqa: E402
from render import display_payload, evidence_doc, trim  # noqa: E402


def test_trim_marks_truncated_strings():
    assert trim("short") == "short"
    long_value = trim("x" * 50, limit=10)
    assert long_value.startswith("x" * 10)
    assert "已截断" in long_value


def test_display_payload_truncates_but_evidence_keeps_full(tmp_path):
    run_dir = make_run(tmp_path, "run-a", [scored("001", 1.0)])
    run = load_run(run_dir)
    task = run["tasks"][0]
    task["steps"][0]["plan"]["current_goal"] = "y" * 3000
    payload = display_payload(run, task, {})
    assert len(payload["task"]["steps"][0]["plan"]["current_goal"]) < 3000
    doc = evidence_doc(task)
    assert len(doc["steps"][0]["plan"]["current_goal"]) == 3000


def test_build_emits_index_and_task_pages(tmp_path):
    runs_root = tmp_path / "rjob_logs"
    make_run(runs_root, "run-a", [scored("001", 1.0)])
    out = tmp_path / "site"
    summary = build(runs_root, out, [runs_root / "run-a"], "osworld2")
    assert summary["runs"] == 1
    assert summary["pages"] == 1
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "OSWorld2 轨迹回放与对比" in index
    page = out / "task" / "run-a" / "001.html"
    assert page.is_file()
    body = page.read_text(encoding="utf-8")
    assert 'id="payload"' in body
    assert "披露" not in body  # 披露口径在总览页
    assert (out / "assets" / "evidence" / "run-a" / "001.json").is_file()


def test_task_page_wires_zero_state_module(tmp_path):
    """0 步任务要讲清楚「为什么没有轨迹」，需要失败态模块与占位容器。"""
    runs_root = tmp_path / "rjob_logs"
    make_run(runs_root, "run-a", [scored("001", 1.0)])
    out = tmp_path / "site"
    build(runs_root, out, [runs_root / "run-a"], "osworld2")
    body = (out / "task" / "run-a" / "001.html").read_text(encoding="utf-8")
    assert 'id="zero-state"' in body
    assert 'id="stage-media"' in body
    assert "player-fail.js" in body
    assert (out / "assets" / "player-fail.js").is_file()


def test_build_skips_runs_of_other_benchmarks(tmp_path):
    runs_root = tmp_path / "rjob_logs"
    run_dir = make_run(runs_root, "run-a", [scored("001", 1.0, wall=1.0)])
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    summary["benchmark"] = "osworld1"
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    out = tmp_path / "site"
    result = build(runs_root, out, [run_dir], "osworld2")
    assert result["runs"] == 0
    assert result["pages"] == 0
