/* 官方对照视图：我们 vs 官方 Sai（Claude Opus 5）
 *
 * 两个 harness **各自独立播放**（不做进度对齐——两边步数不同、动作粒度不同，
 * 硬对齐反而看不出各自在干什么）。每一步都给出：画面、动作、花费、耗时。
 *
 * 口径：同 release（v2.1）· 同原生官方评测器 · 同题号 → 逐题可比。
 */
(function () {
  "use strict";
  var TD = window.TD;

  /* Sai 的时间戳形如 20260923@075024469873 → 当天秒数 */
  function saiSeconds(stamp) {
    if (typeof stamp !== "string" || stamp.indexOf("@") < 0) return null;
    var time = stamp.split("@")[1];
    var hours = parseInt(time.slice(0, 2), 10);
    var minutes = parseInt(time.slice(2, 4), 10);
    var seconds = parseInt(time.slice(4, 6), 10);
    var millis = parseInt(time.slice(6), 10) / 1e6;
    if (isNaN(hours)) return null;
    return hours * 3600 + minutes * 60 + seconds + millis;
  }

  function player(title, who, accent, items, render) {
    /* items: [{frame, meta:[{label,value}], body}] */
    var state = { index: 0, playing: false, timer: null, speed: 1 };
    var box = TD.el("div", { class: "duo-side" });
    var shot = TD.el("div", { class: "shot missing", text: "—" });
    var body = TD.el("div", { class: "act" });
    var meta = TD.el("div", { class: "meta-row" });
    var slider = TD.el("input", { type: "range", min: "0", max: String(Math.max(items.length - 1, 0)), value: "0" });
    var position = TD.el("div", { class: "pos", text: "0 / " + items.length });
    var playBtn = TD.el("button", { class: "ghost", type: "button", text: "▶ 播放" });

    function paint() {
      var item = items[state.index];
      TD.clear(shot);
      TD.clear(body);
      TD.clear(meta);
      if (!item) { position.textContent = "0 / 0"; return; }
      if (item.frame) {
        var img = TD.el("img", { class: "shot", src: item.frame, alt: title + " 第 " + (state.index + 1) + " 帧" });
        shot = img;
        box.replaceChild(img, shot);
        shot = img;
      } else {
        shot.textContent = "这一侧没有帧";
      }
      body.textContent = item.body || "—";
      (item.meta || []).forEach(function (pair) {
        meta.appendChild(TD.el("span", { class: "meta-chip" }, [
          TD.el("b", { text: pair.label }), document.createTextNode(pair.value)
        ]));
      });
      position.textContent = (state.index + 1) + " / " + items.length;
      slider.value = String(state.index);
    }

    function stop() {
      state.playing = false;
      if (state.timer) { clearInterval(state.timer); state.timer = null; }
      playBtn.textContent = "▶ 播放";
    }
    function start() {
      if (!items.length) return;
      state.playing = true;
      playBtn.textContent = "⏸ 暂停";
      if (state.timer) clearInterval(state.timer);
      state.timer = setInterval(function () {
        if (state.index >= items.length - 1) { stop(); return; }
        state.index += 1;
        paint();
      }, Math.max(120, 700 / state.speed));
    }
    playBtn.addEventListener("click", function () { state.playing ? stop() : start(); });
    slider.addEventListener("input", function () {
      stop();
      state.index = Number(slider.value);
      paint();
    });
    var speed = TD.el("select", { class: "ghost" }, [
      TD.el("option", { value: "0.5", text: "0.5×" }),
      TD.el("option", { value: "1", text: "1×" }),
      TD.el("option", { value: "2", text: "2×" })
    ]);
    speed.addEventListener("change", function () {
      state.speed = Number(speed.value);
      if (state.playing) start();
    });
    var prev = TD.el("button", { class: "ghost", type: "button", text: "⏮" });
    var next = TD.el("button", { class: "ghost", type: "button", text: "⏭" });
    prev.addEventListener("click", function () { stop(); state.index = Math.max(0, state.index - 1); paint(); });
    next.addEventListener("click", function () { stop(); state.index = Math.min(items.length - 1, state.index + 1); paint(); });

    box.appendChild(TD.el("div", { class: "cap" }, [
      TD.el("b", { text: title }),
      TD.el("span", { class: "who", text: who }),
      TD.el("span", { class: "grow" })
    ]));
    box.appendChild(shot);
    box.appendChild(meta);
    box.appendChild(body);
    box.appendChild(TD.el("div", { class: "duo-ctrl" }, [playBtn, prev, next, slider, position, speed]));
    paint();
    return box;
  }

  /* 我们这一侧：逐题 view model 的 timeline（已带每步成本与耗时） */
  function ourItems(episode) {
    var timeline = episode.timeline || [];
    return timeline.map(function (entry) {
      var fast = entry.fast || {};
      var slow = entry.slow || {};
      var summary = entry.action
        ? JSON.stringify(entry.action).slice(0, 150)
        : (entry.kind || "");
      return {
        frame: entry.frame,
        body: summary,
        meta: [
          { label: "花费 ", value: "$" + (entry.cost_usd || 0).toFixed(5) },
          { label: " token ", value: TD.int(entry.tokens) },
          { label: " 用时 ", value: ((entry.elapsed_ms || 0) / 1000).toFixed(1) + "s" },
          { label: " 候选 ", value: (fast.n_candidates === undefined ? "—" : fast.n_candidates) },
          { label: " 排序 ", value: fast.latency_ms === undefined ? "—" : fast.latency_ms + "ms" }
        ]
      };
    });
  }

  /* Sai 那一侧：他们的帧 + 每步耗时 + reward（逐步成本官方未发布） */
  function saiItems(sai, totalCostUsd) {
    var steps = sai.steps || [];
    var seconds = steps.map(function (step) { return saiSeconds(step.action_timestamp); });
    var items = steps.map(function (step, index) {
      var elapsed = null;
      if (seconds[index] !== null && seconds[index - 1] !== null && seconds[index - 1] !== undefined) {
        elapsed = Math.max(seconds[index] - seconds[index - 1], 0);
      }
      var fileName = (sai.frames || {})[step.screenshot_file];
      var frame = fileName ? ("assets/sai_frames/" + sai.task + "/" + fileName) : null;
      return {
        frame: frame,
        body: String(step.action || step.osworld_action || "—").slice(0, 150),
        meta: [
          { label: " reward ", value: step.reward === null || step.reward === undefined ? "—" : String(step.reward) },
          { label: " 用时 ", value: elapsed === null ? "—" : elapsed.toFixed(1) + "s" },
          { label: " 累计花费 ", value: "官方未发布逐步成本" }
        ]
      };
    });
    return items;
  }

  TD.views.compare = function (container) {
    var compare = TD.state.compare;
    if (!compare) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的对照数据——请用构建脚本生成站点。" }));
      return;
    }
    var rows = compare.rows || [];
    var subset = rows.filter(function (row) { return row.group; });

    container.appendChild(TD.el("section", { class: "hero" }, [
      TD.el("div", { class: "eyebrow", text: "OFFICIAL HARNESS BENCHMARK" }),
      TD.el("h1", { text: "我们 vs 官方 Sai（Claude Opus 5）" }),
      TD.el("p", { class: "lede", html:
        "同一 release、同一原生官方评测器、同一题号。共同已出分 <em>" + compare.common_scored +
        " 题</em>上：我们 <em>" + (compare.ours_mean * 100).toFixed(2) + "%</em>，Sai 最佳 <em>" +
        (compare.sai_mean_best * 100).toFixed(2) + "%</em>；<em>打平 " + compare.ties +
        " 题</em>，我们领先 <em>" + compare.we_lead + " 题</em>。" })
    ]));

    container.appendChild(TD.el("div", { class: "panel", style: "margin-bottom:18px" }, [
      TD.el("div", { class: "panel-head" }, [TD.el("h2", { text: "对比口径" })]),
      TD.el("div", { class: "grid cols-3" }, [
        TD.el("div", { class: "callout info" }, [
          TD.el("strong", { text: "底座不同" }),
          TD.el("div", { style: "margin-top:6px", text:
            "我们用 MiniMax-M3.1-Flash，官方 Sai 用 Claude Opus 5。成本比 1/" +
            (compare.cost_ratio || "?") + " 主要来自底座。" })
        ]),
        TD.el("div", { class: "callout" }, [
          TD.el("strong", { text: "题集不同" }),
          TD.el("div", { style: "margin-top:6px", text:
            "我们只尝试 " + compare.ours_attempted + " 题（官方 108 题全量）；" +
            compare.ours_unscored + " 题未出分，不折算 0。" })
        ]),
        TD.el("div", { class: "callout bad" }, [
          TD.el("strong", { text: "基础设施失败吃掉了分数" }),
          TD.el("div", { style: "margin-top:6px", text:
            compare.ours_unscored + " 题未出分，其中 " + compare.unscored_sai_full +
            " 题官方 Sai 拿满分——API / 判分侧失败。" })
        ])
      ])
    ]));

    container.appendChild(TD.el("div", { class: "panel" }, [
      TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "对比子集（" + subset.length + " 题 · 只选我们成功的题）" }),
        TD.el("span", { class: "hint", text: "点一行看两边的轨迹播放" })
      ])
    ]));

    var stage = TD.el("div");
    var list = TD.el("div", {}, subset.map(function (row) {
      var verdict = row.delta === null || row.delta === undefined
        ? { text: "未出分", cls: "dim" }
        : (row.tie ? { text: "打平", cls: "good" } : { text: "-" + row.delta.toFixed(3), cls: "bad" });
      return TD.el("div", {
        class: "ladder-row clickable",
        style: "cursor:pointer;margin-bottom:8px",
        onclick: function () { openTask(row); },
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
    }));
    container.lastChild.appendChild(list);
    container.appendChild(stage);

    function openTask(row) {
      TD.clear(stage);
      stage.appendChild(TD.el("div", { class: "panel" }, [TD.el("h2", { text: "载入中…" })]));
      TD.loadEpisode(row.run_id || "", row.task, function (episode, error) {
        TD.clear(stage);
        if (!episode) {
          stage.appendChild(TD.el("div", { class: "callout bad", text:
            "载入我们的逐题数据失败：" + (error || "未知错误") +
            "（file:// 下浏览器会拦本地 fetch，请用 python3 -m http.server 打开）" }));
          return;
        }
        var panel = TD.el("div", { class: "panel", style: "margin-top:18px" }, [
          TD.el("div", { class: "panel-head" }, [
            TD.el("h2", { text: "同题轨迹对照 · " + row.task }),
            TD.el("span", { class: "hint", text: "两边各自播放，不做进度对齐" })
          ])
        ]);
        var duo = TD.el("div", { class: "duo" }, [
          player("我们（Tandem）", "stage+memory · " + (episode.score === null ? "未出分" : "得分 " + episode.score.toFixed(4)),
            "ours", ourItems(episode)),
          player("官方 Sai", "Claude Opus 5", "sai", [])
        ]);
        panel.appendChild(duo);
        stage.appendChild(panel);
        /* Sai 侧：拿到轨迹后替换占位 */
        if (typeof fetch === "function") {
          fetch("assets/data/sai_traj/" + row.task + ".json").then(function (response) {
            if (!response.ok) throw new Error("HTTP " + response.status);
            return response.json();
          }).then(function (data) {
            var saiBox = duo.lastChild;
            var replacement = player("官方 Sai", "Claude Opus 5 · 得分 " +
              (data.score === null ? "—" : data.score.toFixed(4)), "sai", saiItems(data, compare.sai_usd_per_task));
            duo.replaceChild(replacement, saiBox);
          }).catch(function (error) {
            duo.lastChild.appendChild(TD.el("div", { class: "callout bad", style: "margin:12px", text:
              "载入官方轨迹失败：" + error.message }));
          });
        }
      });
    }
  };
})();
