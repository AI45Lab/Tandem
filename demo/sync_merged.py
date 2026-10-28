#!/usr/bin/env python3
"""刷新「合并基线清单」——我们自己的 OSW v2.1 全量跑批结果。

跑批分两批：
- `c10`：stage_memory 批次（85 题有结果，69 题已出分）
- `c20`：dual_api 批次（补跑 c10 未出分的 39 题 + 11 道 recheck）

**合并口径由环境侧写明**（`experiment.json`）：
- 一个题只认**一次已出分的尝试**（同题多尝试时，已出分优先）；
- 11 道 recheck 题用新的尝试替换旧的，**不看分涨跌**（no best-of）；
- 始终没跑出结果的题记为未完成。

本脚本把环境侧的 `merged_progress.json` 压成一份**精简清单**放进 `demo/data/`，
站点按它挑 run——这样站点数字与环境侧的合并口径**逐题一致**，不会各算各的。

用法：
    python3 demo/sync_merged.py
    python3 demo/sync_merged.py --check      # 只校验，不写
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "demo" / "data"
MANIFEST_PATH = DATA_DIR / "merged_manifest.json"

#: 环境侧的合并视图（双 API 批次目录里）
DEFAULT_MERGED = Path(
    "/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/"
    "tandem_osworld21_dual_api_c20_20261026_1240/merged_progress.json"
)
#: 批次标签 → 该批次 rjob_logs 根目录
BATCH_ROOTS = {
    "c10": Path(
        "/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/"
        "tandem_osworld21_stage_memory_c10_20261025_0450/rjob_logs"
    ),
    "c20": Path(
        "/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/"
        "tandem_osworld21_dual_api_c20_20261026_1240/rjob_logs"
    ),
}
DATASET_SIZE = 108


def batch_of(run_id: str) -> str:
    if "dualapi" in run_id:
        return "c20"
    if "stagememory" in run_id:
        return "c10"
    return "unknown"


def build_manifest(merged_path: Path) -> dict[str, Any]:
    payload = json.loads(merged_path.read_text(encoding="utf-8"))
    tasks: dict[str, Any] = {}
    for entry in payload.get("tasks") or []:
        task_id = str(entry.get("task_id"))
        run_id = str(entry.get("run_id") or "")
        timing = entry.get("timing") or {}
        tasks[task_id] = {
            "run_id": run_id,
            "batch": batch_of(run_id),
            "score": entry.get("score"),
            "status": entry.get("status"),
            "stop_reason": entry.get("stop_reason"),
            "steps": entry.get("steps"),
            "wall_seconds": timing.get("wall_seconds"),
            "exception_type": entry.get("exception_type"),
        }
    scored = [item["score"] for item in tasks.values() if isinstance(item.get("score"), (int, float))]
    return {
        "source_url": str(merged_path),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset_size": DATASET_SIZE,
        "scored": len(scored),
        "missing": sorted(
            f"{index:03d}" for index in range(1, DATASET_SIZE + 1)
            if f"{index:03d}" not in tasks
        ),
        "batch_roots": {key: str(value) for key, value in BATCH_ROOTS.items()},
        "merge_rule": (
            "一个题只认一次已出分的尝试；11 道 recheck 用新的替换旧的（不看分涨跌）；"
            "始终没跑出结果的题记为未完成。"
        ),
        "mean_scored": round(sum(scored) / len(scored), 6) if scored else None,
        "mean_over_dataset": round(sum(scored) / DATASET_SIZE, 6) if scored else None,
        "binary": sum(1 for value in scored if value >= 1.0),
        "tasks": tasks,
    }


def verify(manifest: dict[str, Any]) -> list[str]:
    """逐题核对：清单里的 run 在磁盘上存在，且分数一致。"""
    problems: list[str] = []
    for task_id, item in (manifest.get("tasks") or {}).items():
        root = BATCH_ROOTS.get(item.get("batch") or "")
        if root is None:
            problems.append(f"{task_id}: 未知批次 {item.get('batch')}")
            continue
        summary = root / item["run_id"] / "summary.json"
        if not summary.is_file():
            problems.append(f"{task_id}: 找不到 {summary}")
            continue
        tasks = json.loads(summary.read_text(encoding="utf-8")).get("tasks") or []
        row = next((row for row in tasks if str(row.get("task_id")) == task_id), None)
        if row is None:
            problems.append(f"{task_id}: summary 里没有这道题")
        elif row.get("score") != item.get("score"):
            problems.append(f"{task_id}: 分数不一致 清单={item.get('score')} 磁盘={row.get('score')}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="刷新合并基线清单")
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--check", action="store_true", help="只校验现有清单，不写")
    args = parser.parse_args(argv)

    if args.check:
        if not MANIFEST_PATH.is_file():
            print("还没有清单，先跑一次 sync_merged.py")
            return 2
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    else:
        if not args.merged.is_file():
            print(f"[merged] 找不到环境侧合并视图：{args.merged}")
            return 2
        manifest = build_manifest(args.merged)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[merged] 写入 {MANIFEST_PATH.relative_to(REPO_ROOT)}")

    problems = verify(manifest)
    if problems:
        print(f"[merged] 校验未通过（{len(problems)} 处）：")
        for problem in problems[:20]:
            print("   ", problem)
        return 1
    print(
        f"[merged] 校验通过：{manifest['scored']}/{manifest['dataset_size']} 已出分 · "
        f"均值(已出分) {manifest['mean_scored']} · 均值(108 分母) {manifest['mean_over_dataset']} · "
        f"binary {manifest['binary']} · 未完成 {manifest['missing']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
