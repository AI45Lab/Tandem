"""总览页与对比页渲染（demo 内部用）。

- 总览页：run 卡片 + **成本 vs 准确率散点**（服务端生成 SVG，无第三方图表库）
  + 任务缩略图网格 + 可排序对比表。
- 对比页：任选两个 run，逐题并排并给出差值（成本 / 耗时 / 准确率）。
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from render import DISCLOSURE, embed, fmt


def _run_card(run: dict[str, Any]) -> str:
    totals = run["totals"]
    score_text = f"{totals['average_score']:.4g}" if totals["average_score"] is not None else "-"
    failures = (
        "、".join(f"{k}×{v}" for k, v in sorted(totals["failures"].items())) or "无"
    )
    return f"""<article class="card">
  <h3>{html.escape(run['run_id'])}</h3>
  <p class="sub">git {html.escape(str(run['git_describe']))} · selector={html.escape(run['selector_backend'])}</p>
  <dl>
    <div><dt>已出分</dt><dd>{totals['scored']} / {totals['total']}</dd></div>
    <div><dt>未出分</dt><dd>{totals['failed_unscored']}</dd></div>
    <div><dt>均分（仅已出分）</dt><dd>{score_text}</dd></div>
    <div><dt>满分 / 零分</dt><dd>{totals['perfect']} / {totals['zero']}</dd></div>
    <div><dt>总耗时</dt><dd>{totals['wall_seconds_total']:.0f}s</dd></div>
    <div><dt>LLM 调用</dt><dd>{totals['cost']['calls']}</dd></div>
    <div><dt>输入 token</dt><dd>{totals['cost']['prompt_tokens']:,}</dd></div>
    <div><dt>输出 token</dt><dd>{totals['cost']['completion_tokens']:,}</dd></div>
    <div><dt>其中思考 token</dt><dd>{totals['cost']['reasoning_tokens']:,}</dd></div>
    <div><dt>JEV 排序次数</dt><dd>{totals['jev_calls']}</dd></div>
    <div><dt>失败分类</dt><dd class="wrap">{html.escape(failures)}</dd></div>
  </dl>
