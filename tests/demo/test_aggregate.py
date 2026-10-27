"""demo 聚合层单测：**数字必须与 `tools/batch_summary.py` 同源**。

这是整个 demo 最重要的一条测试：站点显示的每一批数字都由 `tools/batch_summary.py`
算出来，demo 只做「题号归一 + Sai 对照列」。如果两边分叉，站点就会开始说谎。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from helpers import make_contract_episode as make_episode  # noqa: E402
from helpers import make_contract_run as make_run  # noqa: E402

from demo.reader.aggregate import (  # noqa: E402
    build_overview,
    collect_merged_rows,
    collect_rows,
    compare_rows,
    compare_summary,
    load_official,
)
from tools.batch_summary import collect_rows as tools_collect_rows  # noqa: E402
from tools.batch_summary import summarize as tools_summarize  # noqa: E402

DATA_DIR = REPO_ROOT / "demo" / "data"


def test_demo_rows_match_tools_rows(tmp_path):
    """同一个 runs-root：demo 的逐题行与 tools 的逐题行逐位一致（题号归一除外）。"""
    run_dir = make_run(tmp_path)
    make_episode(run_dir, task_dir="tasks-025", score=None, stop="exception", steps=0)
    demo_rows = collect_rows(tmp_path)
    tool_rows = tools_collect_rows(tmp_path)
    assert len(demo_rows) == len(tool_rows) == 2
    for demo_row, tool_row in zip(demo_rows, tool_rows, strict=True):
        assert demo_row["score"] == tool_row["score"]
        assert demo_row["status"] == tool_row["status"]
        assert demo_row["stop"] == tool_row["stop"]
        assert demo_row["steps"] == tool_row["steps"]
        assert demo_row["calls"] == tool_row["calls"]
        assert demo_row["prompt_tokens"] == tool_row["prompt_tokens"]
        assert demo_row["completion_tokens"] == tool_row["completion_tokens"]
        assert demo_row["cached_tokens"] == tool_row["cached_tokens"]
        assert demo_row["noop_rate"] == tool_row["noop_rate"]
    assert {row["task"] for row in demo_rows} == {"004", "025"}


def test_overview_numbers_match_tools_summary(tmp_path):
    make_run(tmp_path)
    rows = collect_rows(tmp_path)
    stats = tools_summarize(rows)
    overview = build_overview(rows, data_dir=DATA_DIR)
    ours = overview["ours"]
    assert ours["attempted"] == stats["total"]
    assert ours["scored"] == stats["scored"]
    assert ours["partial_scored"] == stats["average_scored"]
    assert ours["partial_attempted"] == stats["average_all"]
    assert ours["binary"] == stats["full_hits"]
    assert ours["prompt_tokens"] == stats["prompt_tokens"]
    assert ours["completion_tokens"] == stats["completion_tokens"]
    assert ours["wall_seconds"] == stats["wall_seconds"]


def test_overview_has_no_predicted_scores(tmp_path):
    """红线 2：站点不生成我们的预测分/目标分。"""
    make_run(tmp_path)
    overview = build_overview(collect_rows(tmp_path), data_dir=DATA_DIR)
    blob = json.dumps(overview, ensure_ascii=False).lower()
    for forbidden in ("predicted", "forecast", "target_score", "预期分", "预计分"):
        assert forbidden not in blob


def test_sai_anchor_matches_leaderboard():
    """口径锚点：Sai per-task best 均值必须等于官方榜上那行的 partial。

    官方榜 `Sai w/ Claude Opus 5`（v2.1）的 partial 79.38 = HF 参考 run
    「每题最佳干净运行」的均值 0.7938 —— 对不上就说明 vendored 数据串了。
    """
    official = load_official(DATA_DIR)
    sai = official["sai_meta"]
    assert sai["tasks_total"] == 108
    assert sai["headline"]["mean_of_task_best"] == 0.7938
    sai_rows = [
        row for row in official["leaderboard"]["results"]
        if str(row.get("modelType")) == "agent" and str(row.get("releaseVersion")) == "v2.1"
        and "Sai" in str(row.get("model"))
    ]
    assert len(sai_rows) == 1
    assert round(sai_rows[0]["partialScore"] / 100, 4) == sai["headline"]["mean_of_task_best"]


def test_official_harness_rows_are_exposed():
    overview = build_overview([], data_dir=DATA_DIR)
    harness = overview["official"]["harness"]
    assert any("Sai" in row["model"] for row in harness)
    sai = next(row for row in harness if "Sai" in row["model"])
    assert sai["binary_accuracy"] == 41.67
    assert sai["partial_score"] == 79.38
    assert sai["cost_per_task_usd"] == 14.34
    # e2e 行只作背景
    assert all(row["model_type"] == "e2e" for row in overview["official"]["e2e_background"])


def test_compare_rows_delta_and_tie(tmp_path):
    make_run(tmp_path)
    rows = collect_rows(tmp_path)
    sai_tasks = {"004": {"best": 0.8, "mean": 0.8, "runs": 1}}
    subset = {"groups": {"接近但落后": ["004"]}}
    compared = compare_rows(rows, sai_tasks, subset)
    row = compared[0]
    assert row["task"] == "004"
    assert row["ours"] == 0.6556
    assert row["sai_best"] == 0.8
    assert row["delta"] == 0.1444
    assert row["tie"] is False
    assert row["group"] == "接近但落后"


def test_compare_rows_marks_tie_and_missing(tmp_path):
    make_run(tmp_path)
    rows = collect_rows(tmp_path)
    sai_tasks = {"004": {"best": 0.6556, "mean": 0.6556, "runs": 1}}
    compared = compare_rows(rows, sai_tasks)
    assert compared[0]["tie"] is True
    assert compared[0]["delta"] == 0.0
    # Sai 没跑的题 → delta 为 None（不折算 0）
    assert compare_rows(rows, {})[0]["delta"] is None


def test_unscored_sai_full_counts_float_tail_as_full(tmp_path):
    """官方评测器是加权求和，会出现 0.9999999999999999 这种浮点尾差——它就是满分。

    075 的 Sai 最佳分正是这个值；用严格 `>= 1.0` 会把一个满分漏掉，
    低估"基础设施失败吃掉了多少分"。
    """
    run_dir = make_run(tmp_path)
    make_episode(run_dir, task_dir="tasks-025", score=None, stop="exception", steps=0)
    rows = collect_rows(tmp_path)
    overview = build_overview(rows, data_dir=DATA_DIR)
    sai_tasks = {"025": {"best": 0.9999999999999999, "mean": 1.0, "runs": 1}}
    summary = compare_summary(rows, sai_tasks, overview)
    assert summary["ours_unscored"] == 1
    assert summary["unscored_sai_full"] == 1


def test_compare_rows_carry_run_id(tmp_path):
    """逐题行要带 run_id：站点按 run 寻址逐题数据，缺了就拼出 undefined 路径。"""
    make_run(tmp_path)
    rows = collect_rows(tmp_path)
    sai_tasks = {"004": {"best": 0.8, "mean": 0.8, "runs": 1}}
    compared = compare_summary(rows, sai_tasks, build_overview(rows, data_dir=DATA_DIR))
    assert compared["rows"][0]["run_id"], "对照行必须带 run_id"
    assert compared["rows"][0]["run_id"].startswith("osw21-run-")


def test_merged_selection_matches_env_manifest(tmp_path):
    """demo 的合并口径必须与环境侧的 merged_progress 逐题一致。

    清单是环境侧写明的合并规则（同题取已出分的那次、recheck 用新的替换），
    demo 用同一套 `_row_rank` 去重——两边对不上就说明有一处口径漂了。
    """
    import json
    from pathlib import Path

    manifest_path = REPO_ROOT / "demo" / "data" / "merged_manifest.json"
    if not manifest_path.is_file():
        pytest.skip("还没有合并清单（先跑 demo/sync_merged.py）")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roots = [Path(p) for p in (manifest.get("batch_roots") or {}).values()]
    roots = [root for root in roots if root.is_dir()]
    if not roots:
        pytest.skip("批次目录不在本机")

    # 只关心「选哪次尝试」，token 数字与此无关 → stub 掉重 I/O，测试跑得快
    import tools.batch_summary as bs

    original = bs._episode_tokens
    bs._episode_tokens = lambda episode_dir: (0, 0, 0, 0)
    try:
        rows = collect_merged_rows(roots, manifest)
    finally:
        bs._episode_tokens = original
    mine = {row["task"]: row for row in rows}
    for task_id, item in (manifest.get("tasks") or {}).items():
        row = mine.get(task_id)
        assert row is not None, f"清单里的 {task_id} 在 demo 聚合里没有"
        assert row["run_id"] == item["run_id"], (
            f"{task_id}: 选错了 run —— demo={row['run_id']} 清单={item['run_id']}"
        )
        assert row["score"] == item["score"], f"{task_id}: 分数与清单不一致"
