"""组件契约（依赖注入边界，无插件框架、无隐藏分发）。
九个字段名与旧仓库 components.py 保持一致；唯一差异：grounder（visual fallback）
按重构计划 §3.1 延后，默认 None，session 侧判空跳过。compile_gui 现在产出协议动作。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from .candidates import ActionCandidateBuilder
from .compile import gui_action
from .config import SessionConfig
from .planner import plan_step
from .proposals import focused_candidates
from .selector import JevOmniPolicy
from .stage_planner import plan_stage
from .targets import A11yTargetBuilder
from .verifier import task_requirements, verify_observation


@dataclass
class Components:
    planner: Callable
    verifier: Callable
    requirements: Callable
    selector: object
    target_builder: object
    candidate_builder: object
    focus_candidates: Callable
    grounder: Callable | None
    compile_gui: Callable


def build_default(*, client, endpoint: str, config: SessionConfig,
                  image_stage: tuple[str, str] | None = None) -> Components:
    if config.fast_backend == "kev":
        from .selector_kev import KevPolicy

        selector = KevPolicy(endpoint, timeout_seconds=config.fast_timeout_seconds)
    else:
        selector = JevOmniPolicy(endpoint, timeout_seconds=config.fast_timeout_seconds,
                                 image_stage=image_stage)
    return Components(
        planner=partial(
            plan_stage if config.execution_mode == "stage" else plan_step,
            client,
            allow_cli=config.allow_cli and config.route_policy != "gui",
            route_policy=config.route_policy,
        ),
        verifier=partial(verify_observation, client),
        requirements=partial(task_requirements, client),
        selector=selector,
        target_builder=A11yTargetBuilder(),
        candidate_builder=ActionCandidateBuilder(),
        focus_candidates=focused_candidates,
        grounder=None,
        compile_gui=gui_action,
    )
