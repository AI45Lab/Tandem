"""entry：job spec → 环境/harness/runner 组装（worker 侧唯一入口，infra/worker.sh 调用）。

benchmark=mock：MockEnv + 确定性脚本组件（全链路自检）。
benchmark=osworld1/2：OsWorldEnv（共享目录 runtime/VM）+ KimiClient + build_default 组件，
凭据与端点路径由 rjob.py 在提交侧从环境档案注入 spec（secrets 段）。
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


class LlmTap:
    """逐题重定向的 llm_sink：runner 每题把 current 指向该 episode 的 recorder。"""

    def __init__(self):
        self.current = None

    def __call__(self, **kwargs):
        if self.current is not None:
            self.current(**kwargs)


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


def build_session(spec: dict, *, llm_tap: LlmTap | None = None) -> TandemSession:
    config = SessionConfig(**spec.get("harness_config", {}))
    benchmark = spec.get("benchmark")
    if benchmark == "mock":
        return TandemSession(mock_components(), config=config)
    if benchmark in {"osworld1", "osworld2"}:
        from tandem.components import build_default
        from tandem.providers import KimiClient

        secrets = spec["secrets"]
        credentials = dict(secrets["kimi"])
        credentials.setdefault("model", "kimi-k3")
        backend = getattr(config, "selector_backend", "jev")
        endpoint_key = "kev_endpoint" if backend == "kev" else "jev_endpoint"
        if not secrets.get(endpoint_key):
            raise ValueError(f"selector_backend={backend} 需要 spec.secrets.{endpoint_key}")
        run_root = Path(spec["output_root"])
        run_root.mkdir(parents=True, exist_ok=True)
        client = KimiClient(credentials, config, run_root / "kimi_http.jsonl", llm_sink=llm_tap)
        jev = spec.get("jev") or {}
        image_stage = None
        if jev.get("image_stage_write") and jev.get("image_stage_read"):
            image_stage = (jev["image_stage_write"], jev["image_stage_read"])
        components = build_default(
            client=client, endpoint=secrets[endpoint_key], config=config,
            image_stage=image_stage,
        )
        return TandemSession(components, config=config)
    raise NotImplementedError(f"未知 benchmark: {benchmark}")


def build_env(spec: dict):
    benchmark = spec.get("benchmark")
    if benchmark == "mock":
        base = Path(spec["output_root"]) / "mock_env"
        return MockEnv(base_dir=base)
    if benchmark in {"osworld1", "osworld2"}:
        from .osworld import OsWorldEnv

        env_spec = spec["env"]
        return OsWorldEnv(
            benchmark=benchmark,
            task_root=Path(env_spec["root"]),
            vm_path=Path(env_spec["vm"]),
            run_root=Path(spec["output_root"]),
            asset_root=Path(env_spec["asset_root"]) if env_spec.get("asset_root") else None,
            setup_cache_root=Path(env_spec["setup_cache_root"]) if env_spec.get("setup_cache_root") else None,
            startup_wait_seconds=float(env_spec.get("startup_wait_seconds", 30.0)),
        )
    raise NotImplementedError(f"未知 benchmark: {benchmark}")


def _mask_secrets(spec: dict) -> dict:
    """run_spec 落盘前脱敏：secrets 段的值全部打码（密钥/registry 凭据不进结果目录）。"""
    masked = json.loads(json.dumps(spec, ensure_ascii=False))
    secrets = masked.get("secrets")
    if isinstance(secrets, dict):
        masked["secrets"] = {
            key: {subkey: "***" for subkey in value} if isinstance(value, dict) else "***"
            for key, value in secrets.items()
        }
    return masked


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
            "run_spec": _mask_secrets(spec),
        },
    )
    llm_tap = LlmTap()
    env = build_env(spec)
    session = build_session(spec, llm_tap=llm_tap)
    tasks = resolve_manifest(spec)
    if not tasks:
        raise ValueError("manifest 解析结果为空")
    return run(spec, env=env, session=session, tasks=tasks, run_root=run_root, llm_tap=llm_tap)


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
