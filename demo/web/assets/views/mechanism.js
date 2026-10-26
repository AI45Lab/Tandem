/* 机制视图：快慢双模怎么协同 + 失败模式解剖
 *
 * 这一页不编故事，只把**落盘证据**摆出来：停止原因分布、失败分类、
 * 哪些题"声称完成却没得分"。失败不藏——藏了 demo 就没法用。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function classify(row) {
    if (row.status === "scored") {
      if (row.score >= 1) return { key: "done_full", label: "完成且满分", kind: "done" };
      if (row.score > 0) return { key: "done_partial", label: "完成但部分分", kind: "done" };
      return { key: "done_zero", label: "完成却零分", kind: "done" };
    }
    if (row.stop === "wall_time_limit") return { key: "wall_limit", label: "墙钟耗尽", kind: "wall" };
    if (row.stop === "no_action_limit") return { key: "no_action", label: "空转过多", kind: "wall" };
    if (row.stop === "exception") return { key: "exception", label: "异常未出分", kind: "exception" };
    return { key: "other", label: "其它", kind: "" };
  }

  TD.views.mechanism = function (container) {
    var overview = TD.state.overview;
    if (!overview) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的总览数据。" }));
      return;
    }
    var rows = overview.rows || [];
    var groups = {};
    rows.forEach(function (row) {
      var info = classify(row);
      (groups[info.key] = groups[info.key] || { label: info.label, kind: info.kind, tasks: [] }).tasks.push(row.task);
    });
    var order = ["done_full", "done_partial", "done_zero", "wall_limit", "no_action", "exception", "other"];

    container.appendChild(TD.card("快慢双模怎么协同", [
      TD.el("div", { class: "grid cols-2" }, [
        TD.el("div", {}, [
          TD.el("h3", { style: "margin:0 0 6px;font-size:13px", text: "慢模型（大脑 · MiniMax-M3.1-Flash）" }),
          TD.el("div", { class: "small dim", text:
            "一步一次规划：给当前观察定一个目标与预期结果，产出候选动作提案。" +
            "stage 模式下先拆里程碑（stage_goal + milestones），每个里程碑内连续执行动作，" +
            "核验不通过或状态偏离就按 stage_replan 事件重规划。" }),
          TD.el("div", { class: "small dim", style: "margin-top:8px", text:
            "本批 reasoning_effort=max：completion 里 87% 是思考 token —— 成本优化的第一刀在这里。" })
        ]),
        TD.el("div", {}, [
          TD.el("h3", { style: "margin:0 0 6px;font-size:13px", text: "快模型（小脑 · JEV / qwen-jev-choice）" }),
          TD.el("div", { class: "small dim", text:
            "只做一件事：在慢模型给的候选空间里排序并选一个赢家（两阶段：先选 operation，再选 target）。" +
            "它不规划、不纠错 —— 但它选错，agent 就会空转。" }),
          TD.el("div", { class: "small dim", style: "margin-top:8px", text:
            "排序分数是 softmax（相对强度，非校准概率）；延迟与 margin 都记在事件里。" })
        ])
      ])
    ], "机制的事实描述"));

    var failRows = order.filter(function (key) { return groups[key]; }).map(function (key) {
      var info = groups[key];
      return [
        { text: info.label },
        TD.tag(info.kind, info.kind),
        { text: String(info.tasks.length), num: true },
        { text: info.tasks.slice(0, 18).join(" ") + (info.tasks.length > 18 ? " …" : ""), class: "dim" }
      ];
    });
    container.appendChild(TD.card("失败模式解剖（按落盘证据分组）", [
      TD.table([{ label: "类别" }, { label: "终态" }, { label: "题数", num: true }, { label: "题号" }], failRows),
      TD.el("div", { class: "callout bad", style: "margin-top:12px" }, [
        TD.el("strong", { text: "“完成却零分”是最值得看的一类：" }),
        TD.el("span", { text:
          "planner 说做完了、verifier 也确认了，但官方评测器判 0 分——完成判定与评测口径不一致。" +
          "这类题在对比视图里对照 Sai 的同题分数最直观。" })
      ])
    ], "不藏失败"));

    container.appendChild(TD.card("怎么读这些数字", [
      TD.el("ul", { class: "small dim", style: "margin:0;padding-left:18px" }, [
        TD.el("li", { text: "Partial（已出分）只算有分的题；Partial（全题面）用尝试题数作分母；两者都不是官方榜的 108 题口径。" }),
        TD.el("li", { text: "未出分的题**不折算 0**：官方 Partial Score 的定义是 108 题逐题均值、未出分计 0，与我们的口径差在题集。" }),
        TD.el("li", { text: "墙钟耗尽（4h）与步数耗尽（500）分开看：本批墙钟是主约束，步数中位只有 98。" }),
        TD.el("li", { text: "空转口径：gui 事件里 action 编译不出来（action 为 null）即算空转，与 tools/batch_summary 一致。" })
      ])
    ]));
  };
})();
