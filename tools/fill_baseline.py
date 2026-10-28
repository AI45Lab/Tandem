#!/usr/bin/env python3
"""把 tools/batch_summary.py 的输出接进基线报告的「自动生成」小节。

用法: python3 tools/fill_baseline.py --prefix osw21-500-kev \
          --report docs/baseline-osw21-500-kev.md
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parent / "batch_summary.py"
_spec = importlib.util.spec_from_file_location("batch_summary", _TOOL)
batch_summary = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(batch_summary)

MARKER = "<!-- AUTO-GENERATED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把汇总结果写进基线报告")
    parser.add_argument("--runs-root", type=Path, default=Path("rjob_logs"))
    parser.add_argument("--prefix", default="osw21-500-kev")
    parser.add_argument("--report", type=Path, default=Path("docs/baseline-osw21-500-kev.md"))
    parser.add_argument("--title", default="OSW2.1 基线汇总 · fast=kev")
    args = parser.parse_args(argv)

    rows = batch_summary.collect_rows(args.runs_root, args.prefix)
    if not rows:
        print(f"没有找到匹配的 run 目录：{args.runs_root}（prefix={args.prefix}）")
        return 1
    stats = batch_summary.summarize(rows)
    report = batch_summary.render_markdown(rows, stats, args.title)

    text = args.report.read_text(encoding="utf-8")
    head, _, _ = text.partition(MARKER)
    if not _:
        print(f"报告里找不到标记 {MARKER}")
        return 1
    import datetime
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (f"{MARKER}\n\n<!-- 生成命令: python3 tools/fill_baseline.py "
              f"--prefix {args.prefix} --report {args.report} -->\n"
              f"<!-- 快照时间: {stamp} -->\n\n")
    args.report.write_text(f"{head}{header}{report}\n", encoding="utf-8")
    print(f"[已更新] {args.report}（{stats['total']} 题，scored {stats['scored']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
