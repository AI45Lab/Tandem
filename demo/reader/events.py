"""流式解析 events.jsonl → 站点步骤序列。

`events.jsonl` 是 harness 的事件流，route 取值见 `docs/RESULT_DIR_CONTRACT.md`：
`planner` / `cli` / `gui` / `cli_verified` / `gui_verified` / `terminal` / `done_probe` /
`stage_local` / `stage_progress` / `stage_replan`，外加 runner 写的 `{"kind": "action"}`。

**空转口径与 `tools/batch_summary._noop_rate` 完全一致**：判空转看的是
「动作有没有编译出来」（`gui` 事件里 `action` 为 null），不是「winner 是不是回退项」。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

#: 候选与排序明细的保留条数（站点要看得清，又不能把 2.4MB 事件流整份塞进页面）
MAX_CANDIDATES = 20
MAX_RANKED = 12

#: 步骤里保留的文本长度上限
MAX_TEXT = 1200


def iter_events(episode_dir: Path) -> Iterator[dict[str, Any]]:
    """逐行产出事件（坏行跳过）。"""
    path = episode_dir / "events.jsonl"
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def event_kind(record: dict[str, Any]) -> str:
    """事件的归一化类型：`route` 优先，其次 runner 写的 `kind`。"""
    route = record.get("route")
    if isinstance(route, str) and route:
        return route
    kind = record.get("kind")
    return str(kind) if isinstance(kind, str) and kind else "unknown"


def read_events(episode_dir: Path) -> list[dict[str, Any]]:
    """全部事件（仅用于小文件与测试；站点走 `build_steps`）。"""
    return list(iter_events(episode_dir))


def _trim_text(value: Any, limit: int = MAX_TEXT) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def _trim_plan(plan: Any) -> Any:
    """计划里只留站点要展示的字段（milestones 里的命令可能很长）。"""
    if not isinstance(plan, dict):
        return plan
    milestones = plan.get("milestones")
    trimmed = {
        key: plan.get(key)
        for key in ("stage_goal", "current_goal", "expected_observation", "route", "task_status", "done")
        if key in plan
    }
    if isinstance(milestones, list):
        trimmed["milestones"] = [
            {
                "route": item.get("route"),
                "current_goal": _trim_text(item.get("current_goal")),
                "command": _trim_text(item.get("command"), 400),
            }
            for item in milestones
            if isinstance(item, dict)
        ]
    return trimmed


def _trim_ranking(ranking: Any) -> Any:
    if not isinstance(ranking, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("operation_margin", "target_margin", "latency_ms", "used_image", "winner_id"):
        if key in ranking:
            out[key] = ranking[key]
    for key in ("operation_ranked", "target_ranked", "action_ranked"):
        ranked = ranking.get(key)
        if isinstance(ranked, list):
            out[key] = ranked[:MAX_RANKED]
    request = ranking.get("operation_request") or ranking.get("target_request")
    if isinstance(request, dict):
        keep = ("operation", "target", "operation_options")
        out["request"] = {k: v for k, v in request.items() if k in keep}
    return out


def build_steps(episode_dir: Path) -> list[dict[str, Any]]:
    """把事件流整形成站点要的步骤序列。"""
    steps: list[dict[str, Any]] = []
    for record in iter_events(episode_dir):
        kind = event_kind(record)
        step_no = record.get("step")
        step: dict[str, Any] = {
            "step": step_no if isinstance(step_no, int) else len(steps),
            "kind": kind,
        }
        if kind == "planner":
            step["plan"] = _trim_plan(record.get("plan"))
        elif kind == "stage_local":
            step["stage_goal"] = _trim_text(record.get("stage_goal"))
            step["milestone"] = record.get("milestone")
            step["route"] = record.get("route")
        elif kind == "stage_progress":
            step["stage_goal"] = _trim_text(record.get("stage_goal"))
            step["milestone"] = record.get("milestone")
            step["source"] = record.get("source")
        elif kind == "stage_replan":
            step["reason"] = record.get("reason")
            step["stage_goal"] = _trim_text(record.get("stage_goal"))
            step["milestone"] = record.get("milestone")
        elif kind == "gui":
            candidates = record.get("candidates") or []
            step["candidates"] = [
                {
                    "id": item.get("id"),
                    "operation": item.get("operation"),
                    "description": _trim_text(item.get("description"), 200),
                    "target_id": item.get("target_id"),
                    "source": item.get("source"),
                    "semantic_key": (item.get("metadata") or {}).get("semantic_key"),
                }
                for item in candidates[:MAX_CANDIDATES]
                if isinstance(item, dict)
            ]
            step["n_candidates"] = len(candidates)
            step["ranking"] = _trim_ranking(record.get("ranking"))
            step["winner"] = record.get("winner")
            step["action"] = record.get("action")
            step["blocked_action"] = record.get("blocked_action")
            step["noop"] = record.get("action") is None
        elif kind == "cli":
            step["command"] = _trim_text(record.get("command"), 2000)
            step["action"] = record.get("action")
        elif kind in {"gui_verified", "cli_verified"}:
            verification = record.get("verification") or {}
            step["verification"] = {
                "outcome": verification.get("outcome"),
                "evidence": _trim_text(verification.get("evidence")),
                "state_changed": verification.get("state_changed"),
                "requirement_checks": verification.get("requirement_checks") or [],
            }
            step["execution"] = record.get("execution")
        elif kind == "terminal":
            step["planner"] = _trim_plan(record.get("planner"))
            step["completion_check"] = record.get("completion_check")
        elif kind == "action":
            step["action"] = record.get("action")
        steps.append(step)
    return steps


def noop_stats(episode_dir: Path) -> dict[str, Any]:
    """空转口径（与 `tools/batch_summary._noop_rate` 一致）。"""
    total = noop = 0
    for record in iter_events(episode_dir):
        if record.get("route") != "gui" or not record.get("winner"):
            continue
        total += 1
        if record.get("action") is None:
            noop += 1
    return {"decisions": total, "noop": noop, "noop_rate": (noop / total) if total else None}


def rank_stats(episode_dir: Path) -> dict[str, Any]:
    """快模型排序侧的统计：调用次数与总耗时（毫秒）。

    快模型是本地 GPU 服务，**不折美元**——这里只给"多少次、多慢"。
    """
    calls = 0
    latency_total = 0.0
    for record in iter_events(episode_dir):
        if record.get("route") != "gui":
            continue
        ranking = record.get("ranking")
        if not isinstance(ranking, dict):
            continue
        calls += 1
        latency = ranking.get("latency_ms")
        if isinstance(latency, (int, float)):
            latency_total += float(latency)
    return {"rank_calls": calls, "rank_ms_total": round(latency_total, 1)}


def steps_from_events(episode_dir: Path) -> int:
    """从事件流回补真实步数（异常路径下 episode.json 的 steps 可能是 0）。"""
    last = 0
    for record in iter_events(episode_dir):
        step = record.get("step")
        if isinstance(step, int) and step > last:
            last = step
    return last
