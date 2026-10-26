/* 机制区的一部分：真实 case 的多泳道可视化
 *
 * 泳道从上到下：慢模型输出 → 快模型排序 → 实际动作 → 核验 → 花费/用时。
 * 横向是时间（每列一步）。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function laneCell(text, cls, title) {
    return TD.el("div", { class: "lane-cell " + (cls || ""), title: title || text || "", text: text || "" });
  }

  function swimlane(episode) {
    var timeline = episode.timeline || [];
    if (!timeline.length) return null;
    var lanes = [
      { key: "slow", label: "慢模型（大脑）", hint: "原文摘要 · role · token" },
      { key: "fast", label: "快模型（小脑）", hint: "候选数 · 赢家 · margin · 延迟" },
      { key: "action", label: "实际动作", hint: "编译出来的可执行动作" },
      { key: "verify", label: "核验", hint: "outcome / replan" },
      { key: "cost", label: "花费 / 用时", hint: "每步美元与墙钟" }
    ];

    var grid = TD.el("div", { class: "swim" });
    grid.appendChild(TD.el("div", { class: "swim-head" }, [TD.el("span", { class: "lane-name", text: "步骤" })]));
    timeline.forEach(function (entry) {
      grid.appendChild(TD.el("div", { class: "swim-head step", text: String(entry.step) }));
    });

    lanes.forEach(function (lane) {
      grid.appendChild(TD.el("div", { class: "swim-lane-name" }, [
        TD.el("b", { text: lane.label }),
        TD.el("span", { class: "dim", text: lane.hint })
      ]));
      timeline.forEach(function (entry) {
        var text = "";
        var cls = "";
        var title = "";
        if (lane.key === "slow") {
          var slow = entry.slow || {};
          text = slow.text ? slow.text.replace(/\s+/g, " ").slice(0, 120) : (slow.role || "—");
          cls = slow.text ? "s-slow" : "s-empty";
          title = (slow.role || "") + " · " + TD.int(slow.prompt_tokens) + " in / " +
                  TD.int(slow.completion_tokens) + " out";
        } else if (lane.key === "fast") {
          var fast = entry.fast || {};
          text = fast.n_candidates === undefined ? "—"
            : (fast.n_candidates + " 候选 → " + (fast.winner || "?") +
               " · margin " + (fast.operation_margin === undefined ? "—" : fast.operation_margin) +
               " · " + (fast.latency_ms === undefined ? "—" : fast.latency_ms + "ms"));
          cls = fast.n_candidates ? "s-fast" : "s-empty";
          title = fast.used_image ? "排序用了截图" : "排序只用了结构";
        } else if (lane.key === "action") {
          var action = entry.action;
          text = action ? JSON.stringify(action).slice(0, 90) : (entry.kind || "—");
          cls = entry.noop ? "s-noop" : "s-action";
          title = entry.noop ? "空转：动作没编译出来" : "";
        } else if (lane.key === "verify") {
          text = entry.outcome || (entry.kind === "stage_replan" ? "重规划" : "—");
          cls = entry.outcome === "achieved" ? "s-ok"
            : (entry.outcome ? "s-bad" : (entry.kind === "stage_replan" ? "s-replan" : "s-empty"));
        } else {
          text = "$" + (entry.cost_usd || 0).toFixed(4) + " · " +
                 ((entry.elapsed_ms || 0) / 1000).toFixed(1) + "s";
          cls = "s-cost";
          title = TD.int(entry.tokens) + " token";
        }
        grid.appendChild(laneCell(text, cls, title));
      });
    });
    grid.style.gridTemplateColumns = "210px repeat(" + timeline.length + ", 176px)";
    return grid;
  }

  TD.sections = TD.sections || {};
  TD.sections.swimlane = function (container, episode, taskLabel) {
    var grid = swimlane(episode);
    if (!grid) return;
    var totals = episode.timeline_totals || {};
    container.appendChild(TD.el("div", { class: "swim-wrap" }, [
      TD.el("div", { class: "swim-head-bar" }, [
        TD.el("b", { text: "真实 case 泳道 · " + (taskLabel || "") }),
        TD.el("span", { class: "dim", text:
          totals.steps + " 步 · 合计 $" + (totals.cost_usd || 0).toFixed(4) +
          " · " + ((totals.elapsed_ms || 0) / 1000).toFixed(0) + "s" })
      ]),
      grid
    ]));
  };
})();
