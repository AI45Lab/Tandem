/* 总览：Hero → 大数字 → OSW2.1 风格对比表 → 战绩热力 → 官方对标 → 成本散点
 *
 * 版式原则：一屏一个论点；大字、少小字说明；口径差异写在对比表同一行里，
 * 不另开一块"注意事项"。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function countUp(node, target, opts) {
    opts = opts || {};
    var digits = opts.digits === undefined ? 2 : opts.digits;
    var suffix = opts.suffix || "";
    var prefix = opts.prefix || "";
    if (typeof target !== "number" || !isFinite(target)) {
      node.textContent = prefix + (target === null || target === undefined ? "—" : target) + suffix;
      return;
    }
    var start = performance.now();
    var dur = 900;
    function frame(now) {
      var p = Math.min(1, (now - start) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      node.textContent = prefix + (target * eased).toFixed(digits) + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function metric(label, foot, kind, animate) {
    var valueNode = TD.el("div", { class: "value" });
    var box = TD.el("div", { class: "metric " + (kind || "") }, [
      valueNode,
      TD.el("div", { class: "label", text: label }),
      foot ? TD.el("div", { class: "foot", text: foot }) : null
    ]);
    countUp(valueNode, animate.value, animate);
    return box;
  }

  function cellKind(row) {
    if (row.status !== "scored") return row.stop === "exception" ? "s-exc" : "s-wall";
    if (row.score >= 1) return "s-full";
    if (row.score > 0) return "s-part";
    return "s-zero";
  }

  /* ---------------------------------------------------------- 战绩热力 */
  function heat(overview) {
    var subset = overview.subset_tasks || [];
    var byDomain = {};
    (overview.rows || []).forEach(function (row) {
      var domain = row.domain || "other";
      (byDomain[domain] = byDomain[domain] || []).push(row);
    });
    var domains = Object.keys(byDomain).sort(function (a, b) {
      return byDomain[b].length - byDomain[a].length;
    });
    var rows = domains.map(function (domain) {
      var cells = byDomain[domain].sort(function (a, b) { return a.task < b.task ? -1 : 1; }).map(function (row, index) {
        var kind = cellKind(row);
        if (subset.indexOf(row.task) >= 0) kind += " in-subset";
        return TD.el("div", {
          class: "heat-cell " + kind,
          style: "animation-delay:" + (index * 12) + "ms",
          title: row.task + " · " + (row.score === null ? "未出分（" + (row.stop || "-") + "）" : row.score.toFixed(4)) +
                 " · 步数 " + (row.steps || 0),
          text: row.task
        });
      });
      return TD.el("div", { class: "heat-row" }, [
        TD.el("div", { class: "domain", text: domain + " · " + byDomain[domain].length }),
        TD.el("div", { class: "heat-strip" }, cells)
      ]);
    });
    var legend = TD.el("div", { class: "heat-legend" }, [
      TD.el("span", {}, [TD.el("i", { style: "background:var(--good)" }), document.createTextNode("满分")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--good) 42%, var(--surface-1))" }), document.createTextNode("部分分")]),
      TD.el("span", {}, [TD.el("i", { style: "background:var(--surface-3)" }), document.createTextNode("零分")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--warn) 45%, var(--surface-1))" }), document.createTextNode("撞墙钟")]),
      TD.el("span", {}, [TD.el("i", { style: "background:color-mix(in srgb, var(--bad) 55%, var(--surface-1))" }), document.createTextNode("异常未出分")]),
      TD.el("span", {}, [TD.el("i", { style: "background:transparent;border:1px solid var(--accent)" }), document.createTextNode("进入官方对照子集")])
    ]);
    return TD.el("div", {}, [TD.el("div", { class: "heat" }, rows), legend]);
  }

  /* ------------------------------------------------ OSW2.1 风格对比表 */
  function leaderboard(overview, compare) {
    var ours = overview.ours;
    var harness = overview.official.harness || [];
    var e2e = overview.official.e2e_background || [];
    var sai = null;
    var darwinx = null;
    harness.forEach(function (row) {
      if (!sai && /Sai/i.test(row.model)) sai = row;
      if (!darwinx && /Darwinx/i.test(row.model)) darwinx = row;
    });
    var opus5 = e2e.filter(function (row) { return /Opus 5/.test(row.model || ""); })[0];

    function row(name, model, release, steps, binary, partial, cost, note, ours_) {
      return [
        { text: name, class: ours_ ? "good" : "" },
        { text: model, class: "dim" },
        { text: release, class: "dim" },
        { text: String(steps), num: true },
        { text: binary === null ? "—" : binary.toFixed(2), num: true },
        { text: partial === null ? "—" : partial.toFixed(2), num: true },
        { text: cost === null ? "未发布" : "$" + cost.toFixed(cost < 1 ? 3 : 2), num: true },
        { text: note, class: "dim" }
      ];
    }

    var rows = [
      row("Tandem（我们）", "MiniMax-M3.1-Flash + JEV", "v2.1", 500,
        (ours.binary_rate_attempted || 0) * 100, (ours.partial_scored || 0) * 100,
        ours.usd_per_task,
        ours.attempted + " 题尝试 / " + ours.scored + " 题出分（分母与官方不同）", true)
    ];
    if (sai) {
      rows.push(row("Sai", "Claude Opus 5", sai.release || "v2.1", sai.step_budget,
        sai.binary_accuracy, sai.partial_score, sai.cost_per_task_usd, "108 题全量 · 官方 harness"));
    }
    if (darwinx) {
      rows.push(row("Darwinx", "Claude Opus 4.8", darwinx.release || "v2.1", darwinx.step_budget,
        darwinx.binary_accuracy, darwinx.partial_score, darwinx.cost_per_task_usd, "官方 harness"));
    }
    if (opus5) {
      rows.push(row("Claude Opus 5（背景）", "官方 runner 直跑", opus5.release || "v2.1", opus5.step_budget,
        opus5.binary_accuracy, opus5.partial_score, opus5.cost_per_task_usd, "非 harness 型，仅作参照"));
    }

    return TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "结果对比（OSWorld 2.1 · full set · 500 步）" }),
        TD.el("span", { class: "hint", text: "官方数据快照 " + (overview.official.snapshot || "—") })
      ]),
      TD.table(
        [{ label: "Agent" }, { label: "模型底座" }, { label: "Release" }, { label: "步数", num: true },
         { label: "Binary %", num: true }, { label: "Partial %", num: true }, { label: "$/题", num: true },
         { label: "备注" }],
        rows
      ),
      TD.el("div", { class: "small dim", style: "margin-top:14px", text:
        "Binary / Partial 均为官方口径（逐题分恰好 1.00 记为 Binary；Partial 是逐题浮分均值）。" +
        "我们的分母是 " + ours.attempted + " 道尝试题（未出分不折算 0，另计），官方是 108 题全量——" +
        "两者不可直接排名，只看量级与成本比。" +
        (compare.cost_ratio ? "成本比 1/" + compare.cost_ratio + "，但底座不同（M3.1-Flash vs Claude Opus 5）。" : "") })
    ]);
  }

  /* -------------------------------------------------------- 终态解剖 */
  function anatomy(overview) {
    var buckets = [
      { key: "done_full", label: "完成且满分", color: "var(--good)", rows: [] },
      { key: "done_partial", label: "完成但部分分", color: "color-mix(in srgb, var(--good) 45%, var(--surface-3))", rows: [] },
      { key: "done_zero", label: "完成却零分", color: "var(--surface-3)", rows: [] },
      { key: "wall", label: "墙钟耗尽", color: "var(--warn)", rows: [] },
      { key: "exception", label: "异常未出分", color: "var(--bad)", rows: [] },
      { key: "no_action", label: "空转过多", color: "var(--s2)", rows: [] }
    ];
    (overview.rows || []).forEach(function (row) {
      var key = row.status === "scored"
        ? (row.score >= 1 ? "done_full" : (row.score > 0 ? "done_partial" : "done_zero"))
        : (row.stop === "wall_time_limit" ? "wall"
          : (row.stop === "no_action_limit" ? "no_action"
            : (row.stop === "exception" ? "exception" : "done_zero")));
      var bucket = buckets.filter(function (b) { return b.key === key; })[0];
      if (bucket) bucket.rows.push(row);
    });
    var total = (overview.rows || []).length || 1;
    var bar = TD.el("div", { class: "stackbar" }, buckets.map(function (bucket) {
      if (!bucket.rows.length) return null;
      return TD.el("span", {
        style: "width:" + (bucket.rows.length / total * 100).toFixed(2) + "%;background:" + bucket.color,
        title: bucket.label + " " + bucket.rows.length + " 题"
      }, bucket.rows.length >= 3 ? [String(bucket.rows.length)] : []);
    }));
    var legend = TD.el("div", { class: "stack-legend" }, buckets.filter(function (b) { return b.rows.length; }).map(function (bucket) {
      return TD.el("span", {}, [
        TD.el("i", { style: "background:" + bucket.color }),
        document.createTextNode(bucket.label + " " + bucket.rows.length)
      ]);
    }));
    return TD.el("div", {}, [bar, legend]);
  }

  /* ---------------------------------------------------------- 散点 */
  function scatter(overview) {
    var rows = (overview.rows || []).filter(function (row) { return row.score !== null; });
    var maxTokens = rows.reduce(function (max, row) { return Math.max(max, row.ours_tokens || 0); }, 1);
    var box = TD.el("div", { class: "scatter" });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (value) {
      box.appendChild(TD.el("div", { class: "grid-line", style: "bottom:" + (value * 92) + "%" }));
      box.appendChild(TD.el("div", { class: "tick y", style: "bottom:" + (value * 92) + "%", text: value.toFixed(2) }));
    });
    rows.forEach(function (row, index) {
      var x = Math.sqrt(row.ours_tokens || 0) / Math.sqrt(maxTokens) * 96;
      var y = 96 - (row.score || 0) * 92;
      box.appendChild(TD.el("div", {
        class: "dot" + (row.score ? "" : " zero"),
        style: "left:" + x.toFixed(2) + "%;bottom:" + y.toFixed(2) + "%;animation-delay:" + (index * 8) + "ms",
        title: row.task + " · 分数 " + row.score.toFixed(3) + " · token " + TD.int(row.ours_tokens)
      }));
    });
    (overview.official.harness || []).forEach(function (row) {
      if (row.partial_score === null) return;
      var y = 96 - (row.partial_score / 100) * 92;
      box.appendChild(TD.el("div", { class: "refline", style: "bottom:" + y.toFixed(2) + "%" }, [
        TD.el("span", { text: row.model + " " + row.partial_score })
      ]));
    });
    box.appendChild(TD.el("div", { class: "tick x", style: "left:96%", text: "token（√刻度）" }));
    return box;
  }

  TD.views.overview = function (container) {
    var overview = TD.state.overview;
    var compare = TD.state.compare;
    if (!overview) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的总览数据——请用构建脚本生成站点。" }));
      return;
    }
    var ours = overview.ours;
    var price = ours.price || {};

    container.appendChild(TD.el("section", { class: "hero" }, [
      TD.el("div", { class: "eyebrow", text: "OSWorld 2.1 · stage + memory · 原生官方评测器" }),
      TD.el("h1", { text: "快慢双模 CUA Harness 的真实跑批结果" }),
      TD.el("p", { class: "lede", html:
        "慢模型（MiniMax-M3.1-Flash）做规划与纠错，快模型（JEV）只做候选排序。" +
        "本批 <em>" + ours.attempted + " 题</em>出分 <em>" + ours.scored + " 题</em>，" +
        "撞 4 小时墙钟 <em>" + (ours.stop_reasons.wall_time_limit || 0) + " 题</em>，" +
        "每题 API 成本 <em>$" + (ours.usd_per_task === null ? "—" : ours.usd_per_task.toFixed(3)) + "</em>。" })
    ]));

    container.appendChild(TD.el("div", { class: "metrics" }, [
      metric("Partial Score（已出分）", ours.scored + " 题的平均分", "accent",
        { value: ours.partial_scored * 100, digits: 2, suffix: "%" }),
      metric("Binary Accuracy", "逐题分恰好 1.00", ours.binary ? "good" : "bad",
        { value: ours.binary_rate_attempted * 100, digits: 2, suffix: "%" }),
      metric("每题成本", (price.model || "") + " · " + (price.snapshot || ""), "warn",
        { value: ours.usd_per_task || 0, digits: 3, prefix: "$" }),
      metric("对比官方 Sai", "官方 " + (compare.sai_usd_per_task ? "$" + compare.sai_usd_per_task.toFixed(2) : "—") + "/题", "",
        { value: compare.cost_ratio || 0, digits: 0, prefix: "1/" }),
      metric("未出分", "基础设施 / 判分失败，非能力差距", ours.unscored ? "bad" : "",
        { value: ours.unscored, digits: 0 })
    ]));

    container.appendChild(leaderboard(overview, compare));

    var board = TD.el("div", { class: "board", style: "margin-top:22px" });
    var left = TD.el("div", { class: "stack" });
    var right = TD.el("div", { class: "stack" });

    left.appendChild(TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "战绩（按域分行）" }),
        TD.el("span", { class: "hint", text: ours.attempted + " 题 · 悬停看详情" })
      ]),
      heat(overview)
    ]));

    left.appendChild(TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "终态解剖" }),
        TD.el("span", { class: "hint", text: "未出分单独成类，不折算 0" })
      ]),
      anatomy(overview),
      TD.el("div", { class: "callout bad", style: "margin-top:16px" }, [
        TD.el("strong", { text: "“完成却零分”最值得看：" }),
        TD.el("span", { text:
          "planner 说做完、verifier 也确认了，官方评测器却判 0 分——完成判定与评测口径不一致。" +
          "另有 " + compare.unscored_sai_full + " 道未出分的题，官方 Sai 拿满分：API / 判分侧失败。" })
      ])
    ]));

    right.appendChild(TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "成本 × 分数" }),
        TD.el("span", { class: "hint", text: "虚线 = 官方已发布 Partial" })
      ]),
      scatter(overview),
      TD.el("div", { class: "small dim", text: "横轴每题 token（平方根刻度），纵轴官方评分；红点为零分题。" })
    ]));

    board.appendChild(left);
    board.appendChild(right);
    container.appendChild(board);

    container.appendChild(TD.el("div", { class: "footer-note", text:
      "数据源：stage+memory 批次（execution_mode=stage · 500 步上限 / 4h 墙钟 · " +
      "慢模型 MiniMax-M3.1-Flash reasoning_effort=max · 快模型 JEV · 原生官方评测器）；" +
      "数字由 tools/batch_summary.py 统一计算；口径差异见对比表备注列。" }));
  };
})();
