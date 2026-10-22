"""结果目录 → demo 文档（只读 `rjob_logs/<run_id>/`）。

唯一数据来源是 `docs/RESULT_DIR_CONTRACT.md` v0.2 描述的结果目录契约：
本模块不 import `tandem` / `tandem_eval`，不调用模型，不碰 VM。

三条硬纪律（继承旧仓库 demo 层的诚实披露要求）：

1. 只搬运**模型公开输出**，不生成任何虚构的"思考字幕"；
2. `failed_unscored` 永远显示为"未出分"，不折算成 0 分、不进均分；
3. JEV `/rank` 分数一律标注 "softmax，非校准概率"。

成本一律用 **token 用量 + 调用次数** 表达（成本代理指标）——本仓库没有 Kimi
计价信息，demo 不臆造货币单价。

聚合口径在 `metrics.py`，HTML 渲染在 `render.py`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from metrics import aggregate, llm_cost
from timeline import build_chapters, build_timeline, parse_requirements

CONTRACT_VERSION = "v0.2"

#: 集群挂载路径（/mnt/…）含账号与目录结构，公开前一律替换；VM 内的
#: /home/user/… 是任务语义，保留。
_CLUSTER_PATH = re.compile(r"/mnt/[A-Za-z0-9._/-]+")


def scrub_paths(value: Any) -> Any:
    """把集群挂载路径换成占位符（保留末段文件名，便于对照）。"""
    if isinstance(value, str):
        return _CLUSTER_PATH.sub(lambda m: "<cluster-path>/" + m.group(0).rsplit("/", 1)[-1], value)
    if isinstance(value, dict):
        return {key: scrub_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_paths(item) for item in value]
    return value


def read_json(path: Path) -> Any:
    """读单个 JSON 文件；不存在返回 None（契约允许文件缺失）。"""
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读 JSONL；不存在返回空列表。"""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _ranking_summary(ranking: dict[str, Any]) -> dict[str, Any]:
    """压缩 ranking 事件：保留两阶段请求全文 + 每选项分数 + margin + 延迟。"""
    if not isinstance(ranking, dict):
        return {}
    return {
        "winner": ranking.get("winner"),
        "operation_ranked": ranking.get("operation_ranked") or [],
        "action_ranked": ranking.get("action_ranked") or [],
        "operation_margin": ranking.get("operation_margin"),
        "target_margin": ranking.get("target_margin"),
        "latency_ms": ranking.get("latency_ms"),
        "used_image": ranking.get("used_image"),
        "score_type": ranking.get("score_type"),
        "score_is_calibrated_correctness_probability": ranking.get(
            "score_is_calibrated_correctness_probability"
        ),
        "operation_request": ranking.get("operation_request"),
        "action_request": ranking.get("action_request"),
    }


def build_steps(episode_dir: Path) -> list[dict[str, Any]]:
    """把 events.jsonl 与 traj.jsonl 合成逐步视图。

    步号模型（实测自真实 run，并经 a11y_digests 交叉验证）：
    - `events.step` 从 0 起，与 `screenshots/step_NN.png` 的 N 同源——`recorder.screenshot(steps_used, …)`
      在动作**执行后**落盘，故 `step_NN.png` 是**动作 N 之后**的屏幕；
    - `traj.step_idx` 从 1 起，`traj.step_idx = N+1` 与 `step_NN.png` 是同一次观察
      （a11y_digests 的 step_idx=N 与 traj step_idx=N+1 的 digest 完全一致）；
    - 因此动作步 s 的"执行后"帧是 `step_{s:02d}.png`、"执行前"帧是 `step_{s-1:02d}.png`；
      第 0 步没有"执行前"帧（初始观察只在 obs_stage，结束即清）。
    - 验证事件（`gui_verified` / `cli_verified`）在动作之后的下一步骤落盘，故动作
      步 s 的裁决取自 s+1 桶。
    """
    events = read_jsonl(episode_dir / "events.jsonl")
    traj = {row.get("step_idx"): row for row in read_jsonl(episode_dir / "traj.jsonl")}
    frames = sorted(p.name for p in (episode_dir / "screenshots").glob("step_*.png"))

    grouped: dict[int, dict[str, Any]] = {}
    for event in events:
        step = event.get("step")
        if not isinstance(step, int):
            continue
        route = event.get("route") or event.get("kind")
        grouped.setdefault(step, {})[str(route)] = event

    steps: list[dict[str, Any]] = []
    for step in sorted(grouped):
        bucket = grouped[step]
        # 只有"动作步"才成步：纯验证桶（动作的下一步落盘）不单独成步，
        # 它是对上一步动作的裁决。
        if not any(route in bucket for route in ("action", "gui", "cli")):
            continue
        planner = bucket.get("planner") or {}
        gui = bucket.get("gui") or {}
        cli = bucket.get("cli") or {}
        # 验证事件在动作**之后**的下一步骤落盘（实测：step 0 的 gui 动作，其
        # gui_verified 记在 step 1），所以动作步 s 的裁决取自 s+1 桶。
        next_bucket = grouped.get(step + 1, {})
        verified = next_bucket.get("gui_verified") or next_bucket.get("cli_verified") or {}
        action = gui.get("action") or cli.get("action") or bucket.get("action") or {}
        row = traj.get(step + 1) or {}
        observation = row.get("observation") or {}
        receipt = observation.get("last_receipt") or {}
        steps.append(
            {
                "step": step,
                "plan": planner.get("plan") or gui.get("plan") or cli.get("plan") or {},
                "candidates": gui.get("candidates") or [],
                "blocked_action": gui.get("blocked_action"),
                "ranking": _ranking_summary(gui.get("ranking") or {}),
                "action": action,
                "verification": verified.get("verification") or {},
                "control_state_check": verified.get("control_state_check"),
                "execution": verified.get("execution") or {},
                "terminal": bucket.get("terminal") or {},
                "receipt": receipt,
                "budget": observation.get("budget") or {},
                "a11y": {
                    key: value
                    for key, value in (observation.get("accessibility_tree") or {}).items()
                    if key != "path"  # 本地 a11y 文件路径无分析价值，且含集群挂载信息
                },
                "before_frame": (
                    f"step_{step - 1:02d}.png"
                    if step >= 1 and f"step_{step - 1:02d}.png" in frames
                    else None
                ),
                "after_frame": f"step_{step:02d}.png" if f"step_{step:02d}.png" in frames else None,
                "wall_time": row.get("wall_time"),
            }
        )
    return steps


