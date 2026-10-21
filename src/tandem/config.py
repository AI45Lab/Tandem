"""harness 侧会话配置。环境生命周期/预算强制/落盘配置属于 tandem_eval（M2），不在此处。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionConfig:
    allow_cli: bool = True
    route_policy: str = "auto"
    cli_timeout_seconds: int = 90
    jev_timeout_seconds: float = 300
    kimi_max_tokens: int = 8192
    kimi_timeout_seconds: float = 120
    kimi_direct_api: bool = False
    selector_backend: str = "jev"  # "jev"（qwen-jev-choice /rank）| "kev"（Kev System One）

    def __post_init__(self):
        if self.route_policy not in {"auto", "gui", "cli"}:
            raise ValueError("route_policy must be auto, gui or cli")
        if not 1 <= self.cli_timeout_seconds <= 120:
            raise ValueError("cli_timeout_seconds must be within 1..120 (协议上限)")
        if self.selector_backend not in {"jev", "kev"}:
            raise ValueError("selector_backend must be jev or kev")