</article>"""


def _scatter(comparison: dict[str, Any], width: int = 760, height: int = 340) -> str:
    """成本（token）× 准确率 散点；横轴 sqrt 刻度，纵轴 0–1。"""
    points: list[dict[str, Any]] = []
    for entry in comparison["tasks"]:
        for run_id, cell in sorted(entry["runs"].items()):
            points.append({"task": entry["task_id"], "run": run_id, **cell})
    if not points:
        return '<p class="muted">没有可画的点。</p>'

    pad_l, pad_r, pad_t, pad_b = 52, 16, 30, 62
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_token = max((p["tokens"] for p in points), default=1) or 1
    max_wall = max((p["wall_seconds"] or 0 for p in points), default=1) or 1

    def x_of(tokens: int) -> float:
        return pad_l + plot_w * ((tokens / max_token) ** 0.5 if max_token else 0)

    def y_of(score: float) -> float:
        return pad_t + plot_h * (1 - max(0.0, min(1.0, score)))

    parts = [f'<svg class="scatter" viewBox="0 0 {width} {height}" role="img">']
    for tick in range(5):
        value = tick / 4
        y = y_of(value)
        parts.append(
            f'<line class="grid" x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" />'
        )
        parts.append(f'<text class="axis" x="{pad_l - 8}" y="{y + 4:.1f}">{value:g}</text>')
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = pad_l + plot_w * frac
        tokens = int((max_token * (frac**2)) / 1000)
        parts.append(f'<text class="axis" x="{x:.1f}" y="{height - 18}">{tokens}k</text>')
    parts.append(
        f'<text class="axis-title" x="{pad_l + plot_w / 2:.1f}" y="{height - 2}">'
        "token 用量（平方根刻度）→</text>"
    )
    parts.append(
        f'<text class="axis-title" x="14" y="{pad_t + plot_h / 2:.1f}" '
        'transform="rotate(-90 14 '
        f'{pad_t + plot_h / 2:.1f})">官方评分 →</text>'
    )
    # 已出分的题画在主图内（半径∝耗时）
    for point in points:
        if not (point["scored"] and point["score"] is not None):
            continue
        x = x_of(point["tokens"])
        y = y_of(point["score"])
        radius = 5 + 9 * ((point["wall_seconds"] or 0) / max_wall) ** 0.5
        cls = "point ok" if point["score"] > 0 else "point zero"
        tip = (
            f"{point['task']} · {point['run']} · 分数 {point['score']:.4g}"
            f" · {point['tokens']:,} token · {fmt(point['wall_seconds'])}s"
        )
        parts.append(
            f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}">'
            f"<title>{html.escape(tip)}</title></circle>"
        )
        parts.append(
            f'<text class="plabel" x="{x:.1f}" y="{y - radius - 4:.1f}">'
            f"{html.escape(point['task'])}</text>"
        )
    # 未出分的题单独排一行，避免在主图里堆叠重叠
    unscored = [p for p in points if not (p["scored"] and p["score"] is not None)]
    if unscored:
        strip_y = pad_t + plot_h + 16
        parts.append(
            f'<line class="grid" x1="{pad_l}" y1="{strip_y}" x2="{width - pad_r}" y2="{strip_y}" />'
        )
        parts.append(f'<text class="axis" x="{pad_l - 8}" y="{strip_y + 4:.1f}">未出分</text>')
        slot = max(18.0, (width - pad_l - pad_r) / max(1, len(unscored)))
        for index, point in enumerate(unscored):
            x = pad_l + slot * (index + 0.5)
            tip = (
                f"{point['task']} · {point['run']} · 未出分 · {point['tokens']:,} token"
                f" · {fmt(point['wall_seconds'])}s"
            )
            parts.append(
                f'<circle class="point miss" cx="{x:.1f}" cy="{strip_y:.1f}" r="5">'
                f"<title>{html.escape(tip)}</title></circle>"
            )
            parts.append(
                f'<text class="plabel" x="{x:.1f}" y="{strip_y + 17:.1f}">'
                f"{html.escape(point['task'])}</text>"
            )
    parts.append("</svg>")
    parts.append(
        '<p class="sub">实心=已出分（绿=有分，红=零分；半径∝耗时）；下方一排=未出分（不计入均分）。'
        "悬停看明细。</p>"
    )
    return "".join(parts)


def _task_grid(runs: list[dict[str, Any]]) -> str:
    cards = []
    for run in runs:
        for task in run["tasks"]:
            href = f"task/{html.escape(run['run_id'])}/{html.escape(task['task_id'])}.html"
            if task["scored"] and task["score"] is not None:
                badge = f'<span class="badge ok">{task["score"]:.4g}</span>'
            else:
                badge = '<span class="badge miss">未出分</span>'
            if task.get("frames"):
                thumb = (
                    f"assets/frames/{html.escape(run['run_id'])}/"
                    f"{html.escape(task['task_id'])}/thumb.jpg"
                )
                shot = f'<img src="{thumb}" alt="任务 {html.escape(task["task_id"])} 首帧" loading="lazy">'
            else:
                shot = '<div class="nothumb">无帧<br><small>未进入决策步</small></div>'
            cards.append(
                f"""<a class="tcard" href="{href}">
  {shot}
  <div class="tmeta"><b>{html.escape(task['task_id'])}</b>{badge}<span class="sub">{html.escape(run['run_id'])}</span></div>
</a>"""
            )
    return f'<section class="grid-cards">{"".join(cards)}</section>'


def _task_rows(comparison: dict[str, Any]) -> str:
    rows = []
    for entry in comparison["tasks"]:
        for run_id, cell in sorted(entry["runs"].items()):
            score_cell = (
                f"{cell['score']:.4g}" if cell["scored"] and cell["score"] is not None else "未出分"
            )
            cls = "ok" if cell["scored"] else "miss"
            link = f"task/{html.escape(run_id)}/{html.escape(entry['task_id'])}.html"
            rows.append(
                f"""<tr>
  <td><a href="{link}">{html.escape(entry['task_id'])}</a></td>
  <td>{html.escape(run_id)}</td>
  <td class="{cls}">{score_cell}</td>
  <td>{html.escape(str(cell['status']))}</td>
  <td>{html.escape(str(cell['stop_reason']))}</td>
  <td>{fmt(cell['wall_seconds'])}s</td>
  <td>{cell['steps']}</td>
  <td>{cell['tokens']:,}</td>
  <td>{cell['llm_calls']}</td>
  <td>{cell['jev_calls']}</td>
