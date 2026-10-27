#!/usr/bin/env python3
"""把合并基线渲染成一份 Markdown 报告（团队不打开站点也能读）。

数据源是 `demo/data/merged_manifest.json`（环境侧合并口径，已逐题核对磁盘），
所以报告里的每个数字都与站点、与环境侧三方一致。

用法：
    python3 demo/render_merged_report.py --out docs/baseline-osw21-108-merged.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "demo" / "data" / "merged_manifest.json"

STOP_LABELS = {
    "done": "完成（规划+核验都过了）",
    "wall_time_limit": "撞 4 小时墙钟",
    "no_action_limit": "空转过多被判定无动作",
    "max_steps": "步数耗尽",
    "exception": "异常未出分",
}


def render(manifest: dict) -> str:
    tasks = manifest.get("tasks") or {}
    scores = [item["score"] for item in tasks.values() if isinstance(item.get("score"), (int, float))]
    dataset = int(manifest.get("dataset_size") or 108)
    total = sum(scores)
    binary = [item for item in tasks.values() if (item.get("score") or 0) >= 1.0]
    partial = [item for item in tasks.values() if 0 < (item.get("score") or 0) < 1.0]
    zero = [item for item in tasks.values() if item.get("score") == 0]
    missing = manifest.get("missing") or []
    stops = Counter(str(item.get("stop_reason")) for item in tasks.values())
    batches = Counter(item.get("batch") for item in tasks.values())

    lines: list[str] = []
    add = lines.append
    add("# OSW v2.1 全量基线（c10 + c20 合并，108 题）")
    add("")
    add(f"> 生成时间：{manifest.get('fetched_at')} · 数据源：{manifest.get('source_url')}")
    add("")
    add("## 口径")
    add("")
    add(f"- 跑批分两批：**c10**（stage_memory 批次，{batches.get('c10', 0)} 题计入）与 "
        f"**c20**（dual_api 批次，{batches.get('c20', 0)} 题计入）；两批配置一致"
        "（stage 模式 / 500 动作 / 4h 墙钟 / reasoning_effort=max / max_tokens=32768 / 原生官方评测器）。")
    add(f"- 合并规则：{manifest.get('merge_rule')}")
    add(f"- 未跑出结果（两批都没出分）：**{', '.join(missing) if missing else '无'}**")
    add("")
    add("## 汇总")
    add("")
    add("| 指标 | 值 |")
    add("|---|---|")
    add(f"| 题目总数 | {dataset} |")
    add(f"| 已出分 | **{len(scores)}**（未出分 {len(missing)}） |")
    add(f"| Partial Score（{dataset} 题分母，未出分计 0） | **{total / dataset:.4f}** |")
    add(f"| Partial Score（仅已出分 {len(scores)} 题） | **{total / len(scores):.4f}** |")
    binary_rate = len(binary) / dataset * 100
    add(f"| Binary Accuracy（逐题分恰好 1.00） | **{len(binary)}/{dataset} = {binary_rate:.2f}%** |")
    add(f"| 满分 / 部分分 / 零分 | {len(binary)} / {len(partial)} / {len(zero)} |")
    add(f"| 非零题数 | {len(binary) + len(partial)}（{(len(binary) + len(partial)) / dataset * 100:.1f}%） |")
    add("")
    add("### 停止原因")
    add("")
    add("| 停止原因 | 题数 | 含义 |")
    add("|---|---|---|")
    for name, count in stops.most_common():
        label = STOP_LABELS.get(name)
        if label is None:
            label = "其它（规划判定不可行）" if len(name) > 40 else "—"
        add(f"| `{(name[:38] + '…') if len(name) > 40 else name}` | {count} | {label} |")
    add("")
    add("### 满分题")
    add("")
    add("| 题 | 分数 | 步数 | 来源 |")
    add("|---|---|---|---|")
    for task_id, item in sorted(tasks.items()):
        if (item.get("score") or 0) >= 1.0:
            add(f"| {task_id} | {item['score']:.4f} | {item.get('steps')} | {item.get('batch')} |")
    add("")
    add("## 逐题明细")
    add("")
    add("| 题 | 分数 | 停止原因 | 步数 | 墙钟(s) | 来源 |")
    add("|---|---|---|---|---|---|")
    for task_id in sorted(tasks):
        item = tasks[task_id]
        score = "未出分" if item.get("score") is None else f"{item['score']:.4f}"
        wall = item.get("wall_seconds")
        add(
            f"| {task_id} | {score} | `{str(item.get('stop_reason'))[:40]}` | {item.get('steps')} | "
            f"{round(wall) if isinstance(wall, (int, float)) else '—'} | {item.get('batch')} |"
        )
    add("")
    add("---")
    add("")
    add("逐题数值与站点、与环境侧 `merged_progress.json` 三方一致；"
        "改动请走 `demo/sync_merged.py`（刷新清单）→ `demo/build_site.py`（重建站点）。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="渲染合并基线报告")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "baseline-osw21-108-merged.md"
    )
    args = parser.parse_args(argv)
    if not args.manifest.is_file():
        print(f"缺合并清单：{args.manifest}（先跑 demo/sync_merged.py）")
        return 2
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(manifest), encoding="utf-8")
    print(f"写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
