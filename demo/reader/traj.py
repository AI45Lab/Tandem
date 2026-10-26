"""流式解析 traj.jsonl / a11y_digests.jsonl → 帧序列与逐步摘要。

`traj.jsonl` 每行一次观察（截图 + a11y + 预算 + 上一次回执）。
`a11y_digests.jsonl` 每行一个 a11y 摘要（含 `node_count`）——
候选空间漏斗的第一级（a11y 节点数 → 候选数 → winner）就靠它。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def iter_traj(episode_dir: Path) -> Iterator[dict[str, Any]]:
    """逐行产出 traj 记录（坏行跳过）。"""
    path = episode_dir / "traj.jsonl"
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def read_node_counts(episode_dir: Path) -> dict[int, int]:
    """step_idx → a11y 节点数。"""
    counts: dict[int, int] = {}
    path = episode_dir / "a11y_digests.jsonl"
    if not path.is_file():
        return counts
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            step = record.get("step_idx")
            count = record.get("node_count")
            if isinstance(step, int) and isinstance(count, int):
                counts[step] = count
    return counts


def read_frames(episode_dir: Path) -> list[dict[str, Any]]:
    """帧索引：截图路径 + 校验和 + a11y 节点数。

    截图本体不复制进站点数据（站点构建时另行缩放），这里只给路径与校验和。
    """
    node_counts = read_node_counts(episode_dir)
    frames: list[dict[str, Any]] = []
    for record in iter_traj(episode_dir):
        observation = record.get("observation") or {}
        screenshot = observation.get("screenshot") or {}
        tree = observation.get("accessibility_tree") or {}
        step = record.get("step_idx")
        frames.append(
            {
                "step_idx": step,
                "wall_time": record.get("wall_time"),
                "screenshot": {
                    "path": screenshot.get("path"),
                    "sha256": screenshot.get("sha256"),
                    "width": screenshot.get("width"),
                    "height": screenshot.get("height"),
                },
                "node_count": tree.get("node_count") or node_counts.get(step),
                "a11y_present": tree.get("present"),
            }
        )
    return frames


def read_budget(episode_dir: Path) -> dict[str, Any]:
    """最后一次观察里的预算快照（步数/墙钟剩余）。"""
    budget: dict[str, Any] = {}
    for record in iter_traj(episode_dir):
        observation = record.get("observation") or {}
        value = observation.get("budget")
        if isinstance(value, dict):
            budget = value
    return budget


def read_receipts(episode_dir: Path) -> dict[int, dict[str, Any]]:
    """step_idx → 上一次动作的回执（判定动作是否被环境确认）。"""
    receipts: dict[int, dict[str, Any]] = {}
    for record in iter_traj(episode_dir):
        observation = record.get("observation") or {}
        receipt = observation.get("last_receipt")
        step = record.get("step_idx")
        if isinstance(step, int) and isinstance(receipt, dict):
            receipts[step] = receipt
    return receipts
