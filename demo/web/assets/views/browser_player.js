/* 轨迹浏览的逐帧播放器（单轨）
 *
 * 从 browser.js 拆出来：播放器的状态机（播放/暂停/拖动/变速）与「把一份
 * episode / sai 轨迹变成逐步条目」是两件事，拆开后 browser.js 只管页面骨架。
 *
 * 纪律：
 * - 成本口径与我们侧一致（真实 token 归步）；官方侧逐步成本无法由 token 反推，
 *   按官方每题均价与步数折算并标「（折算）」；
 * - 帧是离散帧，缺失就如实标注，不画成连续视频。
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

  /* 我们这一侧：逐步累计花费与用时（真实 token 归步） */
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

  /* Sai 那一侧：逐步累计用时；成本官方未发布逐步数据 → 按每题均价折算 */
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

  TD.browserPlayer = {
    player: player,
    ourItems: ourItems,
    saiItems: saiItems
  };
})();
