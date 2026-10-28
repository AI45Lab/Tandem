"""题号归一 + 集群路径脱敏。

**题号**：不同批次的 episode 目录命名不一致——仓库批次用 `tasks-004`，
stage+memory 批次用 `004`。站点与跨批次对比必须用同一套题号，否则 `004` 与
`tasks-004` 会被当成两道题。

**脱敏**：发布到内网共享目录前，集群挂载路径与账号名必须替换成占位符
（`demo/README.md` 的发布纪律）。VM 内的路径（如 `/home/user/Desktop/x.pptx`）
属任务语义，**保留**——那是评测对象的一部分。
"""

from __future__ import annotations

import re
from typing import Any

#: `tasks-004` / `task_004` / `tasks_004` → 去掉前缀
_TASK_PREFIX = re.compile(r"^tasks?[-_]")

#: 集群挂载路径 → `<cluster-path>/<末段文件名>`
_CLUSTER_PATH = re.compile(r"/mnt/shared-storage-(?:user|gpfs2)/[^\s\"'<>]*")

#: 账号目录段（仅在明确的集群路径上下文里替换，避免误伤任务文本）
_ACCOUNT = re.compile(r"(?<=/)[a-z][a-z0-9_-]{2,}(?=/)")


def normalize_task_id(raw: str) -> str:
    """把 episode 目录名 / 题号统一成三位数字字符串。

    >>> normalize_task_id("tasks-004")
    '004'
    >>> normalize_task_id("004")
    '004'
    >>> normalize_task_id("4")
    '004'
    """
    text = _TASK_PREFIX.sub("", str(raw).strip())
    if text.isdigit():
        return text.zfill(3)
    return text


def scrub_paths(value: Any) -> Any:
    """把集群挂载路径换成占位符（保留末段文件名，便于对照）。"""
    if isinstance(value, str):
        return _CLUSTER_PATH.sub(lambda m: "<cluster-path>/" + m.group(0).rsplit("/", 1)[-1], value)
    if isinstance(value, dict):
        return {key: scrub_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_paths(item) for item in value]
    return value


def scrub_account(value: Any) -> Any:
    """把路径里的账号目录段替换成 `<user>`（只作用于路径串，不动任务指令）。"""
    if isinstance(value, str):
        if "/" not in value or value.startswith("/home/user"):
            return value
        return _ACCOUNT.sub("<user>", value)
    if isinstance(value, dict):
        return {key: scrub_account(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_account(item) for item in value]
    return value
