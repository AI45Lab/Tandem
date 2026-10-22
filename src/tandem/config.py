"""harness 侧会话配置。环境生命周期/预算强制/落盘配置属于 tandem_eval（M2），不在此处。

字段按**角色**命名，不按厂商命名：`slow_*` 是大脑（慢模型）的旋钮，
`fast_*` 是小脑（快模型排序后端）的旋钮。换厂商只换配置里的 API 条目，
不改这里，也不改状态机。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionConfig:
    allow_cli: bool = True
    route_policy: str = "auto"
    cli_timeout_seconds: int = 90
    slow_max_tokens: int = 16384
    slow_timeout_seconds: float = 120
    slow_direct_api: bool = False
    slow_reasoning_effort: str = "low"  # off=enable_thinking:false | low/medium/high=reasoning_effort
    fast_backend: str = "jev"  # "jev"（qwen-jev-choice /rank）| "kev"（Kev System One）
    fast_timeout_seconds: float = 300

    def __post_init__(self):
        if self.route_policy not in {"auto", "gui", "cli"}:
            raise ValueError("route_policy must be auto, gui or cli")
        if not 1 <= self.cli_timeout_seconds <= 120:
            raise ValueError("cli_timeout_seconds must be within 1..120 (协议上限)")
        if self.fast_backend not in {"jev", "kev"}:
            raise ValueError("fast_backend must be jev or kev")
        if self.slow_reasoning_effort not in {"off", "low", "medium", "high"}:
            raise ValueError("slow_reasoning_effort must be off/low/medium/high")
