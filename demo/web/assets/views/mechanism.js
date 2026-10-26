/* 机制视图：快慢双模怎么协同 + **真实 case 的多泳道可视化**
 *
 * 泳道从上到下：慢模型输出 → 快模型排序 → 实际动作 → 核验 → 成本/用时。
 * 横向是时间（每列一步），点格子看细节。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function laneCell(text, cls, title) {
    return TD.el("div", { class: "lane-cell " + (cls || ""), title: title || text || "", text: text || "" });
  }

  function swimlane(episode, container) {
    var timeline = episode.timeline || [];
    if (!timeline.length) {
      container.appendChild(TD.el("div", { class: "callout", text: "这一题没有事件流。" }));
      return;
    }
    var lanes = [
      { key: "slow", label: "慢模型（大脑）", hint: "原文摘要 · role · token" },
      { key: "fast", label: "快模型（小脑）", hint: "候选数 · 赢家 · margin · 延迟" },
      { key: "action", label: "实际动作", hint: "编译出来的可执行动作" },
      { key: "verify", label: "核验", hint: "outcome / replan" },
      { key: "cost", label: "花费 / 用时", hint: "每步美元与墙钟" }
    ];

    var grid = TD.el("div", { class: "swim" });
    grid.appendChild(TD.el("div", { class: "swim-head" }, [TD.el("span", { class: "lane-name", text: "步骤" })]));
    timeline.forEach(function (entry, index) {
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
    container.appendChild(grid);
    container.appendChild(TD.el("div", { class: "swim-legend" }, [
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--s4) 55%, var(--surface-1))" }), document.createTextNode("慢模型输出")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--s2) 55%, var(--surface-1))" }), document.createTextNode("快模型排序")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--s1) 45%, var(--surface-1))" }), document.createTextNode("执行动作")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--bad) 55%, var(--surface-1))" }), document.createTextNode("核验未达成")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--warn) 55%, var(--surface-1))" }), document.createTextNode("空转 / 重规划")])
    ]));
  }

  TD.views.mechanism = function (container) {
    var overview = TD.state.overview;
    var compare = TD.state.compare;
    if (!overview) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的总览数据。" }));
      return;
    }

    container.appendChild(TD.el("section", { class: "hero" }, [
      TD.el("div", { class: "eyebrow", text: "MECHANISM" }),
      TD.el("h1", { text: "快慢双模怎么协同" }),
      TD.el("p", { class: "lede", html:
        "慢模型（大脑）一步一次规划、给目标与预期结果；快模型（小脑）只在候选空间里排序选一个赢家。" +
        "下面是一条<em>真实 case</em> 的泳道：每列一步，五条泳道分别是慢模型输出、快模型排序、" +
        "实际动作、核验与花费用时。" })
    ]));

    container.appendChild(TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "grid cols-2" }, [
        TD.el("div", {}, [
          TD.el("h3", { style: "font-size:16px;margin-bottom:8px", text: "慢模型（大脑 · MiniMax-M3.1-Flash）" }),
          TD.el("div", { class: "small", style: "color:var(--text-2)", text:
            "一步一次规划：给当前观察定目标与预期结果，产出候选动作提案。stage 模式下先拆里程碑" +
            "（stage_goal + milestones），每个里程碑内连续执行动作，核验不通过就按 stage_replan 重规划。" }),
          TD.el("div", { class: "small", style: "color:var(--text-2);margin-top:10px", text:
            "本批 reasoning_effort=max：输出 token 里 87% 是思考 token——成本优化的第一刀在这里。" })
        ]),
        TD.el("div", {}, [
          TD.el("h3", { style: "font-size:16px;margin-bottom:8px", text: "快模型（小脑 · JEV / qwen-jev-choice）" }),
          TD.el("div", { class: "small", style: "color:var(--text-2)", text:
            "只做一件事：在慢模型给的候选空间里排序并选一个赢家（先选 operation，再选 target）。" +
            "它不规划、不纠错——但它选错，agent 就会空转。" }),
          TD.el("div", { class: "small", style: "color:var(--text-2);margin-top:10px", text:
            "排序分数是 softmax（相对强度，非校准概率）；延迟与 margin 都记在事件里。" })
        ])
      ])
    ]));

    /* 选一条我们成功的 case 做泳道 */
    var candidates = (compare.rows || []).filter(function (row) {
      return row.group && row.ours !== null && row.ours > 0;
    });
    var picker = TD.el("select", { class: "ghost" }, candidates.map(function (row) {
      return TD.el("option", { value: row.task, text: "题 " + row.task + "（我们 " + row.ours.toFixed(3) + " / Sai " + (row.sai_best || 0).toFixed(3) + "）" });
    }));
    var stage = TD.el("div");
    var panel = TD.el("div", { class: "panel", style: "margin-top:18px" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "真实 case 泳道" }),
        TD.el("span", { class: "hint", text: "选一道题" }),
        picker
      ])
    ]);
    container.appendChild(panel);
    container.appendChild(stage);

    function load(taskId) {
      var row = candidates.filter(function (item) { return item.task === taskId; })[0] || {};
      TD.clear(stage);
      stage.appendChild(TD.el("div", { class: "panel" }, [TD.el("h2", { text: "载入中…" })]));
      TD.loadEpisode(row.run_id || "", taskId, function (episode, error) {
        TD.clear(stage);
        if (!episode) {
          stage.appendChild(TD.el("div", { class: "callout bad", text:
            "载入逐题数据失败：" + (error || "未知错误") + "（file:// 下会被浏览器拦，请用 http.server 打开）" }));
          return;
        }
        var box = TD.el("div", { class: "panel", style: "margin-top:18px" }, [
          TD.el("div", { class: "panel-head" }, [
            TD.el("h2", { text: "题 " + taskId + " 泳道" }),
            TD.el("span", { class: "hint", text:
              (episode.timeline_totals || {}).steps + " 步 · 合计 $" +
              ((episode.timeline_totals || {}).cost_usd || 0).toFixed(4) + " · " +
              (((episode.timeline_totals || {}).elapsed_ms || 0) / 1000).toFixed(0) + "s" })
          ])
        ]);
        swimlane(episode, box);
        stage.appendChild(box);
      });
    }
    picker.addEventListener("change", function () { load(picker.value); });
    if (candidates.length) load(candidates[0].task);

    /* 失败模式解剖 */
    var buckets = {};
    (overview.rows || []).forEach(function (row) {
      var key = row.status === "scored"
        ? (row.score >= 1 ? "完成且满分" : (row.score > 0 ? "完成但部分分" : "完成却零分"))
        : (row.stop === "wall_time_limit" ? "墙钟耗尽"
          : (row.stop === "no_action_limit" ? "空转过多" : "异常未出分"));
      (buckets[key] = buckets[key] || []).push(row.task);
    });
    var failRows = Object.keys(buckets).map(function (name) {
      return [name, { text: String(buckets[name].length), num: true },
              { text: buckets[name].join(" "), class: "dim" }];
    });
    container.appendChild(TD.el("div", { class: "panel", style: "margin-top:18px" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "终态解剖（按落盘证据分组）" }),
        TD.el("span", { class: "hint", text: "未出分单独成类" })
      ]),
      TD.table([{ label: "终态" }, { label: "题数", num: true }, { label: "题号" }], failRows),
      TD.el("div", { class: "callout bad", style: "margin-top:16px" }, [
        TD.el("strong", { text: "“完成却零分”最值得看：" }),
        TD.el("span", { text:
          "planner 说做完、verifier 也确认了，官方评测器却判 0 分——完成判定与评测口径不一致。" +
          "另有 " + compare.unscored_sai_full + " 道未出分的题官方 Sai 拿满分：API / 判分侧失败。" })
      ])
    ]));
  };
})();
