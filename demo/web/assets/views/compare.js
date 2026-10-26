/* 官方对照视图：我们 vs 官方 harness（Sai w/ Claude Opus 5）—— MVP 的核心
 *
 * 这一页能站住的前提（三处口径声明都在页面上）：
 * 1. **同 release**：双方都是 OSWorld v2.1，同题号；
 * 2. **同评测器**：双方都是原生官方评测器（不是 LLM judge）；
 * 3. **底座不同**：我们 MiniMax-M3.1-Flash，Sai 用 Claude Opus 5 —— 成本差主要来自底座。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function groupTag(group) {
    return group ? TD.tag(group, "group") : TD.el("span", { class: "dim", text: "—" });
  }

  function deltaCell(row) {
    if (row.delta === null || row.delta === undefined) {
      return { text: "—", class: "dim" };
    }
    if (row.tie) return { text: "打平", class: "good" };
    return { text: "-" + row.delta.toFixed(3), class: "bad" };
  }

  function saiTrajectoryPanel(taskId) {
    var panel = TD.el("div", { class: "card", style: "margin-top:10px" });
    panel.appendChild(TD.el("h2", { text: "Sai 侧轨迹（" + taskId + "）" }));
    var body = TD.el("div", { class: "hint", text: "载入中…" });
    panel.appendChild(body);
    if (typeof fetch !== "function") {
      body.textContent = "当前环境没有 fetch，无法载入官方轨迹。";
      return panel;
    }
    fetch("assets/data/sai_traj/" + taskId + ".json").then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (data) {
      TD.clear(body);
      body.className = "";
      body.appendChild(TD.el("div", { class: "small dim", text:
        "官方参考 run " + data.run + " · 该次得分 " + TD.num(data.score) + " · " +
        (data.steps || []).length + " 步（来自 HuggingFace 公开参考 run）" }));
      var rows = (data.steps || []).slice(0, 60).map(function (step) {
        return [
          { text: String(step.step_num), num: true },
          { text: String(step.action || step.osworld_action || "—").slice(0, 90) },
          { text: step.reward === null || step.reward === undefined ? "—" : String(step.reward), num: true }
        ];
      });
      body.appendChild(TD.table(
        [{ label: "#", num: true }, { label: "动作" }, { label: "reward", num: true }], rows
      ));
      if ((data.steps || []).length > 60) {
        body.appendChild(TD.el("div", { class: "hint", text: "（只列前 60 步）" }));
      }
    }).catch(function (error) {
      body.className = "callout info";
      body.textContent = "载入官方轨迹失败：" + error.message +
        "。用 file:// 打开时浏览器会拦截本地 fetch——请用 python3 -m http.server 打开。";
    });
    return panel;
  }

  TD.views.compare = function (container) {
    var data = TD.state.compare;
    if (!data) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的对照数据——请用构建脚本生成站点。" }));
      return;
    }
    var rows = data.rows || [];
    var subsetRows = rows.filter(function (row) { return row.group; });
    var shown = subsetRows.length ? subsetRows : rows;

    container.appendChild(TD.card("官方 harness 对照（同 release · 同原生评测器 · 同题号）", [
      TD.el("div", { class: "kpis" }, [
        TD.kpi("共同已出分题", TD.int(data.common_scored), "我们与 Sai 都有分"),
        TD.kpi("我们均分", TD.num(data.ours_mean, 4), "仅共同已出分题"),
        TD.kpi("Sai 最佳均分", TD.num(data.sai_mean_best, 4), "官方参考 run 每题最佳干净运行"),
        TD.kpi("逐题打平", TD.int(data.ties), "我们与 Sai 最佳分逐位相同"),
        TD.kpi("我们领先", TD.int(data.we_lead), "如实计数：0 题", data.we_lead ? "good" : "warn"),
        TD.kpi("成本比", data.cost_ratio ? "1/" + data.cost_ratio : "—",
          "我们 $" + TD.num(data.ours_usd_per_task, 3) + " vs Sai $" + TD.num(data.sai_usd_per_task, 2) + "/题", "warn")
      ]),
      TD.el("div", { class: "callout", style: "margin-top:12px" }, [
        TD.el("strong", { text: "三处口径差异（每次对比都适用）：" }),
        TD.el("ul", { style: "margin:6px 0 0;padding-left:18px" }, [
          TD.el("li", { text: "底座不同：我们 MiniMax-M3.1-Flash，Sai 用 Claude Opus 5 —— 成本差 1/" + (data.cost_ratio || "?") + " 主要来自底座，不是 harness 更省。" }),
          TD.el("li", { text: "题集不同：我们只尝试 " + (data.ours_attempted || 0) + " 题，Sai 覆盖 108 题全量；未出的 23 题我们按「未出分」处理，不折算 0。" }),
          TD.el("li", { text: "我们 " + (data.ours_unscored || 0) + " 题未出分（多为 API 不可用 / 判分失败），其中 " + (data.unscored_sai_full || 0) + " 题 Sai 拿满分 —— 这是基础设施失败，不是能力差距。" })
        ])
      ])
    ], "只挑一部分题做对照，不做全量比较"));

    var tableRows = shown.map(function (row) {
      return [
        { text: row.task, num: true },
        groupTag(row.group),
        { text: row.ours === null || row.ours === undefined ? "未出分" : TD.num(row.ours, 4),
          class: row.ours === null || row.ours === undefined ? "dim" : "" },
        { text: row.ours_stop || "—" },
        { text: TD.num(row.sai_best, 4), num: true },
        { text: TD.num(row.sai_mean, 4), num: true },
        deltaCell(row),
        { text: TD.int(row.ours_tokens), num: true },
        { text: row.ours_noop_rate === null || row.ours_noop_rate === undefined ? "—" : TD.pct(row.ours_noop_rate, 0), num: true }
      ];
    });
    container.appendChild(TD.card("逐题对照（对比子集）", [
      TD.table(
        [{ label: "题", num: true }, { label: "组" }, { label: "我们" }, { label: "我们的停止原因" },
         { label: "Sai 最佳", num: true }, { label: "Sai 均值", num: true }, { label: "差距", num: true },
         { label: "我们的 token", num: true }, { label: "空转率", num: true }],
        tableRows
      ),
      TD.el("div", { class: "hint", style: "margin-top:8px" },
        "差距 = Sai 最佳 − 我们（正数 = 我们落后）。打平 = 逐位相同。")
    ], "点题号看轨迹对照"));

    var detail = TD.el("div");
    container.appendChild(detail);
    container.appendChild(saiTrajectoryPanel(shown.length ? shown[0].task : "004"));
    detail.addEventListener("click", function (event) {
      var cell = event.target.closest("td");
      if (!cell) return;
      var index = Array.prototype.indexOf.call(cell.parentNode.children, cell);
      var row = shown[index];
      if (!row) return;
      var panels = container.querySelectorAll(".card");
      var last = panels[panels.length - 1];
      if (last) last.replaceWith(saiTrajectoryPanel(row.task));
    });
  };
})();
