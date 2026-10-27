/* 机制段的图形层：子任务循环流程图 + 迷你数据图（纯 SVG，无依赖）。
 *
 * 流程图讲的是**子任务循环**（这是 stage 模式真正的结构）：
 *
 *   慢模型·规划 ──► 快模型·完成子任务 ──► 快模型·排序 ──┐
 *        ▲                                          │
 *        │ 不符合预期 → 重规划/纠错                慢模型·验证
 *        └──────────────────────────────────────────┤
 *                                     子任务达成 ────┴──► 下一个子任务/任务完成
 *                                                          └──► 回到「完成子任务」
 *
 * 节点上的小字是**这条真实 case 的数字**（子任务数、候选数、排序延迟、核验结论、
 * 重规划原因），不是文案。节点可 hover、点击（点击切到右侧对应环节）。
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
        if (event.key === "Enter" || event.key === " ") onSelect(index);
      }
    });
    group.appendChild(svg("rect", { class: "fnode-box", x: x, y: y, width: width, height: height, rx: 12 }));
    group.appendChild(svg("text", { class: "fnode-label", x: x + width / 2, y: y + 25, "text-anchor": "middle", text: label }));
    if (sub) {
      group.appendChild(svg("text", { class: "fnode-sub", x: x + width / 2, y: y + 45, "text-anchor": "middle", text: sub }));
    }
    return group;
  }

  function edge(path, tone) {
    var group = svg("g", { class: "fedge " + (tone || "") });
    group.appendChild(svg("path", { class: "fedge-line", d: path }));
    group.appendChild(svg("path", { class: "fedge-flow", d: path }));
    return group;
  }

  function edgeLabel(x, y, text, tone) {
    var group = svg("g", { class: "fedge-label " + (tone || "") });
    group.appendChild(svg("rect", { x: x - 4, y: y - 11, width: text.length * 7 + 14, height: 22, rx: 11 }));
    group.appendChild(svg("text", { x: x + 3, y: y + 4, "text-anchor": "middle", text: text }));
    return group;
  }

  /* 子任务循环流程图。返回 { node, setActive } */
  function concept(facts, onSelect) {
    var width = 1240;
    var height = 300;
    var boxW = 250;
    var boxH = 74;
    var topY = 34;
    var botY = 196;
    var xs = [30, 340, 650, 960];
    var midY = topY + boxH / 2;

    var svgNode = svg("svg", {
      class: "flow",
      viewBox: "0 0 " + width + " " + height,
      preserveAspectRatio: "xMidYMid meet",
      role: "img",
      "aria-label": "快慢双模子任务循环流程图"
    });

    var grid = svg("g", { class: "fgrid" });
    for (var gx = 0; gx <= width; gx += 40) grid.appendChild(svg("line", { x1: gx, y1: 0, x2: gx, y2: height }));
    for (var gy = 0; gy <= height; gy += 40) grid.appendChild(svg("line", { x1: 0, y1: gy, x2: width, y2: gy }));
    svgNode.appendChild(grid);

    /* 节点：每个节点对应一个「环节」（点击切到粘性卡片对应环节） */
    var plan = facts.concept || {};
    var nodes = [
      { x: xs[0], y: topY, label: "慢模型 · 规划", sub: plan.plan || "拆解子任务 + 定目标", tone: "slow", step: 0 },
      { x: xs[1], y: topY, label: "快模型 · 完成子任务", sub: "候选空间：a11y 解析 + 慢模型", tone: "fast", step: 1 },
      { x: xs[2], y: topY, label: "快模型 · 排序", sub: plan.rank || "选出一个动作", tone: "fast", step: 1 },
      { x: xs[3], y: topY, label: "慢模型 · 验证", sub: plan.verify || "子任务是否达成", tone: "slow", step: 2 },
      { x: xs[0], y: botY, label: "重规划 / 纠错", sub: plan.replan || "换个目标再来", tone: "fix", step: 3 },
      { x: xs[2], y: botY, label: "下一个子任务 → 任务完成", sub: plan.next || "循环直到任务完成", tone: "done", step: 1 }
    ];

    /* 连线 */
    svgNode.appendChild(edge("M " + (xs[0] + boxW) + " " + midY + " L " + xs[1] + " " + midY));
    svgNode.appendChild(edge("M " + (xs[1] + boxW) + " " + midY + " L " + xs[2] + " " + midY));
    svgNode.appendChild(edge("M " + (xs[2] + boxW) + " " + midY + " L " + xs[3] + " " + midY));
    /* 验证 → 重规划（不符合预期） */
    svgNode.appendChild(edge(
      "M " + (xs[3] + boxW / 2) + " " + (topY + boxH) +
      " C " + (xs[3] + boxW / 2) + " " + (botY - 36) + ", " + (xs[0] + boxW / 2) + " " + (botY - 36) +
      ", " + (xs[0] + boxW / 2) + " " + botY, "warn"));
    /* 重规划 → 规划 */
    svgNode.appendChild(edge(
      "M " + (xs[0] + boxW / 2) + " " + botY +
      " C " + (xs[0] + boxW / 2) + " " + (botY - 50) + ", " + (xs[0] + boxW / 2) + " " + (topY + boxH + 30) +
      ", " + (xs[0] + boxW / 2) + " " + (topY + boxH), "warn"));
    /* 验证 → 下一个子任务（达成） */
    svgNode.appendChild(edge(
      "M " + (xs[3] + boxW / 2) + " " + (topY + boxH) +
      " C " + (xs[3] + boxW / 2) + " " + (topY + boxH + 40) + ", " + (xs[2] + boxW / 2) + " " + (topY + boxH + 40) +
      ", " + (xs[2] + boxW / 2) + " " + botY));
    /* 下一个子任务 → 完成子任务 */
    svgNode.appendChild(edge(
      "M " + xs[2] + " " + (botY + boxH / 2) +
      " C " + (xs[1] + boxW + 20) + " " + (botY + boxH / 2) + ", " + (xs[1] + boxW / 2) + " " + (botY + 20) +
      ", " + (xs[1] + boxW / 2) + " " + (topY + boxH), "loopback"));

    svgNode.appendChild(edgeLabel(xs[3] + boxW / 2 - 70, topY + boxH + 26, "不符合预期", "warn"));
    svgNode.appendChild(edgeLabel(xs[2] + boxW / 2 + 90, topY + boxH + 26, "子任务达成", "good"));
    svgNode.appendChild(edgeLabel(xs[1] - 40, botY - 26, "下一个子任务", "accent"));
    svgNode.appendChild(edgeLabel(xs[0] + boxW / 2 + 66, botY - 26, "重规划 / 纠错", "warn"));

    var groups = [];
    nodes.forEach(function (item, index) {
      var group = nodeBox(item.x, item.y, boxW, boxH, item.label, item.sub, item.tone, item.step, onSelect);
      groups.push(group);
      svgNode.appendChild(group);
    });

    return {
      node: svgNode,
      setActive: function (index) {
        groups.forEach(function (group, i) { group.classList.toggle("on", nodes[i].step === index); });
      }
    };
  }

  /* 迷你图：快模型的候选选择方块（赢家高亮） */
  function choiceBlocks(bars, winner) {
    var wrap = TD.el("div", { class: "choices" });
    if (!bars || !bars.length) {
      wrap.appendChild(TD.el("div", { class: "hint", text: "（没有排序明细）" }));
      return wrap;
    }
    var max = Math.max.apply(null, bars.map(function (bar) { return bar.score || 0; })) || 1;
    bars.slice(0, 6).forEach(function (bar, index) {
      var picked = index === 0 || (winner && bar.operation === winner);
      var width = 18 + 82 * ((bar.score || 0) / max);
      wrap.appendChild(TD.el("div", { class: "choice" + (picked ? " picked" : "") }, [
        TD.el("div", { class: "choice-name", text: bar.operation || "?" }),
        TD.el("div", { class: "choice-bar" }, [
          TD.el("i", { style: "width:" + width.toFixed(1) + "%" })
        ]),
        TD.el("div", { class: "choice-score", text: (bar.score || 0).toFixed(3) }),
        picked ? TD.el("div", { class: "choice-pick", text: "✔ 选中" }) : null
      ]));
    });
    return wrap;
  }

  /* 迷你图：截图条（Task 001 的帧） */
  function frameStrip(frames, current) {
    var strip = TD.el("div", { class: "strip" });
    var list = (frames || []).slice(0, 12);
    if (!list.length) {
      strip.appendChild(TD.el("div", { class: "hint", text: "（这一题没有落盘帧）" }));
      return strip;
    }
    list.forEach(function (frame) {
      var img = TD.el("img", {
        src: frame.src, alt: "step " + frame.step_idx,
        title: "step " + frame.step_idx + " · a11y 节点 " + (frame.node_count || "?")
      });
      if (current !== undefined && frame.step_idx === current) img.className = "current";
      strip.appendChild(img);
    });
    return strip;
  }

  /* 迷你图：子任务拆解（慢模型规划的里程碑） */
  function milestones(milestones) {
    var wrap = TD.el("div", { class: "choices" });
    if (!milestones || !milestones.length) {
      wrap.appendChild(TD.el("div", { class: "hint", text: "（这一步没有拆出子任务）" }));
      return wrap;
    }
    milestones.slice(0, 5).forEach(function (item, index) {
      wrap.appendChild(TD.el("div", { class: "choice" }, [
        TD.el("div", { class: "choice-name", text: "子任务 " + (index + 1) }),
        TD.el("div", { class: "choice-note", text: String(item.current_goal || item.command || "").slice(0, 80) })
      ]));
    });
    return wrap;
  }

  TD.flow = {
    concept: concept, choiceBlocks: choiceBlocks, frameStrip: frameStrip,
    milestones: milestones, svg: svg
  };
})();
