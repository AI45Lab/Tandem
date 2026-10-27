"""把事件流 + 慢模型调用 + 轨迹合成**逐步泳道数据**。

**一行 = 一次观察（= 一帧 = 一次动作）**，而不是一个事件。口径来自
`docs/RESULT_DIR_CONTRACT.md`：

- 事件流按 `step` 分桶：桶 s 里有 planner / stage_local / gui|cli / action；
- **核验落在下一步骤桶**（动作步 s 的裁决取自 s+1 桶）；
- 截图索引 0 基 = **动作执行后**，与 `traj.step_idx = 截图索引 + 1` 对应；
- `traj.wall_time` 是这次观察的时刻 → 第 i 步的耗时 = `t[i] - t[i-1]`，
  第 i 步期间发生的慢模型调用 = 落在 `(t[i-1], t[i]]` 窗口里的调用。

每行给三样东西（机制泳道与轨迹对照都靠它）：

- **慢模型这一趟**：原文摘要 + token + 花费 + 耗时；
- **快模型这一趟**：候选数、赢家、两阶段 margin、排序延迟；
- **实际发生的动作**：编译出来的可执行动作 + 本步核验结论。

只统计慢模型调用（快模型是本地 GPU，不折美元）。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

#: 慢模型原文在泳道里显示的长度上限
TEXT_LIMIT = 700

#: 判定"这一步执行了什么"的路由
_ACTION_KINDS = {"gui", "cli"}
_VERIFY_KINDS = {"gui_verified", "cli_verified"}


def _calls_by_window(episode_dir: Path, times: list[float]) -> list[list[dict[str, Any]]]:
    """把慢模型调用按观察窗归位：第 i 窗 = (t[i-1], t[i]]。"""
    from .llm import iter_llm_calls

    calls: list[dict[str, Any]] = []
    for record in iter_llm_calls(episode_dir):
        usage = (record.get("response") or {}).get("usage") or record.get("usage") or {}
        message = ((record.get("response") or {}).get("choices") or [{}])[0].get("message") or {}
        calls.append(
            {
                "time": record.get("time") or 0.0,
                "role": str(record.get("role") or "unknown"),
                "attempt": record.get("attempt"),
                "text": str(message.get("content") or "")[:TEXT_LIMIT],
                "reasoning": str(message.get("reasoning_content") or "")[:TEXT_LIMIT],
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "cached_tokens": int(
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                ),
                "reasoning_tokens": int(
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
                ),
            }
        )
    calls.sort(key=lambda item: item["time"])

    windows: list[list[dict[str, Any]]] = [[] for _ in times]
    if not times:
        return windows
    for call in calls:
        index = 0
        for position, moment in enumerate(times):
            if call["time"] <= moment:
                index = position
                break
        else:
            index = len(times) - 1
        windows[index].append(call)
    return windows


def _pick(bucket: list[dict[str, Any]], kinds: set[str]) -> dict[str, Any] | None:
    for item in bucket:
        if item.get("kind") in kinds:
            return item
    return None


def build_timeline(
    episode_dir: Path,
    steps_detail: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    *,
    price: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """逐步泳道数据（一行 = 一次观察 / 一帧 / 一次动作）。"""
    from .traj import iter_traj

    times: list[float] = []
    for record in iter_traj(episode_dir):
        moment = record.get("wall_time")
        times.append(float(moment) if isinstance(moment, (int, float)) else 0.0)
    windows = _calls_by_window(episode_dir, times)

    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in steps_detail:
        number = step.get("step")
        if isinstance(number, int):
            buckets[number].append(step)

    rate_in = float((price or {}).get("input_per_1m") or 0.0)
    rate_out = float((price or {}).get("output_per_1m") or 0.0)
    rate_cached = float((price or {}).get("cached_per_1m") or 0.0)

    timeline: list[dict[str, Any]] = []
    for index in range(len(times)):
        bucket = buckets.get(index, [])
        next_bucket = buckets.get(index + 1, [])
        step_calls = windows[index] if index < len(windows) else []

        prompt = sum(call["prompt_tokens"] for call in step_calls)
        completion = sum(call["completion_tokens"] for call in step_calls)
        cached = sum(call["cached_tokens"] for call in step_calls)
        cost = (
            max(prompt - cached, 0) / 1e6 * rate_in
            + cached / 1e6 * rate_cached
            + completion / 1e6 * rate_out
        )

        slow_text = ""
        for call in step_calls:
            if call["text"].strip():
                slow_text = call["text"]
                break

        action_step = _pick(bucket, _ACTION_KINDS) or {}
        verify_step = _pick(next_bucket, _VERIFY_KINDS) or {}
        planner_step = _pick(bucket, {"planner"}) or {}
        replan_step = _pick(bucket, {"stage_replan"}) or _pick(next_bucket, {"stage_replan"}) or {}
        ranking = action_step.get("ranking") or {}
        frame = frames[index] if index < len(frames) else None
        elapsed = (times[index] - times[index - 1]) if index > 0 else 0.0

        timeline.append(
            {
                "step": index,
                "kind": action_step.get("kind") or "",
                "slow": {
                    "calls": len(step_calls),
                    "role": step_calls[0]["role"] if step_calls else "",
                    "text": slow_text,
                    "goal": planner_step.get("plan", {}).get("current_goal")
                    if isinstance(planner_step.get("plan"), dict) else None,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "reasoning_tokens": sum(call["reasoning_tokens"] for call in step_calls),
                },
                "fast": {
                    "n_candidates": action_step.get("n_candidates"),
                    "winner": (action_step.get("winner") or {}).get("operation"),
                    "operation_margin": ranking.get("operation_margin"),
                    "target_margin": ranking.get("target_margin"),
                    "latency_ms": ranking.get("latency_ms"),
                    "used_image": ranking.get("used_image"),
                },
                "action": action_step.get("action") or action_step.get("winner")
                           or action_step.get("command"),
                "noop": bool(action_step.get("noop")),
                "outcome": (verify_step.get("verification") or {}).get("outcome"),
                "replan": replan_step.get("reason"),
                "cost_usd": round(cost, 6),
                "tokens": prompt + completion,
                "elapsed_ms": round(elapsed * 1000, 1),
                "frame": (frame or {}).get("src"),
                "frame_step": (frame or {}).get("step_idx"),
            }
        )
    return timeline


def timeline_totals(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """泳道汇总：总花费 / 总耗时 / 每步均值。"""
    total_cost = sum(item.get("cost_usd") or 0.0 for item in timeline)
    total_ms = sum(item.get("elapsed_ms") or 0.0 for item in timeline)
    steps = len(timeline) or 1
    return {
        "cost_usd": round(total_cost, 6),
        "elapsed_ms": round(total_ms, 1),
        "cost_per_step_usd": round(total_cost / steps, 6),
        "elapsed_per_step_ms": round(total_ms / steps, 1),
        "steps": len(timeline),
    }
