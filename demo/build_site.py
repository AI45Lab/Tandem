"""生成 demo 静态站点（轨迹回放 + 多 run 对比）。

用法：

```bash
python demo/build_site.py --runs-root rjob_logs --out demo/site --benchmark osworld2
```

产物：

```
site/
├── index.html                     # 批次总览 + 成本/耗时/准确率对比
├── task/<run_id>/<task_id>.html   # 单题轨迹回放
└── assets/
    ├── player.css / player.js     # 播放器（无第三方依赖）
    ├── frames/<run_id>/<task_id>/ # 缩放后的截图帧 + 缩略图
    └── evidence/<run_id>/<task>.json # 完整原始证据
```

帧处理用 Pillow（构建期依赖，运行时零依赖）；Pillow 缺失时退化为原样拷贝 PNG。
数据以 JSON 内联进 HTML——`file://` 直接双击也能打开，不需要起服务器。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from adapter import load_run
from frames import make_thumbnail, process_frames
from metrics import build_comparison
from pages import render_compare, render_index
from render import evidence_doc, render_task_page

PLAYER_FILES = (
    "player.css",
    "player-v2.css",
    "player.js",
    "player-compare.js",
    "player-detail.js",
    "player-fail.js",
    "player-task.js",
)


def discover_runs(runs_root: Path, benchmark: str | None) -> list[Path]:
    """在结果目录里找出符合基准的 run 目录（按目录名排序）。"""
    found: list[Path] = []
    if not runs_root.is_dir():
        return found
    for candidate in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        summary = candidate / "summary.json"
        if not summary.is_file():
            continue
        if benchmark:
            try:
                value = json.loads(summary.read_text(encoding="utf-8")).get("benchmark")
            except (OSError, json.JSONDecodeError):
                continue
            if value != benchmark:
                continue
        found.append(candidate)
    return found


def _copy_player(out_dir: Path) -> None:
    player_dir = Path(__file__).resolve().parent / "player"
    for name in PLAYER_FILES:
        shutil.copyfile(player_dir / name, out_dir / "assets" / name)


def build(
    runs_root: Path, out_dir: Path, run_dirs: list[Path], benchmark: str | None
) -> dict[str, Any]:
    """构建整个站点，返回统计摘要。"""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    _copy_player(out_dir)

    runs = [load_run(path) for path in run_dirs]
    runs = [run for run in runs if not benchmark or run["benchmark"] == benchmark]
    comparison = build_comparison(runs)

    pages = 0
    for run in runs:
        for task in run["tasks"]:
            episode_dir = runs_root / run["run_id"] / "episodes" / task["episode_dir"]
            frame_dir = out_dir / "assets" / "frames" / run["run_id"] / task["task_id"]
            frames = process_frames(episode_dir, frame_dir)
            if frames:
                first = frame_dir / next(iter(sorted(frames.values())))
                make_thumbnail(first, frame_dir / "thumb.jpg")
            page_dir = out_dir / "task" / run["run_id"]
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / f"{task['task_id']}.html").write_text(
                render_task_page(run, task, frames), encoding="utf-8"
            )
            evidence_dir = out_dir / "assets" / "evidence" / run["run_id"]
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / f"{task['task_id']}.json").write_text(
                json.dumps(evidence_doc(task), ensure_ascii=False, indent=1), encoding="utf-8"
            )
            pages += 1

    (out_dir / "index.html").write_text(render_index(runs, comparison), encoding="utf-8")
    (out_dir / "compare.html").write_text(render_compare(comparison), encoding="utf-8")
    return {"runs": len(runs), "pages": pages, "out": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 Tandem OSW2 轨迹 demo 静态站点")
    parser.add_argument("--runs-root", default="rjob_logs", type=Path)
    parser.add_argument("--out", default=Path("demo/site"), type=Path)
    parser.add_argument("--benchmark", default="osworld2")
    parser.add_argument("--run", action="append", dest="runs", help="只构建指定 run（可重复）")
    args = parser.parse_args(argv)

    run_dirs = (
        [Path(name) for name in args.runs]
        if args.runs
        else discover_runs(args.runs_root, args.benchmark)
    )
    if not run_dirs:
        print(f"没有找到 benchmark={args.benchmark} 的 run 目录：{args.runs_root}")
        return 1
    summary = build(args.runs_root, args.out, run_dirs, args.benchmark)
    print(
        f"站点已生成：{summary['out']}（{summary['runs']} 个 run，{summary['pages']} 个任务页）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
