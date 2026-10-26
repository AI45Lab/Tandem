/* 双轨同步播放器：上轨慢模型原文 / 下轨快模型排序 / 侧轨帧序列
 *
 * 纪律：
 * - 慢模型原文**只搬运** llm_calls.jsonl 里的真实内容（被截断时如实标注）；
 * - 排序分数恒标 **softmax，非校准概率**；
 * - 帧是离散帧不是录屏，缺失就标缺失。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function slowLane(episode) {
    var texts = episode.llm_texts || [];
    var nodes = texts.map(function (item) {
      return TD.el("div", { style: "margin-bottom:10px" }, [
        TD.el("div", { class: "dim mono", style: "font-size:11px",
          text: item.role + " · 第 " + (item.attempt || 1) + " 次尝试" }),
        TD.el("pre", { class: "text", text: item.text }),
        item.truncated ? TD.el("div", { class: "hint", text: "（原文已截断，完整内容见 llm_calls.jsonl）" }) : null
      ]);
    });
    if (!nodes.length) {
      nodes.push(TD.el("div", { class: "hint", text: "这一题没有慢模型原文记录。" }));
    }
    return TD.el("div", { class: "lane slow" }, [
      TD.el("h3", { text: "慢模型（大脑）· 规划原文" })
    ].concat(nodes));
  }

  function candidateRows(step) {
    var ranking = step.ranking || {};
    var ranked = ranking.operation_ranked || [];
    var rows = ranked.map(function (item, index) {
      var score = typeof item.score === "number" ? item.score : 0;
      return TD.el("div", { class: "cand-row" + (index === 0 ? " winner" : "") }, [
        TD.el("span", { class: "op", text: item.operation || "—" }),
        TD.el("span", { class: "softmax" }, [TD.el("i", { style: "width:" + (score * 100).toFixed(1) + "%" })]),
        TD.el("span", { class: "val", text: score.toFixed(3) })
      ]);
    });
    if (!rows.length) {
      rows.push(TD.el("div", { class: "hint", text: "这一步没有排序明细。" }));
    }
    return rows;
  }

  function fastLane(episode) {
    var guiSteps = (episode.steps_detail || []).filter(function (step) { return step.kind === "gui"; });
    var blocks = guiSteps.slice(0, 12).map(function (step) {
      var funnel = TD.el("div", { class: "small dim", style: "margin-bottom:4px" },
        "候选 " + (step.n_candidates || 0) + " 个 · 节点 " +
        ((episode.frames || []).length ? "—" : "—") +
        " · 延迟 " + (step.ranking && step.ranking.latency_ms !== undefined ? step.ranking.latency_ms + " ms" : "—") +
        " · margin " + (step.ranking && step.ranking.operation_margin !== undefined ? step.ranking.operation_margin : "—") +
        (step.noop ? " · 空转（动作编译不出来）" : ""));
      return TD.el("div", { style: "margin-bottom:14px" }, [
        TD.el("div", { class: "mono dim", style: "font-size:11px", text: "step " + step.step }),
        funnel
      ].concat(candidateRows(step)));
    });
    if (!blocks.length) {
      blocks.push(TD.el("div", { class: "hint", text: "这一题没有 GUI 排序事件。" }));
    }
    return TD.el("div", { class: "lane fast" }, [
      TD.el("h3", { text: "快模型（小脑）· 排序实况（softmax 相对强度，非校准概率）" })
    ].concat(blocks));
  }

  function frameLane(episode) {
    var frames = episode.frames || [];
    if (!frames.length) {
      return TD.el("div", { class: "lane" }, [TD.el("h3", { text: "帧序列" }),
        TD.el("div", { class: "hint", text: "这一题没有落盘截图（未进入决策步）。" })]);
    }
    var images = frames.slice(0, 40).map(function (frame) {
      if (!frame.src) {
        return TD.el("div", { class: "hint", text: "step " + frame.step_idx + " 帧未收录（只给对比子集生成缩放帧）" });
      }
      return TD.el("img", { src: frame.src, alt: "step " + frame.step_idx,
        title: "step " + frame.step_idx + " · a11y 节点 " + (frame.node_count || "?") });
    });
    return TD.el("div", { class: "lane" }, [
      TD.el("h3", { text: "帧序列（离散帧，非录屏）" }),
      TD.el("div", { class: "frames" }, images)
    ]);
  }

  function loopPanel(episode) {
    var steps = episode.steps_detail || [];
    var nodes = [];
    steps.slice(0, 24).forEach(function (step) {
      var kind = step.kind;
      var cls = "node";
      var label = kind;
      if (kind === "gui_verified" || kind === "cli_verified") {
        var outcome = (step.verification || {}).outcome;
        cls += outcome === "achieved" ? " ok" : " no";
        label = "核验:" + (outcome || "?");
      } else if (kind === "stage_replan") {
        cls += " replan";
        label = "重规划:" + (step.reason || "?");
      } else if (kind === "planner") {
        label = "规划";
      } else if (kind === "stage_local") {
        label = "阶段动作";
      } else if (kind === "stage_progress") {
        label = "里程碑进度";
      }
      nodes.push(TD.el("div", { class: cls, title: "step " + step.step,
        text: label + " · " + step.step }));
    });
    return TD.el("div", { class: "lane" }, [
      TD.el("h3", { text: "plan → act → verify → replan 闭环（原生 stage_replan 事件）" }),
      TD.el("div", { class: "loop" }, nodes)
    ]);
  }

  function requirementPanel(episode) {
    var reqs = episode.requirements || [];
    var items = reqs.map(function (req) {
      var status = String(req.status || "?");
      var cls = status === "achieved" || status === "pass" ? "good" : (status === "failed" ? "bad" : "dim");
      return TD.el("li", {}, [
        TD.el("span", { class: "st " + cls, text: status }),
        TD.el("span", { text: req.id }),
        TD.el("span", { class: "dim", text: (req.evidence || "").slice(0, 60) })
      ]);
    });
    return TD.el("div", { class: "lane" }, [
      TD.el("h3", { text: "需求逐条核验" }),
      items.length ? TD.el("ul", { class: "reqs" }, items)
                   : TD.el("div", { class: "hint", text: "没有 requirement_checks 记录。" })
    ]);
  }

  function costPanel(episode) {
    var tokens = episode.tokens || {};
    var fast = episode.fast_model || {};
    var total = (tokens.prompt || 0) + (tokens.completion || 0);
    var bars = TD.el("div", { class: "cost-bars" }, [
      TD.el("div", { class: "cost-bar" }, [
        TD.el("span", { text: "输入" }),
        TD.el("span", { class: "track" }, [TD.el("i", { style: "width:100%;background:var(--series-1)" })]),
        TD.el("span", { class: "num", text: TD.int(tokens.prompt) })
      ]),
      TD.el("div", { class: "cost-bar" }, [
        TD.el("span", { text: "输出" }),
        TD.el("span", { class: "track" }, [TD.el("i", { style: "width:" +
          (total ? (tokens.completion / total * 100).toFixed(1) : 0) + "%;background:var(--series-2)" })]),
        TD.el("span", { class: "num", text: TD.int(tokens.completion) })
      ]),
      TD.el("div", { class: "cost-bar" }, [
        TD.el("span", { text: "其中思考" }),
        TD.el("span", { class: "track" }, [TD.el("i", { style: "width:" +
          (tokens.completion ? (tokens.reasoning / tokens.completion * 100).toFixed(1) : 0) + "%;background:var(--series-4)" })]),
        TD.el("span", { class: "num", text: TD.int(tokens.reasoning) })
      ]),
      TD.el("div", { class: "cost-bar" }, [
        TD.el("span", { text: "缓存命中" }),
        TD.el("span", { class: "track" }, [TD.el("i", { style: "width:" +
          (tokens.prompt ? (tokens.cached / tokens.prompt * 100).toFixed(1) : 0) + "%;background:var(--series-3)" })]),
        TD.el("span", { class: "num", text: TD.int(tokens.cached) })
      ])
    ]);
    var usd = tokens.usd_estimate === null || tokens.usd_estimate === undefined
      ? "无价格表"
      : "$" + TD.num(tokens.usd_estimate, 4) + "（按 " + tokens.snapshot + " 挂牌价）";
    return TD.el("div", { class: "lane" }, [
      TD.el("h3", { text: "成本流水" }),
      bars,
      TD.el("div", { class: "small dim", style: "margin-top:8px", text: "慢模型调用 " + TD.int(tokens.calls) + " 次 · " + usd }),
      TD.el("div", { class: "small dim", text:
        "快模型（本地 GPU）：排序 " + TD.int(fast.rank_calls) + " 次 · 累计 " +
        TD.int(fast.rank_ms_total) + " ms —— 不折美元，成本不进美元轴。" })
    ]);
  }

  function scorePanel(episode) {
    var evaluator = episode.evaluator || {};
    return TD.el("div", { class: "lane" }, [
      TD.el("h3", { text: "评估" }),
      TD.el("div", { class: "kpis" }, [
        TD.kpi("分数", episode.score === null ? "未出分" : TD.num(episode.score, 4),
          episode.stop_reason || "", episode.score ? "good" : "bad"),
        TD.kpi("步数", TD.int(episode.steps), "墙钟 " + (episode.wall_seconds ? (episode.wall_seconds / 60).toFixed(0) + " 分" : "—")),
        TD.kpi("空转率", episode.noop_rate === null ? "—" : TD.pct(episode.noop_rate, 1),
          episode.decisions ? episode.noop_decisions + "/" + episode.decisions + " 次决策" : "")
      ]),
      TD.el("div", { class: "small dim", style: "margin-top:8px",
        text: "评测器：" + (evaluator.source || "未知") +
          (evaluator.native ? "（原生官方评测器 → 与官方榜同口径可比）" : "（非原生 → 不可与官方榜直接比）") }),
      episode.error ? TD.el("div", { class: "callout bad", style: "margin-top:8px",
        text: episode.exception_type + "：" + String(episode.error).slice(0, 220) }) : null
    ]);
  }

  window.TD.player = {
    renderDual: function (center, episode) {
      TD.clear(center);
      center.appendChild(TD.el("div", { class: "card" }, [
        TD.el("h2", { text: "题 " + episode.task_id + " · " + (episode.domain || "") }),
        TD.el("div", { class: "small dim", text: episode.instruction || "" })
      ]));
      center.appendChild(TD.el("div", { class: "dual" }, [
        slowLane(episode), fastLane(episode), frameLane(episode)
      ]));
    },
    renderSide: function (side, episode) {
      TD.clear(side);
      side.appendChild(scorePanel(episode));
      side.appendChild(loopPanel(episode));
      side.appendChild(requirementPanel(episode));
      side.appendChild(costPanel(episode));
    }
  };
})();
