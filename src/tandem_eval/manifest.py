"""任务清单：OSW1/OSW2 使用共享索引，OSW2.1 使用 56 题清单，也支持显式题号或清单文件。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: OSW2.1 子集题号（56 题）。
#:
#: 出处：共享环境 `osworld21/validation/coverage.json` 中 `official_vm.status == "passed"`
#: 的题（2026-10-22 快照）。该覆盖表由 `osworld21/setup/summarize_environment.py` 持续
#: 重生成，本清单是它的一次快照——覆盖表更新后必须重新核对，否则会与真实环境脱节。
#: 快照时官方 passed 共 86 道，其余 30 道的排除口径尚未记录（待补）；本清单当前是
#: "已验证通过"的保守子集，不含 failed / not_tested 的题。
OSWORLD21_TASK_IDS = tuple((
    "001 002 003 004 006 009 010 011 012 014 017 022 023 024 "
    "025 027 029 030 032 034 037 040 042 044 045 049 051 053 "
    "054 055 059 061 062 063 066 067 071 074 075 076 078 080 "
    "083 084 085 086 088 089 090 092 093 094 096 097 099 108"
).split())


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
    elif benchmark == "osworld21":
        refs = [TaskRef(task_id=task_id) for task_id in OSWORLD21_TASK_IDS]
    elif benchmark in {"osworld1", "osworld2"} and (
        spec.get("index_root") or spec.get("env", {}).get("root")
    ):
        index_file = (
            "test_nogdrive.json" if benchmark == "osworld1" else "test_v2.json"
        )
        if spec.get("index_root"):
            # 显式 index_root = 共享 benchmarks 根（含 osworld1/、osworld2/ 子目录）
            index = Path(spec["index_root"]) / benchmark / "evaluation_examples" / index_file
        else:
            # env.root 已是各基准根目录
            index = Path(spec["env"]["root"]) / "evaluation_examples" / index_file
        refs = load_index(index)
    elif benchmark == "mock":
        refs = [TaskRef(task_id=f"mock-{i:03d}", domain="mock") for i in range(1)]
    else:
        raise ValueError(f"无法解析 manifest：benchmark={benchmark} 且未提供 index_root/tasks/path")
    if benchmark == "osworld21":
        unsupported = [ref.task_id for ref in refs if ref.task_id not in OSWORLD21_TASK_IDS]
        if unsupported:
            raise ValueError(f"OSWorld 2.1 tasks outside the supported subset: {unsupported}")
    limit = manifest.get("limit")
    if isinstance(limit, int) and limit > 0:
        refs = refs[:limit]
    shard = manifest.get("shard")
    if isinstance(shard, dict) and shard.get("total", 0) > 0:
        index, total = int(shard["index"]), int(shard["total"])
        if not 1 <= index <= total:
            raise ValueError(f"shard.index 必须在 1..{total}（收到 {index}）")
        refs = refs[index - 1::total]  # 交错切片：先 limit 后 shard
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
