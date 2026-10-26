"""把事件流 + 慢模型调用 + 轨迹合成**逐步泳道数据**。

每一步要给三样东西（机制视图与轨迹对照都靠它）：

- **慢模型这一趟**：原文摘要 + token + 花费 + 耗时（plan/verify 的角色与原文）；
- **快模型这一趟**：候选数、赢家、两阶段 margin、排序延迟；
- **实际发生的动作**：编译出来的可执行动作 + 本步墙钟。

**成本怎么归到步上**：`llm_calls.jsonl` 的每次调用都带 `time`，
`traj.jsonl` 的每条观察都带 `wall_time`（观察发生在动作执行之后）。
于是「一次调用属于哪一步」= 找到第一个 `wall_time >= 调用时刻` 的观察；
早于第一条观察的调用归到第 0 步，晚于全部观察的归到最后一步。

只统计慢模型调用（快模型是本地 GPU，不折美元）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 慢模型原文在泳道里显示的长度上限
TEXT_LIMIT = 700

#: 单步慢模型调用数上限（异常题可能一轮里多次重试）
MAX_CALLS_PER_STEP = 12


def _calls_by_step(episode_dir: Path, step_times: list[float]) -> list[list[dict[str, Any]]]:
    """把慢模型调用按时间窗分到各步。"""
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

    buckets: list[list[dict[str, Any]]] = [[] for _ in step_times]
    if not step_times:
        return buckets
    for call in calls:
        index = len(step_times) - 1
        for position, moment in enumerate(step_times):
            if call["time"] <= moment:
                index = position
                break
        buckets[index].append(call)
    return buckets


def _elapsed(times: list[float], index: int) -> float:
    """本步墙钟：与上一次观察的差。"""
    if index >= len(times):
        return 0.0
    current = times[index]
    previous = times[index - 1] if index > 0 else None
    if previous is None:
        return max(current - (current - 60.0), 0.0)  # 第一步没有参照，给个量级
    return max(current - previous, 0.0)


def build_timeline(
    episode_dir: Path,
    steps_detail: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    *,
    price: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """逐步泳道数据。"""
    from .traj import iter_traj

    step_times: list[float] = []
    for record in iter_traj(episode_dir):
        moment = record.get("wall_time")
        step_times.append(float(moment) if isinstance(moment, (int, float)) else 0.0)
    calls = _calls_by_step(episode_dir, step_times)

    rate_in = float((price or {}).get("input_per_1m") or 0.0)
    rate_out = float((price or {}).get("output_per_1m") or 0.0)
    rate_cached = float((price or {}).get("cached_per_1m") or 0.0)

    timeline: list[dict[str, Any]] = []
    for index, step in enumerate(steps_detail):
        step_calls = calls[index] if index < len(calls) else []
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
        ranking = step.get("ranking") or {}
        frame = next((item for item in frames if item.get("step_idx") == step.get("step")), None)
        timeline.append(
            {
                "step": step.get("step"),
                "kind": step.get("kind"),
                "slow": {
                    "calls": len(step_calls),
                    "role": step_calls[0]["role"] if step_calls else "",
                    "text": slow_text,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "reasoning_tokens": sum(call["reasoning_tokens"] for call in step_calls),
                },
                "fast": {
                    "n_candidates": step.get("n_candidates"),
                    "winner": (step.get("winner") or {}).get("operation"),
                    "operation_margin": ranking.get("operation_margin"),
                    "target_margin": ranking.get("target_margin"),
                    "latency_ms": ranking.get("latency_ms"),
                    "used_image": ranking.get("used_image"),
                },
                "action": step.get("action") or step.get("winner") or step.get("command"),
                "noop": bool(step.get("noop")),
                "outcome": (step.get("verification") or {}).get("outcome"),
                "cost_usd": round(cost, 6),
                "tokens": prompt + completion,
                "elapsed_ms": round(_elapsed(step_times, index) * 1000, 1),
                "frame": (frame or {}).get("src"),
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
