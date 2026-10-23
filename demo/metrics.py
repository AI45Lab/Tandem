"""成本 / 耗时 / 准确率的聚合层（demo 内部用）。

与 `adapter` 分开是为了守住"单模块 ≤300 行"的纪律：
adapter 只负责**读**，metrics 只负责**算**。

准确率口径：均分只对 `scored` 的题求平均；`failed_unscored` 单独计数，
不折算 0 分、不进均分（契约 §failed_unscored 纪律）。
"""

from __future__ import annotations

from typing import Any

#: 成本口径字段（token 用量 + 调用次数，不换算货币单价）
COST_KEYS = ("calls", "prompt_tokens", "completion_tokens", "reasoning_tokens")


def llm_cost(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """按 role 聚合 token 用量与调用次数。"""
    total = {key: 0 for key in COST_KEYS}
    by_role: dict[str, dict[str, int]] = {}
    for call in calls:
        role = str(call.get("role") or "unknown")
        usage = (call.get("response") or {}).get("usage") or {}
        bucket = by_role.setdefault(role, {key: 0 for key in COST_KEYS})
        bucket["calls"] += 1
        total["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)):
                bucket[key] += int(value)
                total[key] += int(value)
        details = usage.get("completion_tokens_details") or {}
        reasoning = details.get("reasoning_tokens")
        if isinstance(reasoning, (int, float)):
            bucket["reasoning_tokens"] += int(reasoning)
            total["reasoning_tokens"] += int(reasoning)
    return {"total": total, "by_role": by_role}


def aggregate(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """run 级聚合：准确率 / 时间 / 成本 / 失败分类。"""
    scored = [t for t in tasks if t["scored"] and t["score"] is not None]
    walls = [t["wall_seconds"] for t in tasks if isinstance(t["wall_seconds"], (int, float))]
    cost_total = {key: 0 for key in COST_KEYS}
    fast_calls = 0
    for task in tasks:
        for key in COST_KEYS:
            cost_total[key] += task["cost"]["total"].get(key, 0)
        fast_calls += task.get("fast_calls", 0)
    failures: dict[str, int] = {}
    for task in tasks:
        if not task["scored"]:
            key = str(task.get("exception_type") or task.get("stop_reason") or "unknown")
            failures[key] = failures.get(key, 0) + 1
    return {
        "total": len(tasks),
        "scored": len(scored),
        "failed_unscored": len(tasks) - len(scored),
        "average_score": round(sum(t["score"] for t in scored) / len(scored), 4) if scored else None,
        "perfect": sum(1 for t in scored if t["score"] == 1),
        "zero": sum(1 for t in scored if t["score"] == 0),
        "wall_seconds_total": round(sum(walls), 2),
        "wall_seconds_mean_scored": (
            round(sum(t["wall_seconds"] for t in scored) / len(scored), 2) if scored else None
        ),
        "cost": cost_total,
        "fast_calls": fast_calls,
        "failures": failures,
    }


def build_comparison(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """多 run → 对比文档：按 task_id 横向对齐各 run 的成本/耗时/准确率。"""
    by_task: dict[str, dict[str, Any]] = {}
    for run in runs:
        for task in run["tasks"]:
            slot = by_task.setdefault(task["task_id"], {"task_id": task["task_id"], "runs": {}})
            slot["runs"][run["run_id"]] = {
                "status": task["status"],
                "score": task["score"],
                "scored": task["scored"],
                "stop_reason": task["stop_reason"],
                "exception_type": task["exception_type"],
                "wall_seconds": task["wall_seconds"],
                "steps": len(task["steps"]),
                "tokens": (
                    task["cost"]["total"]["prompt_tokens"] + task["cost"]["total"]["completion_tokens"]
                ),
                "llm_calls": task["cost"]["total"]["calls"],
                "fast_calls": task["fast_calls"],
            }
    return {
        "runs": [
            {
                "run_id": run["run_id"],
                "benchmark": run["benchmark"],
                "git_describe": run["git_describe"],
                "fast_model": run["fast_model"],
                "budget": run["budget"],
                "totals": run["totals"],
            }
            for run in runs
        ],
        "tasks": [by_task[key] for key in sorted(by_task)],
    }
