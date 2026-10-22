"""真实时钟轨迹时间轴 + 需求章节（demo 内部用）。

与旧仓库 demo 层的"重建时钟"不同：结果目录里带真实 epoch 时间戳
（`traj.wall_time` / `llm_calls.time` / `ranking.latency_ms`），本模块据此还原
**真实时长**的时间轴——不做比例重建，也不估算任何未记录的时间。

四条泳道，全部来自实测数据：

| 泳道 | 区间 | 数据来源 |
|------|------|----------|
| `plan` | 上一步结束 → Kimi 规划调用结束 | `llm_calls[].time`（响应落盘时刻） |
| `rank` | 规划结束 → 规划结束 + 排序延迟 | `ranking.latency_ms`（服务端实测） |
| `act` | 排序结束 → 本步观察采集时刻 | `traj[].wall_time` |
| `verify` | 观察时刻 → 验证调用结束 | `llm_calls[].time` |

需求章节来自**结构化字段**（`verification.requirement_checks` + `task_requirements`
的抽取结果），逐条需求能定位到"在第几步被核验"，不做字符串模糊匹配。
"""

from __future__ import annotations

import json
from typing import Any

LANE_PLAN = "plan"
LANE_RANK = "rank"
LANE_ACT = "act"
LANE_VERIFY = "verify"

LANES = (
    (LANE_PLAN, "KIMI 规划"),
    (LANE_RANK, "排序服务"),
    (LANE_ACT, "动作与观察"),
    (LANE_VERIFY, "KIMI 验证"),
)


