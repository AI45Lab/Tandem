"""HTML 渲染层：把文档变成页面（自包含数据 + 共享 CSS/JS）。

展示载荷与完整证据分离：页面内联的 JSON 已裁剪（长文本标注截断），
完整原文落在 `assets/evidence/<run>/<task>.json`，由播放器的证据抽屉按需拉取。
"""

from __future__ import annotations

import html
import json
from typing import Any

CONTRACT_VERSION = "v0.2"
#: 展示载荷里单个字符串的最大长度（超长截断并标注）；完整原文进证据文件
TEXT_LIMIT = 1600
#: 候选描述的最大长度
DESC_LIMIT = 240

DISCLOSURE = (
    "未出分（failed_unscored）如实标注，不折算 0 分、不计入均分；"
    "快模型排序分数为 softmax 输出，非校准正确率；成本以 token 用量与调用次数表达，"
    "未换算货币单价；截图为逐步离散帧，非连续录屏；"
    "时间轴为实测时刻重建（不估算未记录的时间）。"
)


def fmt(value: Any) -> str:
    """数字统一格式化；非数字返回 '-'。"""
    if isinstance(value, (int, float)):
        return f"{value:.1f}"
    return "-"


def embed(payload: Any) -> str:
    """把 JSON 内联进 <script type="application/json">（转义 </script>）。"""
    text = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/json" id="payload">{text}</script>'


