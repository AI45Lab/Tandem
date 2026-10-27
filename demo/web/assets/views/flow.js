/* 机制段的图形层：概念流程图 + 迷你数据图（纯 SVG，无依赖）。
 *
 * 概念流程图讲的是"双模怎么接力"：
 *   观察 → 慢模型规划 → 候选空间 → 快模型排序 → 执行动作 → 核验
 *                                                     ↑ 不通过
 *                                          重规划 ←───┘
 * 节点上带**这条真实 case 的数字**（候选数 / margin / 延迟 / 步号 / 核验结论），
 * 节点可 hover、点击（点击切到右侧对应步骤）。
 */
(function () {
  "use strict";
  var TD = window.TD;
  var NS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs, children) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "text") node.textContent = String(value);
      else if (key.indexOf("on") === 0 && typeof value === "function") {
        node.addEventListener(key.slice(2), value);
      } else node.setAttribute(key, String(value));
    });
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }

  function nodeBox(x, y, width, height, label, sub, tone, index, onSelect) {
    var group = svg("g", {
      class: "fnode " + (tone || ""),
      tabindex: "0",
      role: "button",
      "aria-label": label + (sub ? "：" + sub : ""),
      onclick: function () { onSelect(index); },
      onkeydown: function (event) {
        if (event.key === "Enter" || event.key === " ") { onSelect(index); }
      }
    });
    group.appendChild(svg("rect", { class: "fnode-box", x: x, y: y, width: width, height: height, rx: 12 }));
    group.appendChild(svg("text", { class: "fnode-label", x: x + width / 2, y: y + 26, "text-anchor": "middle", text: label }));
    if (sub) {
      group.appendChild(svg("text", { class: "fnode-sub", x: x + width / 2, y: y + 46, "text-anchor": "middle", text: sub }));
    }
    group.appendChild(svg("text", { class: "fnode-idx", x: x + 10, y: y + 18, text: String(index + 1).padStart(2, "0") }));
    return group;
  }

  function edge(path, tone) {
    var group = svg("g", { class: "fedge " + (tone || "") });
    group.appendChild(svg("path", { class: "fedge-line", d: path }));
    group.appendChild(svg("path", { class: "fedge-flow", d: path }));
    return group;
  }

  /* 概念流程图：返回 { node, setActive }，setActive(index) 高亮对应节点 */
  function concept(steps, facts, onSelect) {
    var width = 1240;
    var height = 260;
    var boxW = 168;
    var boxH = 68;
    var gap = (width - 60 - boxW * 6) / 5;
    var y = 52;
    var x0 = 30;

    var svgNode = svg("svg", {
      class: "flow",
      viewBox: "0 0 " + width + " " + height,
      preserveAspectRatio: "xMidYMid meet",
      role: "img",
      "aria-label": "快慢双模协同流程图"
    });

    /* 背景网格 */
    var grid = svg("g", { class: "fgrid" });
    for (var gx = 0; gx <= width; gx += 40) {
      grid.appendChild(svg("line", { x1: gx, y1: 0, x2: gx, y2: height }));
    }
    for (var gy = 0; gy <= height; gy += 40) {
      grid.appendChild(svg("line", { x1: 0, y1: gy, x2: width, y2: gy }));
    }
    svgNode.appendChild(grid);

    var positions = [];
    for (var i = 0; i < 6; i += 1) {
      positions.push(x0 + i * (boxW + gap));
    }
    var midY = y + boxH / 2;

    /* 主链 */
    for (var e = 0; e < positions.length - 1; e += 1) {
      var x1 = positions[e] + boxW;
      var x2 = positions[e + 1];
      var mid = (x1 + x2) / 2;
      svgNode.appendChild(edge("M " + x1 + " " + midY + " C " + mid + " " + midY + ", " + mid + " " + midY + ", " + x2 + " " + midY));
    }

    /* 节点（数据来自真实 case） */
    var labels = [
      { label: "观察", sub: facts.observed || "当前屏幕 + 任务状态" },
      { label: "慢模型 · 规划", sub: facts.plan || "目标 + 预期结果 + 提案" },
      { label: "候选空间", sub: facts.candidates || "候选动作" },
      { label: "快模型 · 排序", sub: facts.rank || "operation → target" },
      { label: "执行动作", sub: facts.action || "送进 VM" },
      { label: "核验", sub: facts.verify || "达成 / 未达成" }
    ];
    var tones = ["", "slow", "wide", "fast", "act", "verify"];
    var groups = [];
    labels.forEach(function (item, index) {
      var group = nodeBox(positions[index], y, boxW, boxH, item.label, item.sub, tones[index], index, onSelect);
      groups.push(group);
      svgNode.appendChild(group);
    });

    /* 回环：核验不通过 → 重规划 → 回到慢模型 */
    var loopY = y + boxH + 78;
    var loopX = positions[4] + boxW / 2;
    var loopGroup = svg("g", { class: "fedge loop" });
    loopGroup.appendChild(svg("path", {
      class: "fedge-line dashed",
      d: "M " + loopX + " " + (y + boxH) + " C " + loopX + " " + loopY + ", " + (positions[1] + boxW / 2) + " " + loopY + ", " + (positions[1] + boxW / 2) + " " + (y + boxH)
    }));
    loopGroup.appendChild(svg("path", {
      class: "fedge-flow",
      d: "M " + loopX + " " + (y + boxH) + " C " + loopX + " " + loopY + ", " + (positions[1] + boxW / 2) + " " + loopY + ", " + (positions[1] + boxW / 2) + " " + (y + boxH)
    }));
    svgNode.appendChild(loopGroup);
    var loopLabel = svg("g", { class: "floop" });
    loopLabel.appendChild(svg("rect", { x: positions[3] + 20, y: loopY - 20, width: 150, height: 34, rx: 17 }));
    loopLabel.appendChild(svg("text", {
      x: positions[3] + 95, y: loopY + 2, "text-anchor": "middle", text: facts.replan || "核验不通过 → 重规划"
    }));
    svgNode.appendChild(loopLabel);

    return {
      node: svgNode,
      setActive: function (index) {
        groups.forEach(function (group, i) { group.classList.toggle("on", i === index); });
      }
    };
  }

  /* 迷你图：候选空间漏斗（a11y 节点 → 候选 → 赢家） */
  function funnel(facts) {
    var svgNode = svg("svg", { class: "mini", viewBox: "0 0 300 132", role: "img", "aria-label": "候选空间漏斗" });
    var rows = [
      { label: "a11y 节点", value: facts.nodes, color: "var(--surface-3)", wide: 1 },
      { label: "候选动作", value: facts.candidates, color: "var(--series-2)", wide: 0.42 },
      { label: "赢家", value: facts.winner, color: "var(--series-1)", wide: 0.16 }
    ];
    rows.forEach(function (row, index) {
      var y = 8 + index * 42;
      var w = 260 * (row.wide || 0.2);
      svgNode.appendChild(svg("rect", { class: "fbar", x: 20, y: y, width: w, height: 26, rx: 6, fill: row.color }));
      svgNode.appendChild(svg("text", { class: "flabel", x: 28, y: y + 18, text: row.label }));
      svgNode.appendChild(svg("text", { class: "fvalue", x: 20 + w + 10, y: y + 18, text: String(row.value) }));
    });
    return svgNode;
  }

  /* 迷你图：两阶段 softmax 排序条 */
  function rank(bars) {
    var svgNode = svg("svg", { class: "mini", viewBox: "0 0 300 132", role: "img", "aria-label": "快模型排序强度" });
    if (!bars || !bars.length) {
      svgNode.appendChild(svg("text", { class: "flabel", x: 20, y: 40, text: "（没有排序明细）" }));
      return svgNode;
    }
    bars.slice(0, 6).forEach(function (bar, index) {
      var y = 8 + index * 20;
      var w = Math.max(4, 200 * (bar.score || 0));
      svgNode.appendChild(svg("text", { class: "flabel", x: 20, y: y + 12, text: (bar.operation || "?") }));
      svgNode.appendChild(svg("rect", { class: "fbar", x: 92, y: y, width: w, height: 14, rx: 4, fill: index === 0 ? "var(--series-1)" : "var(--series-2)" }));
      svgNode.appendChild(svg("text", { class: "fvalue", x: 92 + w + 8, y: y + 12, text: (bar.score || 0).toFixed(3) }));
    });
    return svgNode;
  }

  /* 迷你图：逐条要求达成 */
  function requirements(requirements) {
    var svgNode = svg("svg", { class: "mini", viewBox: "0 0 300 132", role: "img", "aria-label": "要求达成情况" });
    if (!requirements || !requirements.length) {
      svgNode.appendChild(svg("text", { class: "flabel", x: 20, y: 40, text: "（没有 requirement_checks）" }));
      return svgNode;
    }
    requirements.slice(0, 6).forEach(function (req, index) {
      var y = 8 + index * 20;
      var ok = req.status === "achieved" || req.status === "pass";
      svgNode.appendChild(svg("text", { class: "flabel", x: 20, y: y + 12, text: String(req.id || "").slice(0, 18) }));
      svgNode.appendChild(svg("rect", {
        class: "fbar", x: 140, y: y, width: 120, height: 12, rx: 4,
        fill: ok ? "var(--good)" : "var(--bad)", opacity: ok ? 0.85 : 0.7
      }));
      svgNode.appendChild(svg("text", { class: "fvalue", x: 268, y: y + 12, text: String(req.status || "?") }));
    });
    return svgNode;
  }

  TD.flow = { concept: concept, funnel: funnel, rank: rank, requirements: requirements, svg: svg };
})();
