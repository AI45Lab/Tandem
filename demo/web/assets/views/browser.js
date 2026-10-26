/* 轨迹浏览：三栏工作台
 *
 * 左：任务卡（首帧预览 + 域 + 得分 + 步数）
 * 中：Tandem 与 Sai 两边独立回放，**花费与用时按步骤累计**
 * 右：Task Instruction、模型底座、评测（得分 / 步数 / 逐条要求）
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

  function domainLabel(domain) {
    var map = {
      browser_web: "Browser", libreoffice_impress: "Impress", libreoffice_calc: "Calc",
      libreoffice_writer: "Writer", email_client: "Email", gimp_image: "GIMP",
      video_editor: "Video", media_player: "Media", vscode_ide: "VS Code",
      system_settings: "Settings", other: "Other"
    };
    return map[domain] || domain || "Other";
  }

  /* ---------------------------------------------------------------- 播放器 */
  function player(options) {
    var items = options.items || [];
    var state = { index: 0, playing: false, timer: null, speed: 1 };
    var box = TD.el("div", { class: "duo-side" });
    var shot = TD.el("div", { class: "shot missing", text: "—" });
    var readout = TD.el("div", { class: "readout" });
    var detail = TD.el("div", { class: "step-detail" });
    var slider = TD.el("input", { type: "range", min: "0", max: String(Math.max(items.length - 1, 0)), value: "0" });
    var position = TD.el("div", { class: "pos", text: "0 / 0" });
    var playBtn = TD.el("button", { class: "ghost", type: "button", text: "▶ Play" });

    function paint() {
      var item = items[state.index];
      TD.clear(readout);
      TD.clear(detail);
      if (!item) { position.textContent = "0 / 0"; return; }
      if (item.frame) {
        var image = TD.el("img", { class: "shot", src: item.frame, alt: options.title + " 帧" });
        box.replaceChild(image, shot);
        shot = image;
      } else {
        shot.className = "shot missing";
        shot.textContent = "这一步没有落盘帧";
      }
      TD.el("span", { class: "readout-item" }, [
        TD.el("b", { text: "累计花费 " }), document.createTextNode(item.cumulativeCost)
      ]);
      TD.el("span", { class: "readout-item" }, [
        TD.el("b", { text: "累计用时 " }), document.createTextNode(item.cumulativeElapsed)
      ]);
      if (item.stepCost) {
        TD.el("span", { class: "readout-item" }, [
          TD.el("b", { text: "本步 " }), document.createTextNode(item.stepCost)
        ]);
      }
      if (item.reward !== undefined && item.reward !== null) {
        TD.el("span", { class: "readout-item" }, [
          TD.el("b", { text: "reward " }), document.createTextNode(String(item.reward))
        ]);
      }
      detail.textContent = item.body || "—";
      position.textContent = (state.index + 1) + " / " + items.length;
      slider.value = String(state.index);
    }

    function stop() {
      state.playing = false;
      if (state.timer) { clearInterval(state.timer); state.timer = null; }
      playBtn.textContent = "▶ Play";
    }
    function start() {
      if (!items.length) return;
      state.playing = true;
      playBtn.textContent = "⏸ Pause";
      if (state.timer) clearInterval(state.timer);
      state.timer = setInterval(function () {
        if (state.index >= items.length - 1) { stop(); return; }
        state.index += 1;
        paint();
      }, Math.max(150, 800 / state.speed));
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
    var prev = TD.el("button", { class: "ghost", type: "button", text: "⏮ Prev" });
    var next = TD.el("button", { class: "ghost", type: "button", text: "Next ⏭" });
    prev.addEventListener("click", function () { stop(); state.index = Math.max(0, state.index - 1); paint(); });
    next.addEventListener("click", function () { stop(); state.index = Math.min(items.length - 1, state.index + 1); paint(); });

    box.appendChild(TD.el("div", { class: "cap" }, [
      TD.el("b", { text: options.title }),
      TD.el("span", { class: "who", text: options.who }),
      TD.el("span", { class: "grow" }),
      TD.el("span", { class: "who", text: options.score || "" })
    ]));
    box.appendChild(shot);
    box.appendChild(TD.el("div", { class: "duo-ctrl" }, [playBtn, prev, next, slider, position, speed]));
    box.appendChild(readout);
    box.appendChild(detail);
    paint();
    return box;
  }

  /* 我们这一侧：逐步累计花费与用时 */
  function ourItems(episode) {
    var timeline = episode.timeline || [];
    var cost = 0;
    var elapsed = 0;
    return timeline.map(function (entry) {
      cost += entry.cost_usd || 0;
      elapsed += entry.elapsed_ms || 0;
      var fast = entry.fast || {};
      var body = entry.action
        ? JSON.stringify(entry.action).slice(0, 160)
        : (entry.kind || "");
      var thinking = (entry.slow && entry.slow.text) || "";
      return {
        frame: entry.frame,
        body: (thinking ? thinking.slice(0, 220) + "\n" : "") + body,
        cumulativeCost: "$" + cost.toFixed(5),
        cumulativeElapsed: (elapsed / 1000).toFixed(1) + "s",
        stepCost: "本步 $" + (entry.cost_usd || 0).toFixed(5) + " · " + ((entry.elapsed_ms || 0) / 1000).toFixed(1) + "s"
      };
    });
  }

  /* Sai 那一侧：逐步累计用时；成本官方未发布逐步数据 */
  function saiItems(sai, costPerTask) {
    var steps = sai.steps || [];
    var perStep = steps.length && costPerTask ? (costPerTask / steps.length) : null;
    var seconds = steps.map(function (step) { return saiSeconds(step.action_timestamp); });
    var elapsed = 0;
    return steps.map(function (step, index) {
      if (seconds[index] !== null && seconds[index - 1] !== null && seconds[index - 1] !== undefined) {
        elapsed += Math.max(seconds[index] - seconds[index - 1], 0);
      }
      var fileName = (sai.frames || {})[step.screenshot_file];
      return {
        frame: fileName ? ("assets/sai_frames/" + sai.task + "/" + fileName) : null,
        body: String(step.action || step.osworld_action || step.response || "—").slice(0, 200),
        cumulativeCost: perStep === null
          ? "官方未发布逐步成本"
          : "约 $" + (perStep * (index + 1)).toFixed(2) + "（折算）",
        cumulativeElapsed: elapsed.toFixed(1) + "s",
        reward: step.reward === null || step.reward === undefined ? null : step.reward
      };
    });
  }

  /* ------------------------------------------------------------------ 页面 */
  TD.views.browser = function (container) {
    var compare = TD.state.compare;
    if (!compare) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的对照数据——请用构建脚本生成站点。" }));
      return;
    }
    var subset = (compare.rows || []).filter(function (row) { return row.group; });

    var rail = TD.el("div", { class: "panel rail-panel" });
    var middle = TD.el("div", { class: "panel mid-panel" });
    var right = TD.el("div", { class: "panel right-panel" });
    var grid = TD.el("div", { class: "workbench3" }, [rail, middle, right]);
    container.appendChild(grid);

    rail.appendChild(TD.el("div", { class: "panel-head" }, [
      TD.el("h2", { text: "Tasks" }),
      TD.el("span", { class: "hint", text: subset.length + " Samples" })
    ]));
    var cards = TD.el("div", { class: "task-list" });
    rail.appendChild(cards);

    var episodes = {};
    var saiData = {};
    var active = null;

    function renderCard(row, episode) {
      var frame = episode && episode.frames && episode.frames[0] ? episode.frames[0].src : null;
      var raw = (episode && episode.instruction ? episode.instruction : "").trim();
      var summary = raw.length > 110 ? raw.slice(0, 110).replace(/\s+\S*$/, "") + "…" : raw;
      var card = TD.el("div", {
        class: "task-card" + (active === row.task ? " active" : ""),
        onclick: function () { select(row.task); }
      }, [
        frame
          ? TD.el("img", { src: frame, alt: "Task " + row.task + " 首帧" })
          : TD.el("div", { class: "thumb-missing", text: "无帧" }),
        TD.el("div", { class: "task-card-body" }, [
          TD.el("div", { class: "task-id", text: "Task " + row.task }),
          TD.el("div", { class: "task-summary", text: summary || "—" }),
          TD.el("div", { class: "task-meta", text:
            (row.ours === null ? "未出分" : (row.ours * 100).toFixed(2) + "%") +
            " · " + ((episode && episode.steps) || 0) + " Steps" })
        ])
      ]);
      return card;
    }

    function select(taskId) {
      active = taskId;
      TD.clear(cards);
      subset.forEach(function (row) {
        cards.appendChild(renderCard(row, episodes[row.task]));
      });
      renderMiddle(taskId);
      renderRight(taskId);
    }

    function renderMiddle(taskId) {
      TD.clear(middle);
      var row = subset.filter(function (item) { return item.task === taskId; })[0] || {};
      var episode = episodes[taskId];
      middle.appendChild(TD.el("div", { class: "panel-head" }, [
        TD.el("h2", { text: "Task " + taskId }),
        TD.el("span", { class: "hint", text: row.group || "" })
      ]));
      var duo = TD.el("div", { class: "duo" }, [
        player({
          title: "Tandem",
          who: "MiniMax-M3.1-Flash + JEV",
          score: episode && episode.score !== null ? "得分 " + episode.score.toFixed(4) : "",
          items: episode ? ourItems(episode) : []
        }),
        player({
          title: "Sai",
          who: "Claude Opus 5",
          score: saiData[taskId] && saiData[taskId].score !== null
            ? "得分 " + saiData[taskId].score.toFixed(4) : "",
          items: saiData[taskId] ? saiItems(saiData[taskId], compare.sai_usd_per_task) : []
        })
      ]);
      middle.appendChild(duo);
    }

    function renderRight(taskId) {
      TD.clear(right);
      var row = subset.filter(function (item) { return item.task === taskId; })[0] || {};
      var episode = episodes[taskId];
      var sai = saiData[taskId];
      right.appendChild(TD.el("div", { class: "panel-head" }, [TD.el("h2", { text: "Evaluation" })]));

      var scoreBox = TD.el("div", { class: "score-box" }, [
        TD.el("div", { class: "score-big", text: row.ours === null ? "—" : (row.ours * 100).toFixed(2) + "%" }),
        TD.el("div", { class: "score-sub", text: "Tandem · " + ((episode && episode.steps) || 0) + " 步" }),
        TD.el("div", { class: "score-sub", text: "Sai · " + (row.sai_best === null || row.sai_best === undefined ? "—" : (row.sai_best * 100).toFixed(2) + "%") })
      ]);
      right.appendChild(scoreBox);

      right.appendChild(TD.el("div", { class: "meta-block" }, [
        TD.el("div", { class: "meta-title", text: "Task " + taskId }),
        TD.el("div", { class: "meta-line", text: "域：" + domainLabel((episode && episode.domain) || "") }),
        TD.el("div", { class: "meta-line", text: "慢模型：MiniMax-M3.1-Flash（reasoning_effort=max）" }),
        TD.el("div", { class: "meta-line", text: "快模型：JEV / qwen-jev-choice" }),
        TD.el("div", { class: "meta-line", text: "评测：原生官方评测器 · release v2.1" })
      ]));

      right.appendChild(TD.el("div", { class: "meta-block" }, [
        TD.el("div", { class: "meta-title", text: "对比口径" }),
        TD.el("div", { class: "meta-line", text:
          "同 release（v2.1）· 同原生官方评测器 · 同题号 → 逐题可比。" }),
        TD.el("div", { class: "meta-line", text:
          "题集不同：我们 " + compare.ours_attempted + " 题尝试（官方 108 题全量）；" +
          compare.ours_unscored + " 题未出分，按「未出分」处理，不折算 0。" }),
        TD.el("div", { class: "meta-line", text:
          "底座不同：我们 MiniMax-M3.1-Flash，官方 Sai 用 Claude Opus 5——成本比 1/" +
          (compare.cost_ratio || "?") + " 主要来自底座。" })
      ]));

      right.appendChild(TD.el("div", { class: "meta-block" }, [
        TD.el("div", { class: "meta-title", text: "Task Instruction" }),
        TD.el("div", { class: "instruction", text: (episode && episode.instruction) || "—" })
      ]));

      var reqs = (episode && episode.requirements) || [];
      var rubric = TD.el("div", { class: "meta-block" }, [
        TD.el("div", { class: "meta-title", text: "Rubric（逐条要求核验）" })
      ]);
      if (reqs.length) {
        reqs.forEach(function (req) {
          rubric.appendChild(TD.el("div", { class: "rubric-item" }, [
            TD.el("div", { class: "rubric-head" }, [
              TD.el("b", { text: req.id }),
              TD.el("span", { class: req.status === "achieved" ? "good" : "bad", text: String(req.status || "?") })
            ]),
            TD.el("div", { class: "small dim", text: (req.evidence || "").slice(0, 120) })
          ]));
        });
      } else {
        rubric.appendChild(TD.el("div", { class: "small dim", text: "这一题没有 requirement_checks 记录。" }));
      }
      right.appendChild(rubric);
    }

    /* 载入：我们的逐题数据 + Sai 的轨迹 */
    var pending = subset.length;
    function ready() {
      pending -= 1;
      if (pending > 0) return;
      select(subset.length ? subset[0].task : null);
    }
    subset.forEach(function (row) {
      TD.loadEpisode(row.run_id || "", row.task, function (episode, error) {
        episodes[row.task] = episode || null;
        ready();
      });
      if (typeof fetch === "function") {
        fetch("assets/data/sai_traj/" + row.task + ".json").then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        }).then(function (data) {
          data.task = row.task;
          saiData[row.task] = data;
          ready();
        }).catch(function () { ready(); });
      } else {
        ready();
      }
    });
  };
})();