</tr>"""
            )
    return "".join(rows)


def render_index(runs: list[dict[str, Any]], comparison: dict[str, Any]) -> str:
    """总览页：run 卡片 + 散点 + 缩略图网格 + 可排序对比表。"""
    payload = {
        "runs": comparison["runs"],
        "tasks": comparison["tasks"],
        "contract": "v0.2",
    }
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tandem OSW2 轨迹与对比</title>
<link rel="stylesheet" href="assets/player.css">
<link rel="stylesheet" href="assets/player-v2.css">
</head>
<body>
<header class="topbar">
  <div class="titles">
    <h1>Tandem · OSWorld2 轨迹回放与对比</h1>
    <p class="sub">{len(runs)} 个 run · 契约 v0.2 · 生成于 {html.escape(generated)}</p>
  </div>
  <nav class="topnav"><a href="compare.html">两个 run 对比 →</a></nav>
</header>
<section class="cards">{''.join(_run_card(run) for run in runs)}</section>
<section class="panel">
  <h2>成本 × 准确率</h2>
  {_scatter(comparison)}
</section>
<section class="panel">
  <h2>任务缩略图</h2>
  {_task_grid(runs)}
</section>
<section class="panel">
  <h2>逐题对比（成本 / 耗时 / 准确率）· 点表头排序</h2>
  <table class="grid">
    <thead><tr><th>任务</th><th>run</th><th>分数</th><th>状态</th><th>停止原因</th>
    <th>耗时</th><th>步数</th><th>token</th><th>LLM 调用</th><th>JEV 排序</th></tr></thead>
    <tbody>{_task_rows(comparison)}</tbody>
  </table>
</section>
<section class="panel disclosure"><h2>披露口径</h2><p>{DISCLOSURE}</p></section>
<footer class="foot">demo 只读结果目录，不 import harness、不调模型、不碰 VM</footer>
{embed(payload)}
<script src="assets/player.js"></script>
</body>
</html>
"""


def render_compare(comparison: dict[str, Any]) -> str:
    """两个 run 的对比页（选择器在浏览器里切换）。"""
    payload = {
        "runs": comparison["runs"],
        "tasks": comparison["tasks"],
        "contract": "v0.2",
    }
    options = "".join(
        f'<option value="{html.escape(run["run_id"])}">{html.escape(run["run_id"])}'
        f'（selector={html.escape(run["selector_backend"])}）</option>'
        for run in comparison["runs"]
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tandem OSW2 · 两个 run 对比</title>
<link rel="stylesheet" href="assets/player.css">
<link rel="stylesheet" href="assets/player-v2.css">
</head>
<body>
<header class="topbar">
  <a class="back" href="index.html">← 总览</a>
  <div class="titles">
    <h1>两个 run 对比</h1>
    <p class="sub">成本 / 耗时 / 准确率 · 逐题并排与差值</p>
  </div>
</header>
<section class="panel cmp">
  <div class="cmp-picker">
    <label>A <select id="cmp-a">{options}</select></label>
    <label>B <select id="cmp-b">{options}</select></label>
  </div>
  <div id="cmp-summary"></div>
  <div id="cmp-table"></div>
</section>
<section class="panel disclosure"><h2>披露口径</h2><p>{DISCLOSURE}</p></section>
<footer class="foot">demo 只读结果目录，不 import harness、不调模型、不碰 VM</footer>
{embed(payload)}
<script src="assets/player.js"></script>
<script src="assets/player-compare.js"></script>
</body>
</html>
"""
