"""entry：job spec → 环境/harness/runner 组装（worker 侧唯一入口，infra/worker.sh 调用）。

M2 支持 benchmark=mock 的全链路（MockEnv + 确定性脚本组件）；osworld1/2 真实环境在 M3
接入（共享目录路径由 rjob.py 在提交侧展开并写入 spec）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tandem.components import Components
from tandem.config import SessionConfig
from tandem.selector import Ranking
from tandem.session import TandemSession

from .env import MockEnv
from .manifest import resolve_manifest
from .recorder import write_code_version
from .runner import run


def git_describe(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


class _ScriptedPlanner:
    """mock 模式的确定性 planner：先点第一个目标，再声称完成。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, instruction, screenshot, targets, recent, tree,
                 verified_focus, requirements, remaining_steps):
        self.calls += 1
        if self.calls == 1 and targets:
            target = targets[0]
            return {
                "done": False, "task_status": "running",
                "current_goal": "操作第一个控件", "expected_observation": "界面变化",
                "action_proposals": [{
                    "operation": "click", "target_id": target.id,
                    "target_name": target.name, "target_role": target.role,
                }],
            }
        return {"done": True, "task_status": "completed", "current_goal": "完成",
                "expected_observation": ""}


class _ScriptedVerifier:
    def __call__(self, instruction, screenshot, **kwargs):
        claim = kwargs.get("terminal_claim")
        status = "completed" if claim else "incomplete"
        return {
            "outcome": "achieved", "evidence": "mock 证据", "task_status": status,
            "path_input_focused": False, "state_changed": True,
            "requirement_checks": [],
        }


class _FirstCandidateSelector:
    def rank(self, **kwargs):
        candidates = kwargs["action_space"].candidates()
        winner = candidates[0] if candidates else None
        return Ranking(
            winner=winner,
            action_ranked=[{"id": winner.id, "score": 1.0}] if winner else [],
            operation_ranked=[{"operation": winner.operation, "score": 1.0}] if winner else [],
            operation_margin=0.0, target_margin=0.0, latency_ms=0.1, used_image=False,
        )


def mock_components() -> Components:
    from tandem.candidates import ActionCandidateBuilder
    from tandem.compile import gui_action
    from tandem.proposals import focused_candidates
    from tandem.targets import A11yTargetBuilder

    return Components(
        planner=_ScriptedPlanner(), verifier=_ScriptedVerifier(),
        requirements=lambda instruction: [], selector=_FirstCandidateSelector(),
        target_builder=A11yTargetBuilder(), candidate_builder=ActionCandidateBuilder(),
        focus_candidates=focused_candidates, grounder=None, compile_gui=gui_action,
    )


def build_session(spec: dict) -> TandemSession:
    config = SessionConfig(**spec.get("harness_config", {}))
    if spec.get("benchmark") == "mock":
        return TandemSession(mock_components(), config=config)
    raise NotImplementedError(
        "osworld1/2 真实环境在 M3 接入：需要共享目录路径、Kimi 凭据与 JEV endpoint"
    )


def build_env(spec: dict):
    if spec.get("benchmark") == "mock":
        base = Path(spec["output_root"]) / "mock_env"
        return MockEnv(base_dir=base)
    raise NotImplementedError("osworld1/2 DesktopEnv 适配在 M3 落地（见重构计划 M3 里程碑）")


def run_from_spec(spec: dict) -> list[dict]:
    run_root = Path(spec["output_root"])
    run_root.mkdir(parents=True, exist_ok=True)
    repo_root = Path(spec.get("repo_root", "."))
    write_code_version(
        run_root,
        {
            "git_describe": spec.get("code", {}).get("git_describe", git_describe(repo_root)),
            "resources": spec.get("code", {}).get("resources", {}),
            "images": spec.get("code", {}).get("images", {}),
            "run_spec": spec,
        },
    )
    env = build_env(spec)
    session = build_session(spec)
    tasks = resolve_manifest(spec)
    if not tasks:
        raise ValueError("manifest 解析结果为空")
    return run(spec, env=env, session=session, tasks=tasks, run_root=run_root)


def entry_main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="tandem-eval entry")
    parser.add_argument("--spec", required=True, help="job spec JSON 路径")
    args = parser.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    episodes = run_from_spec(spec)
    finished = sum(1 for item in episodes if item.get("status") == "scored")
    print(json.dumps({"done": len(episodes), "scored": finished}, ensure_ascii=False))
    return 0
