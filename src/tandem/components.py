"""组件契约（依赖注入边界，无插件框架、无隐藏分发）。
在旧九组件上增加 semantic_enricher，统一 slow planner 与 fast selector 看到的元素语义。
grounder（visual fallback）默认 None，session 侧判空跳过。compile_gui 产出协议动作。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from .config import SessionConfig
from .gui.candidates import ActionCandidateBuilder
from .gui.compile import gui_action
from .gui.proposals import focused_candidates
from .gui.semantics import enrich_targets
from .gui.targets import A11yTargetBuilder
from .models.jev import JevOmniPolicy
from .planning.planner import plan_step
from .planning.stage_planner import plan_stage
from .verification.verifier import task_requirements, verify_observation


@dataclass
class Components:
    planner: Callable
    verifier: Callable
    requirements: Callable
    selector: object
    target_builder: object
    semantic_enricher: Callable
    candidate_builder: object
    focus_candidates: Callable
    grounder: Callable | None
    compile_gui: Callable


def build_default(*, client, endpoint: str, config: SessionConfig,
                  image_stage: tuple[str, str] | None = None, endpoint_provider=None) -> Components:
    if config.fast_backend == "kev":
        from .models.kev import KevPolicy

        selector = KevPolicy(endpoint, timeout_seconds=config.fast_timeout_seconds)
    else:
        selector = JevOmniPolicy(endpoint, timeout_seconds=config.fast_timeout_seconds,
                                 image_stage=image_stage, endpoint_provider=endpoint_provider)
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
        semantic_enricher=enrich_targets,
        candidate_builder=ActionCandidateBuilder(),
        focus_candidates=focused_candidates,
        grounder=None,
        compile_gui=gui_action,
    )
