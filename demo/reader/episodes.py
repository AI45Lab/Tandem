"""题级读取：episode 终态（分数 / 停止原因 / 评测来源 / 用时 / 域）。

分数有两个来源，必须区分：
- `episode.json` 的 `score` —— 评测器给出的浮点分（未出分时为 `null`）；
- `evaluation.json` 的 `source` —— 评测器身份。
  `official_benchmark_evaluator` = 原生官方评测器（可与官方榜同口径比）；
  其它来源（如 LLM judge）**不能**直接与官方榜比，站点必须显式标注。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import normalize_task_id
from .runs import read_json


@dataclass
class EpisodeRef:
    """一道题的落盘结果。"""

    run_id: str
    task_id: str
    dir: Path
    score: float | None = None
    status: str = ""
    stop_reason: str = ""
    steps: int = 0
    exception_type: str | None = None
    error: str = ""
    wall_seconds: float | None = None
    evaluator_source: str | None = None
    evaluator_raw: float | None = None
    domain: str = ""
    instruction: str = ""

    @property
    def scored(self) -> bool:
        return self.score is not None

    @property
    def native_evaluator(self) -> bool:
        """是否用原生官方评测器（可与官方榜同口径比）。"""
        return self.evaluator_source == "official_benchmark_evaluator"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "score": self.score,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "steps": self.steps,
            "exception_type": self.exception_type,
            "error": self.error,
            "wall_seconds": self.wall_seconds,
            "evaluator": {
                "source": self.evaluator_source,
                "raw": self.evaluator_raw,
                "native": self.native_evaluator,
            },
            "domain": self.domain,
        }


def list_episodes(run_id: str, episodes_dir: Path) -> list[EpisodeRef]:
    """列出 run 下所有题（含未出分与被中断的）。"""
    if not episodes_dir.is_dir():
        return []
    refs: list[EpisodeRef] = []
    for episode_dir in sorted(p for p in episodes_dir.iterdir() if p.is_dir()):
        episode = read_json(episode_dir / "episode.json")
        if not isinstance(episode, dict):
            continue
        evaluation = read_json(episode_dir / "evaluation.json") or {}
        timing = read_json(episode_dir / "timing.json") or {}
        task = read_json(episode_dir / "task.json") or {}
        raw = evaluation.get("raw")
        refs.append(
            EpisodeRef(
                run_id=run_id,
                task_id=normalize_task_id(episode_dir.name),
                dir=episode_dir,
                score=episode.get("score"),
                status=str(episode.get("status") or ""),
                stop_reason=str(episode.get("stop_reason") or ""),
                steps=int(episode.get("steps") or 0),
                exception_type=episode.get("exception_type"),
                error=str(episode.get("error") or ""),
                wall_seconds=timing.get("wall_seconds"),
                evaluator_source=evaluation.get("source"),
                evaluator_raw=raw if isinstance(raw, (int, float)) else None,
                domain=domain_of(str(task.get("instruction") or "")),
                instruction=str(task.get("instruction") or ""),
            )
        )
    return refs


def read_episode_meta(episode_dir: Path) -> dict[str, Any]:
    """题级元数据（薄封装，给 view model 用）。"""
    episode = read_json(episode_dir / "episode.json") or {}
    evaluation = read_json(episode_dir / "evaluation.json") or {}
    return {
        "score": episode.get("score"),
        "status": episode.get("status"),
        "stop_reason": episode.get("stop_reason"),
        "steps": episode.get("steps"),
        "exception_type": episode.get("exception_type"),
        "error": episode.get("error"),
        "evaluator": {
            "source": evaluation.get("source"),
            "raw": evaluation.get("raw"),
        },
    }


#: 指令关键词 → 域（与 `tools/batch_summary.domain_of` 同口径）
_DOMAIN_RULES: tuple[tuple[str, str], ...] = (
    ("thunderbird", "email_client"),
    ("libreoffice writer", "libreoffice_writer"),
    ("libreoffice calc", "libreoffice_calc"),
    ("libreoffice impress", "libreoffice_impress"),
    ("powerpoint", "libreoffice_impress"),
    ("gimp", "gimp_image"),
    ("photoshop", "gimp_image"),
    ("vlc", "media_player"),
    ("video", "video_editor"),
    ("kdenlive", "video_editor"),
    ("chrome", "browser_web"),
    ("browser", "browser_web"),
    ("firefox", "browser_web"),
    ("vscode", "vscode_ide"),
    ("visual studio code", "vscode_ide"),
    ("settings", "system_settings"),
)


def domain_of(instruction: str) -> str:
    """按指令文本猜应用域（判不出来归 `other`）。

    与 `tools/batch_summary.domain_of` 同一套关键词，站点与分诊报告的域分布才对得上。
    """
    lowered = instruction.lower()
    for keyword, domain in _DOMAIN_RULES:
        if keyword in lowered:
            return domain
    return "other"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读 JSONL（跳过坏行）。仅用于小文件。"""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows
