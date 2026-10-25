"""批次对照器：逐题比较两个批次（默认 kev vs jev），量化空转率与得分差异。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = _ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


batch_summary = _load("batch_summary")
compare_runs = _load("compare_runs")


def _make_run(root: Path, name: str, task: str, score: float | None, stop: str,
              steps: int, winners: list[str]) -> Path:
    episode_dir = root / name / "episodes" / task
    episode_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task, "status": "scored" if score is not None else "failed_unscored",
               "score": score, "stop_reason": stop, "steps": steps}
    (episode_dir / "episode.json").write_text(json.dumps(payload), encoding="utf-8")
    (episode_dir / "timing.json").write_text(json.dumps({"wall_seconds": 60}), encoding="utf-8")
    (episode_dir / "llm_calls.jsonl").write_text(
        json.dumps({"role": "plan_step",
                    "response": {"usage": {"prompt_tokens": 10, "completion_tokens": 1}}}) + "\n",
        encoding="utf-8")
    with (episode_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
        for operation in winners:
            handle.write(json.dumps({"payload": {"winner": {"operation": operation}}}) + "\n")
    return root / name


def test_winner_stats_separates_noop_from_fallback(tmp_path):
    """只有 return_to_planner 是真空转；visual_fallback 走 grounder 产坐标点击。"""
    episode = tmp_path / "run" / "episodes" / "001"
    episode.mkdir(parents=True)
    (episode / "events.jsonl").write_text(
        "\n".join(json.dumps({"payload": {"winner": {"operation": op}}}) for op in
                 ["click", "visual_fallback", "return_to_planner", "click"]) + "\n",
        encoding="utf-8")
    stats = compare_runs.winner_stats(episode)
    assert stats["winners"] == 4
    assert stats["noop"] == 1
    assert stats["fallback"] == 1
    assert stats["noop_rate"] == 0.25


def test_compare_reports_per_task_deltas(tmp_path):
    _make_run(tmp_path, "batch-a", "001", 0.0, "no_action_limit", 5,
              ["click", "return_to_planner", "return_to_planner"])
    _make_run(tmp_path, "batch-b", "001", 0.8, "done", 12,
              ["click", "click", "click", "click"])
    a_rows = compare_runs.enrich(batch_summary.collect_rows(tmp_path, "batch-a"), tmp_path, "batch-a")
    b_rows = compare_runs.enrich(batch_summary.collect_rows(tmp_path, "batch-b"), tmp_path, "batch-b")
    result = compare_runs.compare(a_rows, b_rows)
    assert result["shared"] == 1
    assert result["b_better"] == 1
    assert result["a_better"] == 0
    assert result["b_avg"] > result["a_avg"]
    assert result["a_noop"] > result["b_noop"]
    report = compare_runs.render(result, "batch-a", "batch-b")
    assert "001" in report and "批次对照" in report


def test_compare_ignores_tasks_missing_in_one_batch(tmp_path):
    _make_run(tmp_path, "batch-a", "001", 1.0, "done", 3, ["click"])
    _make_run(tmp_path, "batch-a", "002", 0.0, "no_action_limit", 2, ["return_to_planner"])
    _make_run(tmp_path, "batch-b", "001", 1.0, "done", 3, ["click"])
    a_rows = compare_runs.enrich(batch_summary.collect_rows(tmp_path, "batch-a"), tmp_path, "batch-a")
    b_rows = compare_runs.enrich(batch_summary.collect_rows(tmp_path, "batch-b"), tmp_path, "batch-b")
    result = compare_runs.compare(a_rows, b_rows)
    assert result["shared"] == 1
    assert len(result["pairs"]) == 1
