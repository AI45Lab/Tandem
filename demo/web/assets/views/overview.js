/* 总览视图：我们的成绩 + 官方 harness 参照 + 题矩阵 + 成本散点
 *
 * 口径纪律（红线）：
 * - 虚线只画**官方已发布**的参照值，不画我们的预测分；
 * - 未出分的题单独成列，**不折算 0**；
 * - 每一处对比旁都写清 release / 题集 / 步数预算的差异。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function stopKind(stop) {
    if (stop === "done") return "done";
    if (stop === "wall_time_limit") return "wall";
    if (stop === "exception") return "exception";
    return "";
  }

  function matrix(overview) {
    var rows = overview.rows || [];
    var subset = (overview.subset_tasks) || [];
    var cells = rows.map(function (row) {
      var kind = "s-zero";
      if (row.status !== "scored") kind = stopKind(row.stop) === "exception" ? "s-exc" : "s-wall";
      else if (row.score >= 1) kind = "s-full";
      else if (row.score > 0) kind = "s-part";
      else kind = "s-zero";
      if (subset.indexOf(row.task) >= 0) kind += " in-subset";
      return TD.el("div", {
        class: "cell " + kind,
        title: row.task + " · " + (row.score === null ? "未出分" : row.score.toFixed(3)) +
               " · " + (row.stop || "-"),
        text: row.task
      });
    });
    return TD.el("div", { class: "matrix" }, cells);
  }

  function stopBars(overview) {
    var stops = overview.ours.stop_reasons || {};
    var names = Object.keys(stops).sort(function (a, b) { return stops[b] - stops[a]; });
    var total = names.reduce(function (sum, name) { return sum + stops[name]; }, 0) || 1;
    var colors = { done: "var(--good)", wall_time_limit: "var(--warn)", exception: "var(--bad)" };
    var bar = TD.el("div", { class: "bar" }, names.map(function (name) {
      return TD.el("span", {
        style: "width:" + (stops[name] / total * 100).toFixed(2) + "%;background:" + (colors[name] || "var(--series-1)")
      });
    }));
    var legend = TD.el("div", { class: "bar-legend" }, names.map(function (name) {
      return TD.el("span", {}, [
        TD.el("i", { style: "background:" + (colors[name] || "var(--series-1)") }),
        document.createTextNode(name + " " + stops[name])
      ]);
    }));
    return TD.el("div", {}, [bar, legend]);
  }

  function scatter(overview) {
    var rows = overview.rows || [];
    var plotted = rows.filter(function (row) { return row.score !== null; });
    var maxTokens = plotted.reduce(function (max, row) {
      return Math.max(max, row.ours_tokens || 0);
    }, 1);
    var box = TD.el("div", { class: "scatter" });
    plotted.forEach(function (row) {
      var x = Math.sqrt(row.ours_tokens || 0) / Math.sqrt(maxTokens) * 96;
      var y = 96 - (row.score || 0) * 92;
      var dot = TD.el("div", {
        class: "dot" + (row.score ? "" : " zero"),
        style: "left:" + x.toFixed(2) + "%;bottom:" + y.toFixed(2) + "%;width:9px;height:9px;margin:-4px 0 0 -4px",
        title: row.task + " · 分数 " + TD.num(row.score) + " · token " + TD.int(row.ours_tokens)
      });
      box.appendChild(dot);
    });
    // 官方参照线（虚线 = 已发布值，不是我们的预测）
    var harness = (overview.official.harness || []).filter(function (row) {
      return row.partial_score !== null;
    });
    harness.forEach(function (row) {
      var y = 96 - (row.partial_score / 100) * 92;
      box.appendChild(TD.el("div", {
        class: "dot ref",
        style: "left:0;right:0;bottom:" + y.toFixed(2) + "%;height:0;border-radius:0;border-width:1px 0 0 0",
        title: row.model + " 官方 Partial " + row.partial_score
      }));
    });
    box.appendChild(TD.el("span", { class: "axis-x", text: "token（√刻度）→" }));
    box.appendChild(TD.el("span", { class: "axis-y", text: "score" }));
    return box;
  }

  function officialCard(overview) {
    var ours = overview.ours;
    var harness = overview.official.harness || [];
    var rows = harness.map(function (row) {
      return [
        { text: row.model },
        { text: row.step_budget === 500 ? "500" : String(row.step_budget), num: true },
        { text: TD.num(row.binary_accuracy, 2), num: true },
        { text: TD.num(row.partial_score, 2), num: true },
        row.cost_per_task_usd === null || row.cost_per_task_usd === undefined
          ? { text: "未发布", class: "dim" }
          : { text: "$" + TD.num(row.cost_per_task_usd, 2), num: true }
      ];
    });
    rows.unshift([
      { text: "我们（stage+memory）" },
      { text: "500", num: true },
      { text: TD.num(ours.binary_rate_attempted ? ours.binary_rate_attempted * 100 : null, 2), num: true },
      { text: TD.num(ours.partial_attempted ? ours.partial_attempted * 100 : null, 2), num: true },
      ours.usd_per_task === null ? { text: "无价格表", class: "dim" } : { text: "$" + TD.num(ours.usd_per_task, 3), num: true }
    ]);
    return TD.card("官方 harness 对照", [
      TD.table(
        [{ label: "条目" }, { label: "步数", num: true }, { label: "Binary %", num: true },
         { label: "Partial %", num: true }, { label: "$/题", num: true }],
        rows
      ),
      TD.el("div", { class: "hint", style: "margin-top:8px" },
        "release " + overview.official.release + " · 题集 " + overview.official.dataset_size +
        " 题 · 我们的题集只有 " + ours.attempted + " 题尝试（见首屏口径声明）。" +
        "官方成本含其自身工具费与缓存定价；我们的美元数只算 API token。")
    ], "同一 release、同步数预算；底座不同（我们 MiniMax-M3.1-Flash，官方为 Claude/GPT 等）");
  }

  TD.views.overview = function (container) {
    var overview = TD.state.overview;
    if (!overview) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的总览数据——请用构建脚本生成站点。" }));
      return;
    }
    var ours = overview.ours;

    var kpis = TD.el("div", { class: "kpis" }, [
      TD.kpi("尝试题数", TD.int(ours.attempted), ours.scored + " 题已出分"),
      TD.kpi("Partial（已出分）", TD.pct(ours.partial_scored), "只算有分的题"),
      TD.kpi("Partial（全题面）", TD.pct(ours.partial_attempted), "未出分不计入分母外，口径见声明"),
      TD.kpi("Binary", ours.binary + " 题", "逐题分恰好 1.00", ours.binary ? "good" : "bad"),
      TD.kpi("未出分", TD.int(ours.unscored), "基础设施/判分失败，不是能力差距", ours.unscored ? "bad" : ""),
      TD.kpi("慢模型 token", TD.int(ours.total_tokens), TD.int(ours.calls) + " 次调用"),
      TD.kpi("成本", ours.usd_per_task === null ? "无价格表" : "$" + TD.num(ours.usd_per_task, 3) + "/题",
        ours.price ? ("按 " + ours.price.snapshot + " 挂牌价估算 · " + ours.price.model) : "", "warn"),
      TD.kpi("总墙钟", TD.hours(ours.wall_seconds), "撞墙钟 = 预算主约束")
    ]);

    container.appendChild(TD.card("这一批是什么", [
      kpis,
      TD.el("div", { class: "hint", style: "margin-top:10px" },
        "数据源：stage+memory 批次（execution_mode=stage，500 步上限 / 4h 墙钟，" +
        "慢模型 MiniMax-M3.1-Flash（reasoning_effort=max），快模型 JEV，原生官方评测器）。" +
        "慢模型原文、排序明细、核验与 replan 全部在 events/llm_calls 里，可逐题回放。")
    ], "先看口径，再看数字"));

    container.appendChild(TD.el("div", { class: "grid cols-2", style: "margin-top:16px" }, [
      TD.card("题矩阵", [
        matrix(overview),
        TD.el("div", { class: "bar-legend" }, [
          TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--good) 75%, var(--surface-1))" }), document.createTextNode("满分")]),
          TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--good) 35%, var(--surface-1))" }), document.createTextNode("部分分")]),
          TD.el("span", {}, [TD.el("i", { style: "background:var(--surface-2)" }), document.createTextNode("零分")]),
          TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--warn) 32%, var(--surface-1))" }), document.createTextNode("撞墙钟")]),
          TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--bad) 42%, var(--surface-1))" }), document.createTextNode("异常未出分")]),
          TD.el("span", {}, [TD.el("i", { style: "background:transparent;border:1px solid var(--accent)" }), document.createTextNode("对比子集")])
        ])
      ], "每格 = 一题；边框高亮 = 进入官方对照子集"),
      TD.card("停止原因", [stopBars(overview),
        TD.el("div", { class: "hint", style: "margin-top:8px" },
          "墙钟耗尽远多于步数耗尽 → 约束是 4 小时墙钟，不是 500 步预算。")])
    ]));

    container.appendChild(TD.el("div", { class: "grid cols-2", style: "margin-top:16px" }, [
      TD.card("成本 × 分数", [scatter(overview),
        TD.el("div", { class: "hint", style: "margin-top:8px" },
          "虚线 = 官方已发布的 Partial 参照值（不是我们的预测）。红点 = 零分题。")]),
      officialCard(overview)
    ]));

    container.appendChild(TD.el("div", { class: "footer-note", text:
      "本站数字由 tools/batch_summary.py 统一计算，与 docs/ 基线报告同源；" +
      "官方数据快照与价格表带抓取日期，过期会提示核对。" }));
  };
})();
