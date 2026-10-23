"""demo 单测的合成结果目录构造器。

造的是符合 `docs/RESULT_DIR_CONTRACT.md` v0.2 的 run 目录，不依赖
`rjob_logs/` 里的真实 run（CI 上没有），也不 import `tandem` /
`tandem_eval`——demo 与 harness 完全解耦，这条边界本身就是被测项之一。
"""

from __future__ import annotations

import json
from pathlib import Path


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def usage(prompt: int, completion: int, reasoning: int = 0) -> dict:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    }


def scored(task_id: str, score: float, steps: int = 1, wall: float = 10.0) -> dict:
    """已出分的任务定义。"""
    return {"task_id": task_id, "score": score, "status": "scored", "steps": steps, "wall": wall}


def make_run(root: Path, run_id: str, tasks: list[dict]) -> Path:
    """造一个符合契约 v0.2 的 run 目录。

    tasks 每项：{"task_id", "domain", "score", "status", "steps", "wall"}。
    """
    run_dir = root / run_id
    write_json(
        run_dir / "code_version.json",
        {
            "harness_version": "0.1.0",
            "protocol_version": "0.1",
            "git_describe": "abc1234",
            "images": {"inner": "img:inner"},
            "run_spec": {
                "budget": {"max_steps": 30, "max_wall_seconds": 1800.0},
                "harness": {"name": "tandem", "mode": "planner_led",
                            "models": {"slow": "kimi-k3", "fast": "kev"}},
                "harness_config": {"fast_backend": "kev"},
            },
        },
    )
    write_json(
        run_dir / "summary.json",
        {
            "run_id": run_id,
            "benchmark": "osworld2",
            "total": len(tasks),
            "scored": sum(1 for t in tasks if t["status"] == "scored"),
            "failed_unscored": sum(1 for t in tasks if t["status"] != "scored"),
            "average_score": None,
        },
    )
    entries = []
    for task in tasks:
        task_id = task["task_id"]
        domain = task.get("domain", "tasks")
        episode_dir = run_dir / "episodes" / f"{domain}-{task_id}"
        write_json(episode_dir / "task.json", {"id": task_id, "instruction": "do it", "snapshot": "chrome"})
        write_json(
            episode_dir / "episode.json",
            {
                "task_id": task_id,
                "harness": "tandem 0.1.0",
                "stop_reason": task.get("stop_reason", "done"),
                "steps": task["steps"],
                "status": task["status"],
                "score": task.get("score"),
                "exception_type": task.get("exception_type"),
            },
        )
        write_json(episode_dir / "timing.json", {"wall_seconds": task["wall"], "status": task["status"]})
        if task.get("score") is not None:
            write_json(
                episode_dir / "evaluation.json",
                {"source": "official_benchmark_evaluator", "raw": task["score"], "score": task["score"]},
            )
        steps = task["steps"]
        events = []
        for index in range(steps):
            events.append({"step": index, "route": "planner", "plan": {"current_goal": f"goal {index}"}})
            events.append(
                {
                    "step": index,
                    "route": "gui",
                    "plan": {"current_goal": f"goal {index}"},
                    "candidates": [{"id": "click:a11y:t0:0", "operation": "click", "description": "d"}],
                    "ranking": {
                        "winner": {"id": "click:a11y:t0:0", "operation": "click"},
                        "operation_ranked": [{"operation": "click", "score": 0.9}],
                        "action_ranked": [{"id": "click:a11y:t0:0", "score": 0.8}],
                        "operation_margin": 0.5,
                        "latency_ms": 120.0,
                        "score_type": "fast_model_choice_softmax",
                        "score_is_calibrated_correctness_probability": False,
                    },
                    "action": {"kind": "gui", "action_type": "click", "parameters": {"x": 1, "y": 2}},
                }
            )
            events.append({"step": index, "kind": "action", "action": {"kind": "gui"}})
            # 验证事件落在下一步骤（契约实测语义）
            events.append(
                {
                    "step": index + 1,
                    "route": "gui_verified",
                    "execution": {"returncode": 0, "stdout": "", "stderr": "", "kind": "gui"},
                    "verification": {"outcome": "achieved", "state_changed": True, "evidence": "ok"},
                }
            )
        write_jsonl(episode_dir / "events.jsonl", events)
        write_jsonl(
            episode_dir / "traj.jsonl",
            [
                {
                    "step_idx": index + 1,
                    "wall_time": 1000.0 + index,
                    "observation": {
                        "budget": {"steps_remaining": 30 - index},
                        "last_receipt": {"returncode": 0, "stdout": "", "stderr": "", "kind": "gui"},
                    },
                    "action": {"kind": "gui", "action_type": "click"},
                }
                for index in range(steps)
            ],
        )
        write_jsonl(
            episode_dir / "llm_calls.jsonl",
            [
                {
                    "role": "task_requirements",
                    "time": 1.0,
                    "attempt": 1,
                    "request": {"payload": {"messages": [{"role": "system", "content": "sys"}]}},
                    "response": {"usage": usage(10, 20, 5)},
                },
                {
                    "role": "plan_step",
                    "time": 2.0,
                    "attempt": 1,
                    "request": {"payload": {"messages": [{"role": "user", "content": "u"}]}},
                    "response": {"usage": usage(100, 200, 50)},
                },
            ],
        )
        shots = episode_dir / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        for index in range(steps):
            (shots / f"step_{index:02d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        entries.append({"task_id": task_id, "domain": domain, "episode_dir": f"{domain}-{task_id}"})
    write_json(
        run_dir / "episodes" / "manifest.resolved.json",
        {"run_id": run_id, "benchmark": "osworld2", "count": len(entries), "tasks": entries},
    )
    return run_dir