def trim(value: Any, limit: int = TEXT_LIMIT) -> Any:
    """递归裁剪超长字符串——展示载荷用；完整原文进证据文件。"""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit] + f"…（已截断，完整原文见运行证据，共 {len(value)} 字）"
        return value
    if isinstance(value, dict):
        return {key: trim(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [trim(item, limit) for item in value]
    return value


def display_payload(run: dict[str, Any], task: dict[str, Any], frames: dict[str, Any]) -> dict[str, Any]:
    """内联进页面的展示载荷（裁剪后）。"""
    steps = []
    for step in task["steps"]:
        item = dict(step)
        candidates = []
        for candidate in item.get("candidates") or []:
            short = dict(candidate)
            if isinstance(short.get("description"), str):
                short["description"] = short["description"][:DESC_LIMIT]
            candidates.append(short)
        item["candidates"] = candidates
        steps.append(trim(item))
    llm_calls = [
        {
            "role": call.get("role"),
            "time": call.get("time"),
            "attempt": call.get("attempt"),
            "usage": call.get("usage") or {},
        }
        for call in task["llm_calls"]
    ]
    return {
        "run": {
            "run_id": run["run_id"],
            "benchmark": run["benchmark"],
            "git_describe": run["git_describe"],
            "fast_model": run["fast_model"],
        },
        "task": {
            "task_id": task["task_id"],
            "domain": task["domain"],
            "instruction": task["instruction"],
            "snapshot": task["snapshot"],
            "status": task["status"],
            "score": task["score"],
            "scored": task["scored"],
            "stop_reason": task["stop_reason"],
            "exception_type": task["exception_type"],
            "wall_seconds": task["wall_seconds"],
            "cost": task["cost"],
            "fast_calls": task["fast_calls"],
            "fast_latency_ms_total": task["fast_latency_ms_total"],
            "evaluation": task["evaluation"],
            "steps": steps,
            "llm_calls": llm_calls,
            "requirements": task.get("requirements") or [],
            "timeline": task.get("timeline") or {},
            "chapters": task.get("chapters") or [],
        },
        "frames": frames,
        "evidence_url": f"../../assets/evidence/{run['run_id']}/{task['task_id']}.json",
    }


def evidence_doc(task: dict[str, Any]) -> dict[str, Any]:
    """完整证据文档（原始事件 + 完整 LLM 请求/响应），落独立 JSON。"""
    return {
        "task_id": task["task_id"],
        "episode_dir": task["episode_dir"],
        "steps": task["steps"],
        "llm_calls": task["llm_calls"],
        "evaluation": task["evaluation"],
        "cost": task["cost"],
        "requirements": task.get("requirements") or [],
        "chapters": task.get("chapters") or [],
    }


def _readout(task: dict[str, Any]) -> str:
    """读数带：准确率 / 成本 / 时长（沿用旧版 studio 的三读数布局）。"""
    if task["scored"] and task["score"] is not None:
        score_big = f"{task['score']:.4g}"
        score_cls = "good" if task["score"] > 0 else "na"
        score_sub = f"已出分 · 官方 evaluator · {task['stop_reason'] or '-'}"
    else:
        score_big = "未出分"
        score_cls = "na"
        score_sub = f"{task['exception_type'] or task['stop_reason'] or '异常'} · 如实标注，不计 0 分"
    total = task["cost"]["total"]
    cost_big = f"{total['prompt_tokens'] + total['completion_tokens']:,}"
    cost_sub = (
        f"{total['calls']} 次调用 · 输入 {total['prompt_tokens']:,} / 输出 "
        f"{total['completion_tokens']:,}（含思考 {total['reasoning_tokens']:,}）"
    )
    wall = task["wall_seconds"]
    time_big = f"{wall:.0f}s" if isinstance(wall, (int, float)) else "—"
    time_sub = (
        f"约 {wall / 60:.0f} 分钟" if isinstance(wall, (int, float)) else "无 timing.json"
    )
    return f"""<section class="readout">
  <div class="meter {score_cls}"><small>官方评分 · 准确率</small><b>{html.escape(score_big)}</b><span class="sub">{html.escape(score_sub)}</span></div>
  <div class="meter"><small>token 用量 · 执行成本</small><b>{html.escape(cost_big)}</b><span class="sub">{html.escape(cost_sub)}</span></div>
  <div class="meter"><small>真实用时 · wall-clock</small><b>{html.escape(time_big)}</b><span class="sub">{html.escape(time_sub)}</span></div>
  <div class="rail"><span><b>{len(task['steps'])}</b> 决策步</span><span>快模型排序 <b>{task['fast_calls']}</b> 次</span></div>
</section>"""


def render_task_page(run: dict[str, Any], task: dict[str, Any], frames: dict[str, Any]) -> str:
    """单题轨迹回放页。"""
    payload = display_payload(run, task, frames)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(task['task_id'])} · {html.escape(run['run_id'])} · Tandem 轨迹回放</title>
<link rel="stylesheet" href="../../assets/player.css">
<link rel="stylesheet" href="../../assets/player-v2.css">
</head>
<body>
<header class="topbar">
  <a class="back" href="../../index.html">← 总览</a>
  <div class="titles">
    <h1>OSW2 任务 {html.escape(task['task_id'])}</h1>
    <p class="sub">{html.escape(run['run_id'])} · 大脑={html.escape(str(run.get('slow_model', '')))} · 小脑={html.escape(run['fast_model'])} · git {html.escape(str(run['git_describe']))}</p>
  </div>
  <div class="badges">
    <span class="badge">契约 {CONTRACT_VERSION}</span>
    <span class="badge">状态 {html.escape(task['status'])}</span>
  </div>
</header>
{_readout(task)}
<section class="instruction"><h2>任务指令</h2><p>{html.escape(task['instruction'])}</p></section>
<main class="player">
  <section class="stage">
    <div id="stage-media">
      <div class="framebox">
        <figure><figcaption id="cap-before">执行前</figcaption><img id="img-before" alt="执行前截图"><p class="noshot" id="noshot-before" hidden></p></figure>
        <figure><figcaption id="cap-after">执行后</figcaption><img id="img-after" alt="执行后截图"><p class="noshot" id="noshot-after" hidden></p></figure>
      </div>
      <div class="stepnav">
        <button id="prev" type="button">← 上一步</button>
        <span id="step-label">-</span>
        <button id="next" type="button">下一步 →</button>
      </div>
    </div>
    <section class="panel zerostate" id="zero-state" hidden></section>
    <section class="panel chapters"><h2>需求清单 · 逐条核验</h2><ol id="chapter-list"></ol></section>
  </section>
  <aside class="detail" id="detail"></aside>
</main>
<section class="panel tlpanel">
  <div class="tlhead"><h2>真实时钟轨迹</h2><span class="sub" id="tl-note"></span></div>
  <div id="lanes"></div>
  <div class="ruler" id="ruler"></div>
</section>
<nav class="timeline" id="timeline"></nav>
<section class="evidence"><button id="toggle-evidence" type="button">运行证据（原始 JSON）</button><pre id="evidence" hidden></pre></section>
<footer class="foot">{DISCLOSURE}</footer>
{embed(payload)}
<script src="../../assets/player.js"></script>
<script src="../../assets/player-detail.js"></script>
<script src="../../assets/player-fail.js"></script>
<script src="../../assets/player-task.js"></script>
</body>
</html>
"""
