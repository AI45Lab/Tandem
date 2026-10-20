"""任务清单：OSW1 用共享目录 test_nogdrive.json（361 题），OSW2 用 test_v2.json（108 题），
或显式 id 列表 / repo 内清单文件。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskRef:
    task_id: str
    domain: str = ""


def load_index(index_path: str | Path) -> list[TaskRef]:
    """读 {domain: [task_id]} 索引（OSW1/OSW2 共享目录格式）或 [task_id] / [{id,...}] 列表。"""
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    refs: list[TaskRef] = []
    if isinstance(data, dict):
        for domain, task_ids in data.items():
            if not isinstance(task_ids, list):
                continue
            for task_id in task_ids:
                refs.append(TaskRef(task_id=str(task_id), domain=domain))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                refs.append(TaskRef(task_id=item))
            elif isinstance(item, dict) and item.get("id"):
                refs.append(TaskRef(task_id=str(item["id"]), domain=str(item.get("domain", ""))))
    return refs


def resolve_manifest(spec: dict) -> list[TaskRef]:
    """job spec 的 manifest 段 → 任务列表。三种形态：
    {"source": "osworld1"|"osworld2", "limit"?: n}（共享目录索引，路径由调用方注入）
    {"tasks": ["id", ...]}（显式列表）
    {"path": "/abs/or/repo/relative.json"}（清单文件）
    """
    manifest = spec.get("manifest") or {}
    benchmark = spec.get("benchmark", "mock")
    if "tasks" in manifest:
        refs = [TaskRef(task_id=str(task)) for task in manifest["tasks"]]
    elif "path" in manifest:
        path = Path(manifest["path"])
        if not path.is_absolute():
            path = Path(spec["repo_root"]) / path
        refs = load_index(path)
    elif benchmark in {"osworld1", "osworld2"} and spec.get("index_root"):
        index = Path(spec["index_root"]) / (
            "osworld1/evaluation_examples/test_nogdrive.json"
            if benchmark == "osworld1"
            else "osworld2/evaluation_examples/test_v2.json"
        )
        refs = load_index(index)
    elif benchmark == "mock":
        refs = [TaskRef(task_id=f"mock-{i:03d}", domain="mock") for i in range(1)]
    else:
        raise ValueError(f"无法解析 manifest：benchmark={benchmark} 且未提供 index_root/tasks/path")
    limit = manifest.get("limit")
    if isinstance(limit, int) and limit > 0:
        refs = refs[:limit]
    return refs


def write_resolved(run_root: Path, refs: list[TaskRef], spec: dict) -> None:
    (run_root / "episodes").mkdir(parents=True, exist_ok=True)
    (run_root / "episodes" / "manifest.resolved.json").write_text(
        json.dumps(
            {
                "run_id": spec.get("run_id"),
                "benchmark": spec.get("benchmark"),
                "count": len(refs),
                "tasks": [
                    (
                        {"task_id": ref.task_id, "domain": ref.domain,
                         "episode_dir": f"{ref.domain}-{ref.task_id}"}
                        if ref.domain
                        else {"task_id": ref.task_id, "episode_dir": ref.task_id}
                    )
                    for ref in refs
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
