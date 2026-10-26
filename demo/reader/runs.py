"""run 级读取：发现 run 目录、读 run 级元数据。

run 目录契约（`docs/RESULT_DIR_CONTRACT.md`）：
`summary.json` / `heartbeat.json` / `code_version.json` / `episodes/<task>/…`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunInfo:
    """一个 run（= 一次提交的一组题）。"""

    run_id: str
    path: Path
    benchmark: str = ""
    harness: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    scored: int = 0
    failed_unscored: int = 0
    average_score: float | None = None
    code_version: str | None = None
    inner_image: str | None = None
    has_summary: bool = False

    @property
    def episodes_dir(self) -> Path:
        return self.path / "episodes"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "benchmark": self.benchmark,
            "harness": self.harness,
            "total": self.total,
            "scored": self.scored,
            "failed_unscored": self.failed_unscored,
            "average_score": self.average_score,
            "code_version": self.code_version,
            "inner_image": self.inner_image,
        }


def read_json(path: Path) -> Any:
    """读单个 JSON；不存在或坏行返回 None（契约允许文件缺失）。"""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def discover_runs(runs_root: Path, benchmark: str | None = None) -> list[RunInfo]:
    """扫 `runs_root/*/summary.json`，返回 run 列表（按 run_id 排序）。

    `benchmark` 过滤按 `summary.json.benchmark` 判；没有 summary 的目录
    （被中途停掉的 run）也会被收进来，但 `has_summary=False`——
    站点要能显示"这个 run 跑到一半被停了"，而不是当作不存在。
    """
    if not runs_root.is_dir():
        return []
    runs: list[RunInfo] = []
    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        summary = read_json(run_dir / "summary.json")
        code_version = read_json(run_dir / "code_version.json") or {}
        info = RunInfo(
            run_id=run_dir.name,
            path=run_dir,
            benchmark=str((summary or {}).get("benchmark") or ""),
            harness=dict((summary or {}).get("harness") or {}),
            total=int((summary or {}).get("total") or 0),
            scored=int((summary or {}).get("scored") or 0),
            failed_unscored=int((summary or {}).get("failed_unscored") or 0),
            average_score=(summary or {}).get("average_score"),
            code_version=code_version.get("git_describe"),
            inner_image=((code_version.get("images") or {}) or {}).get("inner"),
            has_summary=summary is not None,
        )
        if benchmark and info.benchmark and info.benchmark != benchmark:
            continue
        runs.append(info)
    return runs


def run_episode_dirs(run: RunInfo) -> list[Path]:
    """run 下的 episode 目录（按题号排序）。"""
    if not run.episodes_dir.is_dir():
        return []
    return sorted(p for p in run.episodes_dir.iterdir() if p.is_dir())
