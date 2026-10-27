"""逐题行 → 站点的总览与对照数据。

**唯一实现原则**：逐题行直接委托 `tools/batch_summary.py`（团队已认可的聚合实现，
空转口径 2026-10-25 修正过）。demo 侧**只加两样东西**：

1. **题号归一**（`tasks-004` / `004` → `004`），否则跨批次会把同一题当两道；
2. **Sai 对照列**（同 release、同原生评测器的官方 harness 逐题分）。

这样站点的数字与 `tools/fill_baseline.py` 生成的报告**逐位一致**——
一致性测试（`tests/demo/test_aggregate.py`）守着这条线。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.batch_summary import _row_rank  # noqa: E402  跨批次去重口径，全站只此一份
from tools.batch_summary import collect_rows as _collect_rows  # noqa: E402
from tools.batch_summary import summarize as _summarize  # noqa: E402

from .paths import normalize_task_id  # noqa: E402

#: 满分判定容差（官方评测器加权求和的浮点尾差）
FULL_SCORE_TOLERANCE = 1.0 - 1e-6

#: 官方榜里作为背景展示的 e2e 行（v2.1，同步数预算）
BACKGROUND_E2E = ("Claude Opus 5", "GPT-5.6 Sol", "MuseSpark 1.3")


def collect_rows(runs_root: Path, prefix: str = "") -> list[dict[str, Any]]:
    """逐题行（委托 tools + 题号归一）。"""
    rows = _collect_rows(Path(runs_root), prefix)
    for row in rows:
        row["task"] = normalize_task_id(row.get("task") or "")
        # tools 给的键是 "run"，站点要按 run 寻址逐题数据 → 补一个 run_id
        row["run_id"] = row.get("run") or ""
    return rows


def load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_merged_rows(
    roots: list[Path], selection: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """跨多个批次根目录收集逐题行（c10 + c20 合成 OSW v2.1 全量）。

    `selection` 是合并基线清单（题号 → run_id）。**给了清单就按清单挑 run**——
    清单是环境侧写明的合并规则（同题取已出分的那次、recheck 用新的替换），
    逐题核对过磁盘，直接照它走，口径零漂移。

    没给清单时回退到 `tools/batch_summary._row_rank`（已出分优先 → 批次时间戳晚）。
    """
    rows: list[dict[str, Any]] = []
    for root in roots:
        rows.extend(_collect_rows(Path(root)))
    for row in rows:
        row["task"] = normalize_task_id(row.get("task") or "")
        row["run_id"] = row.get("run") or ""
    if selection:
        wanted = selection.get("tasks") or {}
        picked: list[dict[str, Any]] = []
        for task_id, item in wanted.items():
            match = next(
                (row for row in rows
                 if row["task"] == task_id and row["run_id"] == item.get("run_id")),
                None,
            )
            if match is not None:
                picked.append(match)
        return sorted(picked, key=lambda row: row["task"])
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = best.get(row["task"])
        if current is None or _row_rank(row) > _row_rank(current):
            best[row["task"]] = row
    return sorted(best.values(), key=lambda row: row["task"])


def load_official(data_dir: Path) -> dict[str, Any]:
    """官方数据快照：榜 + Sai 逐题 + 对比子集。"""
    leaderboard = load_json(data_dir / "official" / "leaderboard.json") or {}
    sai_tasks = load_json(data_dir / "official" / "sai_tasks.json") or {}
    subset = load_json(data_dir / "official" / "compare_subset.json") or {}
    prices = load_json(data_dir / "prices.json") or {}
    return {
        "leaderboard": leaderboard,
        "sai_tasks": sai_tasks.get("tasks") or {},
        "sai_meta": {k: v for k, v in sai_tasks.items() if k != "tasks"},
        "subset": subset,
        "prices": prices,
    }


def _price_for(prices: dict[str, Any], model_key: str) -> dict[str, Any] | None:
    """按角色名取价格条目（`prices.json` 的 `models.<name>`）。"""
    models = prices.get("models") or {}
    entry = models.get(model_key)
    if not isinstance(entry, dict):
        return None
    return {
        "model": entry.get("model") or model_key,
        "input_per_1m": entry.get("input_per_1m"),
        "output_per_1m": entry.get("output_per_1m"),
        "cached_per_1m": entry.get("cached_per_1m") or 0.0,
        "snapshot": entry.get("snapshot"),
        "source_url": entry.get("source_url"),
    }


def _official_rows(leaderboard: dict[str, Any], release: str = "v2.1") -> dict[str, list[dict[str, Any]]]:
    """从榜快照里挑出 harness 行与 e2e 背景行。"""
    harness: list[dict[str, Any]] = []
    background: list[dict[str, Any]] = []
    for row in leaderboard.get("results") or []:
        if str(row.get("releaseVersion")) != release:
            continue
        if str(row.get("datasetScope")) not in {"full", "None"}:
            continue
        item = {
            "model": row.get("model"),
            "model_type": row.get("modelType"),
            "reasoning": row.get("reasoning"),
            "step_budget": row.get("stepBudget"),
            "binary_accuracy": row.get("binaryAccuracy"),
            "partial_score": row.get("partialScore"),
            "cost_per_task_usd": row.get("costPerTaskUsd"),
            "estimated_cost_usd": row.get("estimatedCostUsd"),
            "output_tokens_per_task": row.get("outputTokensPerTask"),
        }
        if str(row.get("modelType")) == "agent":
            harness.append(item)
        elif str(row.get("model")) in BACKGROUND_E2E:
            background.append(item)
    harness.sort(key=lambda item: -(item["partial_score"] or 0))
    return {"harness": harness, "e2e_background": background}


def build_overview(
    rows: list[dict[str, Any]],
    *,
    data_dir: Path,
    dataset_size: int = 108,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    """站点总览：我们的成绩 + 官方参照 + 逐题行。

    两个 partial 口径都给：
    - `partial_over_dataset`：108 题分母、未出分计 0 —— **与官方榜可比**（官方就是这么算的）；
    - `partial_scored`：只算有分的题 —— 反映"真做出来时"的水平。
    """
    official = load_official(data_dir)
    prices = official["prices"]
    price = _price_for(prices, "slow_model")
    stats = _summarize(rows)
    scores = [score for score in stats["scores"] if isinstance(score, (int, float))]

    prompt = sum(row.get("prompt_tokens") or 0 for row in rows)
    completion = sum(row.get("completion_tokens") or 0 for row in rows)
    cached = sum(row.get("cached_tokens") or 0 for row in rows)
    total_tokens = prompt + completion
    usd = None
    if price:
        fresh_input = max(prompt - cached, 0)
        usd = (
            fresh_input / 1e6 * float(price.get("input_per_1m") or 0.0)
            + cached / 1e6 * float(price.get("cached_per_1m") or 0.0)
            + completion / 1e6 * float(price.get("output_per_1m") or 0.0)
        )

    # attempted = 有结果的题 + 明确没跑出结果的题（= 我们实际覆盖的题数）
    missing = missing or []
    scored = stats["scored"]
    attempted = len(rows) + len(missing)
    # 停止原因里可能有整段 infeasible 理由（几百字）→ 归到「其它」，
    # 免得它在分布图里变成一个巨大的 key
    stops: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("stop") or "")
        key = reason if len(reason) <= 40 else "其它（规划判定不可行）"
        stops[key] = stops.get(key, 0) + 1
    return {
        "ours": {
            "attempted": attempted,
            "scored": scored,
            "unscored": attempted - scored,
            "missing": missing,
            "partial_scored": stats["average_scored"],
            "partial_attempted": (sum(scores) / scored) if scored else None,
            "partial_over_dataset": (sum(scores) / dataset_size) if dataset_size else None,
            "binary": stats["full_hits"],
            "binary_rate_attempted": (stats["full_hits"] / attempted) if attempted else None,
            "full_hits": stats["full_hits"],
            "partial_hits": stats["partial_hits"],
            "zeros": stats["zeros"],
            "calls": stats["calls"],
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_tokens": cached,
            "total_tokens": total_tokens,
            "usd_estimate": round(usd, 4) if usd is not None else None,
            "usd_per_task": round(usd / attempted, 4) if usd is not None and attempted else None,
            "price": price,
            "wall_seconds": stats["wall_seconds"],
            "stop_reasons": stops,
            "env_failed": len(stats["env_failed"]),
            "judge_infra": len(stats["judge_infra"]),
            "model_failed": len(stats["model_failed"]),
        },
        "official": {
            "release": "v2.1",
            "dataset_size": dataset_size,
            "harness": _official_rows(official["leaderboard"])["harness"],
            "e2e_background": _official_rows(official["leaderboard"])["e2e_background"],
            "snapshot": official["leaderboard"].get("fetched_at"),
            "source_url": official["leaderboard"].get("source_url"),
        },
        "sai": official["sai_meta"],
        "rows": rows,
    }


def compare_rows(
    rows: list[dict[str, Any]],
    sai_tasks: dict[str, Any],
    subset: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """逐题对照：我们 vs Sai（同一题、同一 release、同一原生评测器）。"""
    groups = (subset or {}).get("groups") or {}
    out: list[dict[str, Any]] = []
    for row in rows:
        task = row.get("task") or ""
        sai = sai_tasks.get(task) or {}
        best = sai.get("best")
        mean = sai.get("mean")
        score = row.get("score")
        delta = None
        if isinstance(score, (int, float)) and isinstance(best, (int, float)):
            delta = round(best - score, 4)
        out.append(
            {
                "task": task,
                "run_id": row.get("run_id") or "",
                "ours": score,
                "ours_status": row.get("status"),
                "ours_stop": row.get("stop"),
                "ours_steps": row.get("steps"),
                "ours_wall": row.get("wall_seconds"),
                "ours_noop_rate": row.get("noop_rate"),
                "ours_tokens": (row.get("prompt_tokens") or 0) + (row.get("completion_tokens") or 0),
                "sai_best": best,
                "sai_mean": mean,
                "sai_runs": sai.get("runs"),
                "delta": delta,
                "tie": delta is not None and abs(delta) < 0.01,
                "group": _group_of(groups, task),
            }
        )
    out.sort(key=lambda item: item["task"])
    return out


def _group_of(groups: dict[str, Any], task: str) -> str:
    for name, tasks in groups.items():
        if task in (tasks or []):
            return name
    return ""


def compare_summary(
    rows: list[dict[str, Any]],
    sai_tasks: dict[str, Any],
    overview: dict[str, Any],
    *,
    subset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对照视图需要的汇总数字（逐题 Δ 的聚合）。

    口径：
    - `common_scored`：我们与 Sai 都有分的题（**只在这批题上比**，避免分母被稀释）；
    - `we_lead` 如实计数（我们从未领先，页面要显示 0 而不是藏起来）；
    - `unscored_sai_full`：我们未出分、但 Sai 拿满分的题数 —— 基础设施失败的代价。
    """
    compared = compare_rows(rows, sai_tasks, subset)
    # 两批都没跑出结果的题也要进对照行（ours=None）——否则"未出分且官方拿满分"
    # 这类披露会漏掉它们（075 的 Sai 分是 0.9999999999999999，其实就是满分）
    known = {row["task"] for row in compared}
    for task_id in (overview.get("ours") or {}).get("missing") or []:
        if task_id in known:
            continue
        sai = sai_tasks.get(task_id) or {}
        compared.append({
            "task": task_id,
            "run_id": "",
            "ours": None,
            "ours_status": "missing",
            "ours_stop": "",
            "ours_steps": 0,
            "ours_wall": None,
            "ours_noop_rate": None,
            "ours_tokens": 0,
            "sai_best": sai.get("best"),
            "sai_mean": sai.get("mean"),
            "sai_runs": sai.get("runs"),
            "delta": None,
            "tie": False,
            "group": "",
        })
    compared.sort(key=lambda item: item["task"])
    common = [
        row for row in compared
        if row["ours"] is not None and row["sai_best"] is not None
    ]
    ours_mean = sum(row["ours"] for row in common) / len(common) if common else None
    sai_mean = sum(row["sai_best"] for row in common) / len(common) if common else None
    ties = sum(1 for row in common if row["tie"])
    we_lead = sum(1 for row in common if row["ours"] > row["sai_best"] + 0.01)
    ours = overview.get("ours") or {}
    harness = overview.get("official", {}).get("harness") or []
    sai_row = next((row for row in harness if "Sai" in str(row.get("model"))), {})
    sai_cost = sai_row.get("cost_per_task_usd")
    ours_cost = ours.get("usd_per_task")
    ratio = None
    if ours_cost and sai_cost:
        ratio = round(sai_cost / ours_cost, 1)
    # 满分容差：官方评测器是加权求和，会出现 0.9999999999999999 这种浮点尾差，
    # 与真正的 1.00 是同一件事（075 就是这种）。用容差判定，别让尾差吃掉一个满分。
    unscored_sai_full_tasks = [
        row["task"] for row in compared
        if row["ours"] is None and row["sai_best"] is not None
        and row["sai_best"] >= FULL_SCORE_TOLERANCE
    ]
    unscored_sai_full = len(unscored_sai_full_tasks)
    return {
        "rows": compared,
        "common_scored": len(common),
        "ours_mean": round(ours_mean, 4) if ours_mean is not None else None,
        "sai_mean_best": round(sai_mean, 4) if sai_mean is not None else None,
        "ties": ties,
        "we_lead": we_lead,
        "ours_attempted": ours.get("attempted"),
        "ours_unscored": ours.get("unscored"),
        "unscored_sai_full": unscored_sai_full,
        "unscored_sai_full_tasks": unscored_sai_full_tasks,
        "ours_usd_per_task": ours_cost,
        "sai_usd_per_task": sai_cost,
        "cost_ratio": ratio,
        "sai_meta": overview.get("sai"),
        "official": overview.get("official"),
        "groups": (subset or {}).get("groups") or {},
        "groups_note": (subset or {}).get("groups_note") or {},
    }
