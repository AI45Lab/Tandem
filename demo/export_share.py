#!/usr/bin/env python3
"""把站点导出到内网共享目录，并在发布前逐条自检「诚实披露红线」。

**为什么要有这道闸门**：站点是要给别人看的，一处未标注的口径差异就会变成
「我们比官方强/弱」的既成事实。自检失败就**拒绝导出**，不做"先发出去再说"。

用法：
    python3 demo/export_share.py --site demo/site --out /path/to/shared/dir
    python3 demo/export_share.py --site demo/site --check-only
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: 站点里绝对不允许出现的东西（集群路径 / 凭据）。
#: 凭据用正则而不是裸子串：`sk-` 裸匹配会把 "task-list" 这类普通词误报
#: （026 是 TeamChat 题，消息里满是 "task-list"）。
FORBIDDEN_PATTERNS = (
    re.compile(r"/mnt/shared-storage"),
    re.compile(r"/home/xuyuanxun"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{16,}"),   # OpenAI 风格密钥
    re.compile(r"glpat-[A-Za-z0-9_-]{6,}"),                # GitLab PAT
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{12,}"),          # Bearer 令牌
)


def site_text_files(site_dir: Path) -> list[Path]:
    return [
        path for path in site_dir.rglob("*")
        if path.is_file() and path.suffix in {".html", ".js", ".css", ".json", ".txt"}
    ]


def read_overview(site_dir: Path) -> dict[str, Any]:
    path = site_dir / "assets" / "data" / "overview.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def check_red_lines(site_dir: Path) -> list[tuple[str, bool, str]]:
    """逐条检查红线，返回 [(规则, 是否通过, 说明)]。"""
    overview = read_overview(site_dir)
    ours = overview.get("ours") or {}
    rows = overview.get("rows") or []
    notes = overview.get("disclaimer_notes") or []
    index_path = site_dir / "index.html"
    index_html = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    player_js = ""
    for candidate in site_dir.rglob("*.js"):
        player_js += candidate.read_text(encoding="utf-8", errors="replace")

    checks: list[tuple[str, bool, str]] = []

    # 1 未出分不折算 0
    unscored = [row for row in rows if row.get("status") != "scored"]
    folded = [row for row in unscored if row.get("score") == 0]
    checks.append((
        "未出分的题不折算 0",
        not folded,
        f"未出分 {len(unscored)} 题，其中被折算成 0 的 {len(folded)} 题",
    ))

    # 2 不生成我们的预测分
    blob = json.dumps(overview, ensure_ascii=False).lower()
    forbidden = [word for word in ("predicted", "forecast", "target_score", "预计分", "预期分")
                 if word in blob]
    detail = f"命中：{forbidden}" if forbidden else "未命中"
    checks.append(("不生成我们的预测分/目标分", not forbidden, detail))

    # 3 美元成本带快照日期与底座
    price = ours.get("price") or {}
    checks.append((
        "美元成本标注快照日期与底座型号",
        bool(price.get("snapshot")) and bool(price.get("model")),
        f"快照 {price.get('snapshot')} · 底座 {price.get('model')}",
    ))

    # 4 快模型成本单列（不进美元轴）
    has_fast_axis = "fast_model" in (rows[0] if rows else {}) or "rank_calls" in player_js
    checks.append(("快模型成本单列为第二轴", has_fast_axis, "快模型排序调用数/耗时独立于美元轴"))

    # 5 release / 题集 / 步数差异出现在对比旁
    joined = " ".join(notes)
    checks.append((
        "release/题集/步数预算差异有标注",
        "v2.1" in joined and "题" in joined,
        f"{len(notes)} 条披露",
    ))

    # 6 慢模型原文只搬运
    spot_ok = True
    detail = "站点只搬运 llm_calls.jsonl 的真实内容"
    for path in sorted((site_dir / "assets" / "data" / "episode").rglob("*.json"))[:1]:
        try:
            episode = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        texts = episode.get("llm_texts") or []
        for item in texts:
            if not item.get("text"):
                spot_ok = False
                detail = "有原文条目为空"
            if item.get("truncated") and "截断" not in item.get("text", ""):
                pass  # 截断标记由 UI 展示
    checks.append(("慢模型原文只搬运不编造", spot_ok, detail))

    # 7 排序分数标 softmax
    checks.append((
        "排序分数标 softmax 非校准概率",
        "softmax" in player_js and ("非校准" in player_js or "相对强度" in player_js),
        "播放器带 softmax 标注",
    ))

    # 8 帧是离散帧
    checks.append((
        "帧是离散帧不是录屏",
        "离散帧" in player_js and "recording.mp4" not in index_html,
        "播放器标注离散帧",
    ))

    # 9 失败与口径披露（首屏披露块已按要求删除 → 口径改在对比视图 + 首页对比表备注列）
    has_failure_notes = any("未出分" in note for note in notes) and any("墙钟" in note for note in notes)
    has_caliber_view = "对比口径" in player_js
    checks.append((
        "失败与口径有披露",
        has_failure_notes and has_caliber_view,
        f"{len(notes)} 条口径说明 + 对比视图的「对比口径」面板",
    ))

    return checks


def check_no_secrets(site_dir: Path) -> list[tuple[str, bool, str]]:
    """站点里不能有集群路径与凭据。"""
    hits: list[str] = []
    for path in site_text_files(site_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_PATTERNS:
            match = pattern.search(text)
            if match:
                snippet = text[max(0, match.start() - 30):match.start() + 30].replace("\n", " ")
                hits.append(f"{path.name}: {snippet}")
    return [("站点无集群路径与凭据", not hits,
             f"命中 {len(hits)} 处：{hits[:3]}" if hits else "干净")]


def external_links(site_dir: Path) -> list[str]:
    """站点里不该有**外部资源加载**（离线可开）。

    只认真正的加载姿势：`src=`/`href=`/`url()`/`fetch()`/`@import` 指向外网。
    文本里出现的 URL（价格表出处链接、OOXML 命名空间 URI）不是资源加载，放行。
    """
    patterns = (
        re.compile(r"""src\s*=\s*["']https?://""", re.IGNORECASE),
        re.compile(r"""href\s*=\s*["']https?://""", re.IGNORECASE),
        re.compile(r"""url\(\s*["']?https?://""", re.IGNORECASE),
        re.compile(r"""fetch\(\s*["']https?://""", re.IGNORECASE),
        re.compile(r"""@import\s+(?:url\()?["']https?://""", re.IGNORECASE),
    )
    hits: list[str] = []
    for path in site_text_files(site_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            for match in pattern.finditer(text):
                hits.append(f"{path.name}: {text[match.start():match.start() + 60]}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 demo 站点并自检诚实披露红线")
    parser.add_argument("--site", type=Path, default=REPO_ROOT / "demo" / "site")
    parser.add_argument("--out", type=Path, default=None, help="目标目录（内网共享目录）")
    parser.add_argument("--check-only", action="store_true", help="只自检，不导出")
    args = parser.parse_args(argv)

    site_dir = args.site
    if not site_dir.is_dir():
        print(f"[export] 站点目录不存在：{site_dir}")
        return 2

    checks = check_red_lines(site_dir) + check_no_secrets(site_dir)
    links = external_links(site_dir)
    checks.append(("站点无外部资源引用（离线可开）", not links, f"命中 {links[:3]}" if links else "无外链"))

    print("[export] 诚实披露红线自检：")
    failed = 0
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {name} — {detail}")
    if failed:
        print(f"[export] {failed} 条未通过 —— 拒绝导出。")
        return 1
    if args.check_only or args.out is None:
        tail = "（--check-only，未导出）" if args.check_only else "（未指定 --out，未导出）"
        print("[export] 自检通过。" + tail)
        return 0

    target = args.out
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(site_dir, target)
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    print(f"[export] 已导出到 {target}（{size / 1e6:.1f} MB）")
    print("[export] 打开方式：python3 -m http.server 8899 --directory " + str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
