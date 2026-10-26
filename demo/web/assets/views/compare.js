/* 官方对照视图：我们 vs 官方 harness（Sai w/ Claude Opus 5）
 *
 * 三层：
 * 1. 口径声明（底座 / 题集 / 基础设施失败）—— 每次对比都适用；
 * 2. 子集总览（12 题：我们 vs Sai 的分与 Δ）；
 * 3. **双边轨迹播放器**：同一进度点上并排看我们的帧与 Sai 的帧、动作与判分。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function pct(value, digits) { return TD.pct(value, digits === undefined ? 1 : digits); }

  function caliberStrip(compare) {
    return TD.el("div", { class: "panel", style: "margin-bottom:18px" }, [
      TD.el("div", { class: "panel-head" }, [TD.el("h2", { text: "对比口径（三处差异，每次对比都适用）" })]),
      TD.el("div", { class: "grid cols-3" }, [
        TD.el("div", { class: "callout info" }, [
          TD.el("strong", { text: "底座不同" }),
          TD.el("div", { style: "margin-top:6px", text:
            "我们用 MiniMax-M3.1-Flash，官方 Sai 用 Claude Opus 5。成本比 1/" +
            (compare.cost_ratio || "?") + " 主要来自底座，不是 harness 更省。" })
        ]),
        TD.el("div", { class: "callout" }, [
          TD.el("strong", { text: "题集不同" }),
          TD.el("div", { style: "margin-top:6px", text:
            "我们只尝试 " + compare.ours_attempted + " 题（官方 108 题全量）。" +
            compare.ours_unscored + " 题未出分，按「未出分」处理，不折算 0。" })
        ]),
        TD.el("div", { class: "callout bad" }, [
          TD.el("strong", { text: "基础设施失败吃掉了分数" }),
          TD.el("div", { style: "margin-top:6px", text:
            compare.ours_unscored + " 题未出分，其中 " + compare.unscored_sai_full +
            " 题官方 Sai 拿满分（含浮点尾差）——API / 判分侧失败，不是能力差距。" })
        ])
      ])
    ]);
  }

  /* 子集总览：每题一张小卡 */
  function subsetGrid(rows, onPick) {
    var cards = rows.filter(function (row) { return row.group; }).map(function (row) {
      var delta = row.delta;
      var verdict = delta === null || delta === undefined
        ? { text: "未出分", cls: "dim" }
        : (row.tie ? { text: "打平", cls: "good" } : { text: "-" + delta.toFixed(3), cls: "bad" });
      return TD.el("div", {
        class: "ladder-row clickable",
        style: "cursor:pointer;margin-bottom:6px",
        onclick: function () { onPick(row.task); },
        title: "点开看同题轨迹对照"
      }, [
        TD.el("div", { class: "name" }, [
          TD.el("span", { class: "mono", text: row.task }),
          TD.el("span", { class: "kind", text: row.group }),
          TD.el("span", { class: "dim small", text: row.ours_stop || "" })
        ]),
        TD.el("div", { class: "num" }, [
          TD.el("span", { class: row.ours === null ? "dim" : "", text: row.ours === null ? "未出分" : row.ours.toFixed(3) }),
          TD.el("span", { class: "dim", text: " / " }),
          TD.el("span", { text: row.sai_best === null || row.sai_best === undefined ? "—" : row.sai_best.toFixed(3) })
        ]),
        TD.el("div", { class: "num " + verdict.cls, text: verdict.text })
      ]);
    });
    return TD.el("div", {}, cards);
  }

  /* 双边轨迹播放器：同一进度点上并排看两边 */
  function duoPlayer(container, taskId, oursEpisode) {
    var panel = TD.el("div", { class: "panel" });
    panel.appendChild(TD.el("div", { class: "panel-head" }, [
      TD.el("h2", { text: "同题轨迹对照 · " + taskId }),
      TD.el("span", { class: "hint", text: "滑块按进度对齐两边（两个 agent 步数不同）" })
    ]));
    var stage = TD.el("div");
    panel.appendChild(stage);

    var oursSteps = (oursEpisode && oursEpisode.steps_detail) || [];
    var ourFrames = (oursEpisode && oursEpisode.frames) || [];
    var ourActions = oursSteps.filter(function (s) { return s.kind === "gui" || s.kind === "cli"; });

    var sai = null;
    var saiFrames = [];
    var saiSteps = [];
    var status = TD.el("div", { class: "small dim", style: "margin-top:10px", text: "载入官方参考轨迹…" });
    panel.appendChild(status);

    var slider = TD.el("input", { type: "range", min: "0", max: "100", value: "0" });
    var posLabel = TD.el("div", { class: "pos", text: "0%" });
    var ctrl = TD.el("div", { class: "duo-ctrl" }, [
      TD.el("span", { class: "small dim", text: "进度" }), slider, posLabel
    ]);
    panel.appendChild(ctrl);

    function paint() {
      var progress = Number(slider.value) / 100;
      posLabel.textContent = Math.round(progress * 100) + "%";

      TD.clear(stage);
      var duo = TD.el("div", { class: "duo" });

      /* 我们的那一侧 */
      var oursSide = TD.el("div", { class: "duo-side" }, [
        TD.el("div", { class: "cap" }, [
          TD.el("b", { text: "我们" }),
          TD.el("span", { class: "who", text: "tandem · stage+memory" }),
          TD.el("span", { class: "grow" }),
          TD.el("span", { class: "who", text: oursEpisode ? ("分数 " + (oursEpisode.score === null ? "未出分" : oursEpisode.score.toFixed(4))) : "—" })
        ])
      ]);
      var ourIndex = Math.min(ourFrames.length - 1, Math.max(0, Math.round(progress * (ourFrames.length - 1))));
      var ourFrame = ourFrames[ourIndex];
      if (ourFrame && ourFrame.src) {
        oursSide.appendChild(TD.el("img", { class: "shot", src: ourFrame.src, alt: "我们的第 " + ourFrame.step_idx + " 帧" }));
      } else {
        oursSide.appendChild(TD.el("div", { class: "shot missing", text: "这一题没有落盘帧" }));
      }
      var ourAction = ourActions.length ? ourActions[Math.min(ourActions.length - 1, Math.round(progress * (ourActions.length - 1)))] : null;
      oursSide.appendChild(TD.el("div", { class: "act", text:
        ourFrame ? ("step " + ourFrame.step_idx + " · " + (ourAction ? (ourAction.kind + " " + JSON.stringify(ourAction.action || ourAction.command || {}).slice(0, 120)) : "—")) : "—" }));
      duo.appendChild(oursSide);

      /* Sai 的那一侧 */
      var saiSide = TD.el("div", { class: "duo-side" }, [
        TD.el("div", { class: "cap" }, [
          TD.el("b", { text: "官方 Sai" }),
          TD.el("span", { class: "who", text: "anthropic/claude-opus-5" }),
          TD.el("span", { class: "grow" }),
          TD.el("span", { class: "who", text: sai ? ("分数 " + (sai.score === null ? "—" : sai.score.toFixed(4))) : "—" })
        ])
      ]);
      if (sai && saiSteps.length) {
        var saiIndex = Math.min(saiSteps.length - 1, Math.max(0, Math.round(progress * (saiSteps.length - 1))));
        var saiStep = saiSteps[saiIndex];
        var fileName = (sai.frames || {})[saiStep.screenshot_file];
        if (fileName) {
          saiSide.appendChild(TD.el("img", {
            class: "shot",
            src: "assets/" + (sai.frames_dir || ("sai_frames/" + taskId)).replace(/^assets\//, "") + "/" + fileName,
            alt: "Sai 第 " + saiStep.step_num + " 帧"
          }));
        } else {
          saiSide.appendChild(TD.el("div", { class: "shot missing", text: "该步无帧" }));
        }
        saiSide.appendChild(TD.el("div", { class: "act", text:
          "step " + saiStep.step_num + " · " + String(saiStep.action || saiStep.osworld_action || "—").slice(0, 120) +
          (saiStep.reward !== null && saiStep.reward !== undefined ? "  · reward " + saiStep.reward : "") }));
      } else {
        saiSide.appendChild(TD.el("div", { class: "shot missing", text: "载入中…" }));
      }
      duo.appendChild(saiSide);
      stage.appendChild(duo);
    }

    slider.addEventListener("input", paint);
    paint();

    /* 官方参考轨迹：文本 + 帧映射 */
    if (typeof fetch === "function") {
      fetch("assets/data/sai_traj/" + taskId + ".json").then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      }).then(function (data) {
        sai = data;
        saiSteps = data.steps || [];
        status.textContent = "官方参考 run " + (data.run || "") + " · " + saiSteps.length + " 步 · 分数 " +
          (data.score === null || data.score === undefined ? "—" : data.score.toFixed(4)) +
          " · 帧 " + Object.keys(data.frames || {}).length + " 张";
        paint();
      }).catch(function (error) {
        status.textContent = "载入官方轨迹失败：" + error.message +
          "（用 file:// 打开时浏览器会拦本地 fetch，请用 python3 -m http.server）";
      });
    }
    return panel;
  }

  TD.views.compare = function (container) {
    var compare = TD.state.compare;
    if (!compare) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的对照数据——请用构建脚本生成站点。" }));
      return;
    }
    var rows = compare.rows || [];

    container.appendChild(TD.el("section", { class: "hero" }, [
      TD.el("div", { class: "eyebrow", text: "OFFICIAL HARNESS BENCHMARK" }),
      TD.el("h1", { text: "我们 vs 官方 Sai（Claude Opus 5）" }),
      TD.el("p", { class: "lede", html:
        "同一 release、同一原生官方评测器、同一题号——逐题可比。共同已出分 <em>" +
        compare.common_scored + " 题</em>上：我们 <em>" + (compare.ours_mean * 100).toFixed(2) +
        "%</em>，Sai 最佳 <em>" + (compare.sai_mean_best * 100).toFixed(2) + "%</em>；" +
        "<em>打平 " + compare.ties + " 题</em>，我们领先 <em>" + compare.we_lead + " 题</em>。" })
    ]));

    container.appendChild(caliberStrip(compare));

    var gridPanel = TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "对比子集（12 题 · 4 组）" }),
        TD.el("span", { class: "hint", text: "点一行看同题轨迹对照" })
      ]),
      TD.el("p", { class: "lede", text: "数字格式：我们分 / Sai 最佳分；右侧为差距（Sai − 我们）。" })
    ]);
    var player = TD.el("div");
    gridPanel.appendChild(subsetGrid(rows, function (taskId) {
      TD.clear(player);
      player.appendChild(duoPlayer(container, taskId, null));
      player.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }));
    container.appendChild(gridPanel);
    container.appendChild(player);

    var tableRows = rows.filter(function (row) { return row.group; }).map(function (row) {
      return [
        { text: row.task, class: "tid" },
        { text: row.group },
        { text: row.ours === null ? "未出分" : row.ours.toFixed(4),
          class: row.ours === null ? "dim" : "" },
        { text: row.ours_stop || "—" },
        { text: row.sai_best === null || row.sai_best === undefined ? "—" : row.sai_best.toFixed(4), num: true },
        { text: row.sai_mean === null || row.sai_mean === undefined ? "—" : row.sai_mean.toFixed(4), num: true },
        { text: row.delta === null || row.delta === undefined ? "—" : (row.tie ? "打平" : "-" + row.delta.toFixed(3)),
          class: row.delta === null || row.delta === undefined ? "dim" : (row.tie ? "good" : "bad"), num: true },
        { text: TD.int(row.ours_tokens), num: true },
        { text: row.ours_noop_rate === null || row.ours_noop_rate === undefined ? "—" : pct(row.ours_noop_rate, 0), num: true }
      ];
    });
    container.appendChild(TD.el("div", { class: "panel", style: "margin-top:18px" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "逐题明细" }),
        TD.el("span", { class: "hint", text: "同 release · 同评测器" })
      ]),
      TD.table(
        [{ label: "题" }, { label: "组" }, { label: "我们" }, { label: "我们的终态" },
         { label: "Sai 最佳", num: true }, { label: "Sai 均值", num: true }, { label: "差距", num: true },
         { label: "我们的 token", num: true }, { label: "空转率", num: true }],
        tableRows
      )
    ]));
  };
})();
