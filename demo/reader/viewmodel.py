"""把读取层拼成**站点唯一数据契约**（episode view model）。

契约形状见 `docs/DEMO_REDESIGN.md` §4.2。站点、导出器、实时 API 三个出口
都只认这个形状——换数据源时只改 reader，不动前端。

单题目标 ≤300KB：慢模型原文每题 ≤8 条 × ≤4KB，候选只留前 20 个。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .episodes import EpisodeRef
from .events import build_steps, noop_stats, rank_stats, steps_from_events
from .llm import read_llm_errors, read_llm_texts, read_llm_usage
from .paths import scrub_paths
from .steps import build_timeline, timeline_totals
from .traj import read_budget, read_frames

#: 没有价格表时的兜底：只报 token，不报美元（红线 3：没有价格就不许出现美元数）
NO_PRICE = {"snapshot": None, "usd_estimate": None}


def estimate_usd(usage_total: dict[str, Any], price: dict[str, Any] | None) -> dict[str, Any]:
    """按价格表估算美元成本。

    `price` 形如 `{"input_per_1m": 0.15, "output_per_1m": 0.60, "cached_per_1m": 0.015,
    "model": "...", "snapshot": "2026-10-23"}`。缺表 → 不出美元数。
    """
    if not price:
        return dict(NO_PRICE)
    prompt = int(usage_total.get("prompt_tokens") or 0)
    cached = int(usage_total.get("cached_tokens") or 0)
    completion = int(usage_total.get("completion_tokens") or 0)
    fresh_input = max(prompt - cached, 0)
    usd = (
        fresh_input / 1e6 * float(price.get("input_per_1m") or 0.0)
        + cached / 1e6 * float(price.get("cached_per_1m") or 0.0)
        + completion / 1e6 * float(price.get("output_per_1m") or 0.0)
    )
    return {
        "usd_estimate": round(usd, 6),
        "snapshot": price.get("snapshot"),
        "model": price.get("model"),
    }


def build_view_model(
    ref: EpisodeRef,
    *,
    price: dict[str, Any] | None = None,
    sai: dict[str, Any] | None = None,
    include_text: bool = True,
    max_candidates_note: str = "",
) -> dict[str, Any]:
    """一道题的 view model。"""
    episode_dir = ref.dir
    steps = build_steps(episode_dir)
    usage = read_llm_usage(episode_dir)
    usage_total = usage["total"]
    noop = noop_stats(episode_dir)
    fast = rank_stats(episode_dir)

    real_steps = ref.steps if ref.steps > 0 else steps_from_events(episode_dir)
    frames = read_frames(episode_dir)
    texts = read_llm_texts(episode_dir) if include_text else []
    errors = read_llm_errors(episode_dir)

    model: dict[str, Any] = {
        "task_id": ref.task_id,
        "run_id": ref.run_id,
        "status": ref.status,
        "score": ref.score,
        "stop_reason": ref.stop_reason,
        "steps": real_steps,
        "wall_seconds": ref.wall_seconds,
        "domain": ref.domain,
        "instruction": ref.instruction,
        "noop_rate": noop["noop_rate"],
        "decisions": noop["decisions"],
        "noop_decisions": noop["noop"],
        "evaluator": {
            "source": ref.evaluator_source,
            "raw": ref.evaluator_raw,
            "native": ref.native_evaluator,
        },
        "tokens": {
            "prompt": usage_total["prompt_tokens"],
            "completion": usage_total["completion_tokens"],
            "cached": usage_total["cached_tokens"],
            "reasoning": usage_total["reasoning_tokens"],
            "calls": usage_total["calls"],
            "by_role": usage["by_role"],
        },
        "fast_model": fast,
        "steps_detail": steps,
        "llm_texts": texts,
        "llm_errors": errors,
        "replans": [s for s in steps if s.get("kind") == "stage_replan"],
        "requirements": _requirements(steps),
        "frames": frames,
        "budget": read_budget(episode_dir),
        "error": ref.error,
        "exception_type": ref.exception_type,
    }
    model["tokens"].update(estimate_usd(usage_total, price))
    # 逐步泳道：慢模型原文/成本/耗时 + 快模型排序 + 实际动作
    model["timeline"] = build_timeline(episode_dir, steps, frames, price=price)
    model["timeline_totals"] = timeline_totals(model["timeline"])
    if sai:
        model["sai"] = sai
    if max_candidates_note:
        model["note"] = max_candidates_note
    return scrub_paths(model)


def _requirements(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """需求核验清单：把各次 verify 的 requirement_checks 合并去重。

    同一需求在多次核验里可能反复出现，这里保留**最后一次**状态与证据。
    """
    merged: dict[str, dict[str, Any]] = {}
    for step in steps:
        verification = step.get("verification") or {}
        for check in verification.get("requirement_checks") or []:
            if not isinstance(check, dict):
                continue
            key = str(check.get("id") or check.get("name") or "")
            if not key:
                continue
            merged[key] = {
                "id": key,
                "status": check.get("status"),
                "evidence": check.get("evidence"),
                "step": step.get("step"),
            }
    return list(merged.values())


def frame_source(run_id: str, task_id: str, step_idx: int | None) -> str:
    """站点内帧的相对路径（构建时生成缩放帧到 `assets/frames/<run>/<task>/`）。"""
    name = f"step_{int(step_idx):02d}.jpg" if isinstance(step_idx, int) else "step_00.jpg"
    return f"assets/frames/{run_id}/{task_id}/{name}"


def attach_frame_paths(model: dict[str, Any]) -> dict[str, Any]:
    """给 view model 的帧补上站点内相对路径。"""
    run_id = model.get("run_id") or ""
    task_id = model.get("task_id") or ""
    for frame in model.get("frames") or []:
        frame["src"] = frame_source(run_id, task_id, frame.get("step_idx"))
    return model


def source_dir_hint(path: Path) -> str:
    """源目录的可读提示（发布前脱敏用）。"""
    return scrub_paths(str(path))
