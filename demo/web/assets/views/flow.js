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
 *
 * 版式约定（都是踩过的坑）：
 * - 标签宽度按**实际字宽**算（中文 1em / 西文 0.56em），不能按字符个数估。
 *   按字符数估会把中文标签的胶囊框算窄，文字直接溢出框外。
 * - 回环走两条**互不交叉**的通道：「不符合预期」绕最下面的下带，
 *   「下一个子任务」走中带。这样两条线不会在中带互相压字。
 */
(function () {
  "use strict";
  var TD = window.TD;
  var NS = "http://www.w3.org/2000/svg";

  var LABEL_SIZE = 15;
  var SUB_SIZE = 12;
  var EDGE_SIZE = 12;

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

  /* ------------------------------------------------------------ 文字度量 */
  var CJK = /[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]/;

  /* 估算一段文字的像素宽度：中文/全角按 1em，西文按 0.56em。 */
  function textWidth(text, fontSize) {
    var width = 0;
    String(text === null || text === undefined ? "" : text).split("").forEach(function (ch) {
      width += CJK.test(ch) ? fontSize : fontSize * 0.56;
    });
    return width;
  }

  /* 超宽就截断并加省略号（节点框与标签都要用，别让字跑出框外）。 */
  function fitText(text, maxWidth, fontSize) {
    var str = String(text === null || text === undefined ? "" : text);
    if (!str) return "";
    if (textWidth(str, fontSize) <= maxWidth) return str;
    var out = "";
    for (var i = 0; i < str.length; i += 1) {
      if (textWidth(out + str[i] + "…", fontSize) > maxWidth) break;
      out += str[i];
    }
    return out ? out + "…" : "";
  }

  /* ------------------------------------------------------------ 图形零件 */
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
    group.appendChild(svg("text", {
      class: "fnode-label", x: x + width / 2, y: y + 32, "text-anchor": "middle",
      text: fitText(label, width - 22, LABEL_SIZE)
    }));
    if (sub) {
      group.appendChild(svg("text", {
        class: "fnode-sub", x: x + width / 2, y: y + 57, "text-anchor": "middle",
        text: fitText(sub, width - 22, SUB_SIZE)
      }));
    }
    return group;
  }

  function edge(path, tone) {
    var group = svg("g", { class: "fedge " + (tone || "") });
    group.appendChild(svg("path", { class: "fedge-line", d: path }));
    group.appendChild(svg("path", { class: "fedge-flow", d: path }));
    return group;
  }

  /* 标签：x 是**中心**；胶囊宽度按实际字宽算，不会出框。 */
  function edgeLabel(x, y, text, tone) {
    var group = svg("g", { class: "fedge-label " + (tone || "") });
    var width = textWidth(text, EDGE_SIZE) + 18;
    group.appendChild(svg("rect", { x: x - width / 2, y: y - 11, width: width, height: 22, rx: 11 }));
    group.appendChild(svg("text", { x: x, y: y + 4, "text-anchor": "middle", text: text }));
    return group;
  }

  /* ------------------------------------------------- 子任务循环流程图 */
  /* 返回 { node, setActive }
   *
   * conceptFacts 是**节点小字**（这条真实 case 的数字）；onSelect 是点击回调。
   * （之前这里按 (facts, onSelect) 定义，调用方却传了 (steps, facts.concept, cb)
   *   三个参数 → onSelect 拿到的是对象，节点小字永远走默认值、点击直接抛错。）
   */
  function concept(conceptFacts, onSelect) {
    var width = 1360;
    var height = 400;
    var boxW = 300;
    var boxH = 86;
    var topY = 30;            /* 顶行：30..116 */
    var botY = 236;           /* 底行：236..322 */
    var underY = 380;         /* 下带：不符合预期的绕行线 */
    var xs = [20, 350, 680, 1010];
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

    var plan = conceptFacts || {};
    var nodes = [
      { x: xs[0], y: topY, label: "慢模型 · 规划", sub: plan.plan || "拆解子任务 + 定目标", tone: "slow", step: 0 },
      { x: xs[1], y: topY, label: "快模型 · 完成子任务", sub: plan.task || "候选空间：a11y 解析 + 慢模型", tone: "fast", step: 1 },
      { x: xs[2], y: topY, label: "快模型 · 排序", sub: plan.rank || "选出一个动作", tone: "fast", step: 1 },
      { x: xs[3], y: topY, label: "慢模型 · 验证", sub: plan.verify || "子任务是否达成", tone: "slow", step: 2 },
      { x: xs[0], y: botY, label: "重规划 / 纠错", sub: plan.fix || "换个目标再来", tone: "fix", step: 3 },
      { x: xs[2], y: botY, label: "下一个子任务 → 任务完成", sub: plan.next || "循环直到任务完成", tone: "done", step: 1 }
    ];

    /* ---- 连线 ---- */
    /* 顶行三段直连 */
    svgNode.appendChild(edge("M " + (xs[0] + boxW) + " " + midY + " L " + xs[1] + " " + midY));
    svgNode.appendChild(edge("M " + (xs[1] + boxW) + " " + midY + " L " + xs[2] + " " + midY));
    svgNode.appendChild(edge("M " + (xs[2] + boxW) + " " + midY + " L " + xs[3] + " " + midY));
    /* 验证 → 下一个子任务（子任务达成）：从验证左下弯到「下一个子任务」正上方 */
    svgNode.appendChild(edge(
      "M " + (xs[3] + 90) + " " + (topY + boxH) +
      " C " + (xs[3] + 90) + " " + (botY - 46) + ", " + (xs[2] + boxW / 2) + " " + (botY - 46) +
      ", " + (xs[2] + boxW / 2) + " " + botY, "loopback"));
    /* 下一个子任务 → 完成子任务：走中带（左侧出去，中带向左，再向上顶到「完成子任务」底边） */
    svgNode.appendChild(edge(
      "M " + xs[2] + " " + (botY + boxH / 2) +
      " L " + (xs[1] + boxW / 2) + " " + (botY + boxH / 2) +
      " L " + (xs[1] + boxW / 2) + " " + (topY + boxH), "loopback"));
    /* 验证 → 重规划（不符合预期）：从验证右下垂直下到下带，再向左绕到「重规划」底边 */
    svgNode.appendChild(edge(
      "M " + (xs[3] + boxW - 40) + " " + (topY + boxH) +
      " L " + (xs[3] + boxW - 40) + " " + underY +
      " L " + (xs[0] + boxW / 2) + " " + underY +
      " L " + (xs[0] + boxW / 2) + " " + (botY + boxH), "warn"));
    /* 重规划 → 规划：垂直回顶 */
    svgNode.appendChild(edge(
      "M " + (xs[0] + boxW / 2) + " " + botY +
      " L " + (xs[0] + boxW / 2) + " " + (topY + boxH), "warn"));

    /* ---- 连线标签：位置互不重叠，也不压线 ---- */
    svgNode.appendChild(edgeLabel(xs[3] + boxW - 96, topY + boxH + 62, "不符合预期", "warn"));
    svgNode.appendChild(edgeLabel(xs[2] + boxW / 2 + 132, botY - 62, "子任务达成", "good"));
    svgNode.appendChild(edgeLabel((xs[1] + boxW / 2 + xs[2]) / 2, botY + boxH / 2, "下一个子任务", "accent"));
    svgNode.appendChild(edgeLabel(xs[0] + boxW / 2 - 66, topY + boxH + 62, "纠错后回到规划", "warn"));

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

  /* --------------------------------------------- 迷你图：快模型挑动作 */
  /* bars 是**动作级**候选（action_ranked × 候选表 join 出来的），赢家高亮。 */
  function choiceBlocks(bars, winner) {
    var wrap = TD.el("div", { class: "choices" });
    if (!bars || !bars.length) {
      wrap.appendChild(TD.el("div", { class: "hint", text: "（没有排序明细）" }));
      return wrap;
    }
    var max = Math.max.apply(null, bars.map(function (bar) { return bar.score || 0; })) || 1;
    var winnerId = winner && (winner.id || winner.operation);
    bars.forEach(function (bar) {
      var picked = bar.id ? bar.id === winnerId : bar.operation === winnerId;
      var width = 12 + 88 * ((bar.score || 0) / max);
      var row = TD.el("div", { class: "choice" + (picked ? " picked" : "") }, [
        TD.el("div", { class: "choice-name", text: bar.operation || "?" }),
        TD.el("div", { class: "choice-bar" }, [TD.el("i", { style: "width:" + width.toFixed(1) + "%" })]),
        TD.el("div", { class: "choice-score", text: (bar.score || 0).toFixed(3) }),
        picked ? TD.el("div", { class: "choice-pick", text: "✔ 快模型选中" }) : null
      ]);
      if (bar.description) {
        row.appendChild(TD.el("div", { class: "choice-desc", text: bar.description }));
      }
      wrap.appendChild(row);
    });
    return wrap;
  }

  /* 迷你图：截图条（这一题的帧） */
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

  /* 迷你图：子任务清单（慢模型拆出来的目标链）
   *
   * 画的是**整轮累积**的子任务，不是第一次规划的那两三个——只画第一次会
   * 让人以为整个任务就两步。meta 给出规划次数与子任务总数。
   * 列表要限长：这一轮能累积出几十个子任务，全铺开会把粘性卡片撑爆。
   */
  function milestones(items, meta) {
    var wrap = TD.el("div", { class: "choices" });
    var list = items || [];
    if (!list.length) {
      wrap.appendChild(TD.el("div", { class: "hint", text: "（这一步没有拆出子任务）" }));
      return wrap;
    }
    var limit = (meta && meta.limit) || 6;
    var shown = list.slice(0, limit);
    if (meta && meta.total) {
      wrap.appendChild(TD.el("div", { class: "choices-head", text:
        "本轮慢模型规划 " + (meta.plans || 0) + " 次 · 拆出 " + meta.total +
        " 个子任务（下列前 " + shown.length + " 个）" }));
    }
    shown.forEach(function (item, index) {
      wrap.appendChild(TD.el("div", { class: "choice sub" }, [
        TD.el("div", { class: "choice-name", text: "子任务 " + (index + 1) }),
        TD.el("div", { class: "choice-note", text: String(item) })
      ]));
    });
    if (list.length > shown.length) {
      wrap.appendChild(TD.el("div", { class: "choices-more", text:
        "… 还有 " + (list.length - shown.length) + " 个子任务（慢模型重规划时陆续拆出）" }));
    }
    return wrap;
  }

  TD.flow = {
    concept: concept, choiceBlocks: choiceBlocks, frameStrip: frameStrip,
    milestones: milestones, svg: svg, textWidth: textWidth, fitText: fitText
  };
})();