def parse_requirements(llm_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 `task_requirements` 调用里取回结构化需求清单。"""
    for call in llm_calls:
        if call.get("role") != "task_requirements":
            continue
        response = call.get("response") or {}
        choices = response.get("choices") or []
        if not choices:
            continue
        content = ((choices[0].get("message") or {}).get("content")) or ""
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        items = payload.get("requirements")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _call_time(call: dict[str, Any]) -> float | None:
    value = call.get("time")
    return float(value) if isinstance(value, (int, float)) else None


def attribute_calls(
    steps: list[dict[str, Any]], llm_calls: list[dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    """把 LLM 调用按事件顺序归属到步骤。

    实测调用序列恒为 `plan* → (观察) → verify → plan* → …`，故：累积 plan 调用，
    遇到 verify 时一并归给当前步，然后步号前进。一步可能有 0 次、1 次或多次 plan。
    """
    attributed: dict[int, dict[str, Any]] = {}
    index = 0
    pending_plans: list[dict[str, Any]] = []
    for call in llm_calls:
        role = call.get("role")
        if role == "task_requirements":
            continue
        if index >= len(steps):
            break
        if role == "plan_step":
            pending_plans.append(call)
            continue
        if role != "verify_observation":
            continue
        slot = attributed.setdefault(index, {"plans": [], "verify": None})
        slot["plans"] = pending_plans
        slot["verify"] = call
        pending_plans = []
        index += 1
    # 收尾：还有没等到 verify 的 plan（episode 被截断）也算在最后一步
    if pending_plans and steps:
        slot = attributed.setdefault(len(steps) - 1, {"plans": [], "verify": None})
        slot["plans"] = slot["plans"] + pending_plans
    return attributed


def build_timeline(
    steps: list[dict[str, Any]], llm_calls: list[dict[str, Any]], wall_seconds: Any = None
) -> dict[str, Any]:
    """逐步真实时间轴。"""
    attributed = attribute_calls(steps, llm_calls)
    spans: list[dict[str, Any]] = []
    cursor: float | None = None
    first_at: float | None = None
    last_at: float | None = None

    for step in steps:
        index = step.get("step", 0)
        slot = attributed.get(index) or {}
        plans = slot.get("plans") or []
        verify = slot.get("verify") or {}
        plan_times = [t for t in (_call_time(call) for call in plans) if t is not None]
        verify_time = _call_time(verify)
        # 没有 LLM 调用痕迹的步骤不画段——没有数据就不画条，不做估算
        if not plan_times and verify_time is None:
            continue
        obs_time = step.get("wall_time")
        ranking = step.get("ranking") or {}
        latency = ranking.get("latency_ms")
        latency = float(latency) if isinstance(latency, (int, float)) and latency > 0 else None
        action = step.get("action") or {}
        route = str(action.get("kind") or "").lower()
        if route not in {"gui", "cli"}:
            route = "gui" if (ranking.get("winner") or step.get("candidates")) else "cli"

        plan_end = max(plan_times) if plan_times else None
        if plan_end is None and obs_time is not None:
            plan_end = float(obs_time)
        span: dict[str, Any] = {"step": index, "route": route, "lanes": {}}

        start = cursor
        if start is None:
            start = plan_end if plan_end is not None else obs_time
        if start is None:
            continue
        if first_at is None:
            first_at = start

        if plan_end is not None and plan_end >= start:
            span["lanes"][LANE_PLAN] = [start, plan_end]
            cursor = plan_end
        rank_start = cursor
        if latency is not None:
            # 排序服务只要被调用过就画（某步可能先试 GUI 再改走 CLI）
            span["lanes"][LANE_RANK] = [rank_start, rank_start + latency / 1000.0]
            cursor = rank_start + latency / 1000.0
        if obs_time is not None and obs_time > cursor:
            span["lanes"][LANE_ACT] = [cursor, float(obs_time)]
            cursor = float(obs_time)
        if verify_time is not None and verify_time > cursor:
            span["lanes"][LANE_VERIFY] = [cursor, float(verify_time)]
            cursor = float(verify_time)

        span["plan_calls"] = len(plans)
        span["verify_call"] = bool(verify)
        span["ranking_latency_ms"] = latency
        span["at"] = round(start, 3)
        spans.append(span)
        last_at = cursor if cursor is not None else last_at

    duration = 0.0
    if first_at is not None and last_at is not None:
        duration = max(0.0, last_at - first_at)
    # 全部泳道区间归一化到"回放区间起点"，前端才能直接按百分比布局
    if first_at is not None:
        for span in spans:
            span["at"] = round(span["at"] - first_at, 3)
            for key, (start, end) in (span["lanes"] or {}).items():
                span["lanes"][key] = [round(start - first_at, 3), round(end - first_at, 3)]
    return {
        "duration": round(duration, 3),
        "wall_seconds": wall_seconds if isinstance(wall_seconds, (int, float)) else None,
        "spans": spans,
        "lanes": [{"key": key, "label": label} for key, label in LANES],
    }


def build_chapters(
    steps: list[dict[str, Any]], requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """需求 → 终态结论 + 被核验的步骤号。

    终态结论取自 `terminal.completion_check.requirement_checks`；每步的
    `verification.requirement_checks` 给出"在第几步被检查"。
    """
    order: list[str] = []
    texts: dict[str, str] = {}
    seen: set[str] = set()
    for item in requirements:
        rid = str(item.get("id") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        order.append(rid)
        texts[rid] = str(item.get("requirement") or "")

    per_requirement: dict[str, dict[str, Any]] = {}

    def touch(rid: str) -> dict[str, Any]:
        if rid not in per_requirement:
            per_requirement[rid] = {"id": rid, "steps": [], "statuses": {}, "final": None}
            if rid not in seen:
                seen.add(rid)
                order.append(rid)
        return per_requirement[rid]

    for step in steps:
        index = step.get("step", 0)
        for check in (step.get("verification") or {}).get("requirement_checks") or []:
            rid = str(check.get("id") or "")
            if not rid:
                continue
            slot = touch(rid)
            slot["steps"].append(index)
            slot["statuses"][str(index)] = str(check.get("status") or "")
    for step in steps:
        terminal = step.get("terminal") or {}
        checks = (terminal.get("completion_check") or {}).get("requirement_checks") or []
        for check in checks:
            rid = str(check.get("id") or "")
            if not rid:
                continue
            slot = touch(rid)
            slot["final"] = str(check.get("status") or "")
            slot["final_evidence"] = str(check.get("evidence") or "")

    chapters = []
    for rid in order:
        slot = per_requirement.get(rid)
        if slot is None:
            # 抽取出来但全程没被核验的需求——如实显示"未核验"，不隐藏
            chapters.append(
                {
                    "id": rid,
                    "requirement": texts.get(rid, ""),
                    "final": None,
                    "final_evidence": "",
                    "steps": [],
                    "statuses": {},
                }
            )
            continue
        chapters.append(
            {
                "id": rid,
                "requirement": texts.get(rid, ""),
                "final": slot.get("final"),
                "final_evidence": slot.get("final_evidence", ""),
                "steps": sorted(set(slot["steps"])),
                "statuses": slot["statuses"],
            }
        )
    return chapters