def _first_message(call: dict[str, Any], role: str) -> str:
    """取一条请求消息的文本（payload 或 messages 任一形态）。"""
    payload = call.get("request") or {}
    for source in (payload.get("messages"), payload.get("payload", {}).get("messages")):
        if not isinstance(source, list):
            continue
        for message in source:
            if isinstance(message, dict) and message.get("role") == role:
                content = message.get("content")
                if isinstance(content, str):
                    return content
    return ""


def load_episode(run_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """单个 episode 目录 → 任务文档。"""
    episode_dir = run_dir / "episodes" / str(entry.get("episode_dir") or entry.get("task_id"))
    task = read_json(episode_dir / "task.json") or {}
    episode = read_json(episode_dir / "episode.json") or {}
    timing = read_json(episode_dir / "timing.json") or {}
    evaluation = read_json(episode_dir / "evaluation.json") or {}
    calls = read_jsonl(episode_dir / "llm_calls.jsonl")

    steps = build_steps(episode_dir)
    ranking_latency = [
        step["ranking"].get("latency_ms") for step in steps
    ]
    ranking_latency = [v for v in ranking_latency if isinstance(v, (int, float))]

    cost = llm_cost(calls)
    status = str(episode.get("status") or timing.get("status") or "unknown")
    score = episode.get("score")
    if score is None:
        score = evaluation.get("score")
    requirements = parse_requirements(calls)
    timeline = build_timeline(steps, calls, timing.get("wall_seconds"))
    chapters = build_chapters(steps, requirements)

    return scrub_paths(
        {
            "task_id": str(entry.get("task_id") or episode.get("task_id") or task.get("id") or ""),
            "domain": str(entry.get("domain") or task.get("domain") or ""),
            "episode_dir": episode_dir.name,
            "instruction": str(task.get("instruction") or ""),
            "snapshot": str(task.get("snapshot") or ""),
            "status": status,
            "scored": status == "scored",
            "score": score if isinstance(score, (int, float)) else None,
            "stop_reason": episode.get("stop_reason"),
            "exception_type": episode.get("exception_type"),
            "steps_reported": episode.get("steps"),
            "wall_seconds": timing.get("wall_seconds"),
            "evaluation": evaluation,
            "cost": cost,
            "jev_calls": len(ranking_latency),
            "jev_latency_ms_total": round(sum(ranking_latency), 2),
            "steps": steps,
            "requirements": requirements,
            "timeline": timeline,
            "chapters": chapters,
            "frames": sorted(p.name for p in (episode_dir / "screenshots").glob("step_*.png")),
            "llm_calls": [
                {
                    "role": call.get("role"),
                    "time": call.get("time"),
                    "attempt": call.get("attempt"),
                    "usage": (call.get("response") or {}).get("usage") or {},
                    "system": _first_message(call, "system"),
                    "user": _first_message(call, "user"),
                    "assistant": _first_message(call, "assistant"),
                }
                for call in calls
            ],
        }
    )


def load_run(run_dir: Path) -> dict[str, Any]:
    """一个 run 目录 → run 文档（含逐题列表）。"""
    run_dir = Path(run_dir)
    code_version = read_json(run_dir / "code_version.json") or {}
    summary = read_json(run_dir / "summary.json") or {}
    manifest = read_json(run_dir / "episodes" / "manifest.resolved.json") or {}
    run_spec = code_version.get("run_spec") or {}
    harness_config = run_spec.get("harness_config") or {}

    entries = manifest.get("tasks")
    if not isinstance(entries, list):
        entries = [
            {"task_id": p.name.rsplit("-", 1)[-1], "domain": "", "episode_dir": p.name}
            for p in sorted((run_dir / "episodes").glob("*/"))
            if (p / "episode.json").is_file()
        ]

    tasks = [load_episode(run_dir, entry) for entry in entries]
    return {
        "run_id": summary.get("run_id") or run_dir.name,
        "benchmark": summary.get("benchmark") or manifest.get("benchmark") or "",
        "harness_version": code_version.get("harness_version"),
        "protocol_version": code_version.get("protocol_version"),
        "git_describe": code_version.get("git_describe"),
        "images": code_version.get("images") or {},
        "selector_backend": harness_config.get("selector_backend", "jev"),
        "budget": run_spec.get("budget") or {},
        "summary": {
            "total": summary.get("total", len(tasks)),
            "scored": summary.get("scored"),
            "failed_unscored": summary.get("failed_unscored"),
            "average_score": summary.get("average_score"),
        },
        "tasks": tasks,
        "totals": aggregate(tasks),
    }
