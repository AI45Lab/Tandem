/* 任务页：真实时钟泳道 / 需求章节 / 步骤回放 / 运行证据抽屉。 */
(function (global) {
  "use strict";

  var T = global.TANDEM;
  var payload = T.payload;
  var esc = T.esc;
  var num = T.num;
  var secs = T.secs;
  var clock = T.clock;
  var renderDetail = T.detail.renderDetail;

  function initPlayer() {
    var detail = document.getElementById("detail");
    var timeline = document.getElementById("timeline");
    if (!detail || !timeline) return;

    var task = payload.task;
    var run = payload.run;
    var steps = task.steps || [];
    var frames = payload.frames || {};
    var frameBase = "../../assets/frames/" + run.run_id + "/" + task.task_id + "/";
    var current = 0;

    function frameSrc(name) {
      if (!name) return null;
      var jpg = frames[name];
      return jpg ? frameBase + jpg : null;
    }

    function outcomeClass(step) {
      var outcome = (step.verification || {}).outcome || "";
      if (!outcome) return "";
      var low = String(outcome).toLowerCase();
      if (low.indexOf("achieved") >= 0 || low.indexOf("pass") >= 0) return "ok";
      if (low.indexOf("not_achieved") >= 0 || low.indexOf("fail") >= 0) return "bad";
      return "miss";
    }

    function renderTimeline() {
      timeline.innerHTML = "";
      steps.forEach(function (step, index) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip" + (index === current ? " active" : "");
        var route = ((step.action || {}).kind || "").toLowerCase();
        chip.innerHTML = "<span class='dot " + outcomeClass(step) + "'></span>第 " + (index + 1) +
          " 步" + (route ? "<span class='rt'>" + route + "</span>" : "");
        chip.addEventListener("click", function () { current = index; render(); });
        timeline.appendChild(chip);
      });
    }

    function renderChapters() {
      var list = document.getElementById("chapter-list");
      if (!list) return;
      var chapters = task.chapters || [];
      if (!chapters.length) {
        list.innerHTML = "<li class='muted'>本 episode 没有结构化需求核验记录。</li>";
        return;
      }
      list.innerHTML = chapters.map(function (chapter) {
        var status = chapter.final || "";
        var cls = status === "met" ? "ok" : status === "not_met" ? "bad" : "miss";
        var seen = chapter.steps || [];
        var jump = seen.length
          ? "<a href='#step=" + (seen[0] + 1) + "' data-jump='" + (seen[0] + 1) + "'>第 " +
            (seen[0] + 1) + " 步 →</a><span class='cnt'>共 " + seen.length + " 次核验</span>"
          : "<span class='cnt'>未核验</span>";
        return "<li class='" + cls + "'><b>" + esc(chapter.id) + "</b>" +
          "<span class='req'>" + esc(chapter.requirement) + "</span>" +
          "<span class='st'>" + esc(status || "未核验") + "</span>" + jump + "</li>";
      }).join("");
      Array.prototype.forEach.call(list.querySelectorAll("[data-jump]"), function (link) {
        link.addEventListener("click", function (event) {
          event.preventDefault();
          current = parseInt(link.getAttribute("data-jump"), 10) - 1;
          render();
        });
      });
    }

    function renderLanes() {
      var lanesBox = document.getElementById("lanes");
      var ruler = document.getElementById("ruler");
      if (!lanesBox || !ruler) return;
      lanesBox.innerHTML = "";
      ruler.innerHTML = "";
      var tl = task.timeline || {};
      var spans = tl.spans || [];
      var duration = tl.duration || 0;
      var note = document.getElementById("tl-note");
      if (!spans.length || duration <= 0) {
        if (note) {
          note.textContent = "本 episode 没有可还原的实测时间轴（无 LLM 调用或未进入决策步）。";
        }
        return;
      }
      if (note) {
        note.textContent = "实测时刻重建 · 区间 " + duration.toFixed(1) + "s" +
          (tl.wall_seconds
            ? "（端到端 " + tl.wall_seconds.toFixed(1) + "s，含环境准备与评分）"
            : "") +
          " · 不含环境准备与评分时间";
      }
      (tl.lanes || []).forEach(function (lane) {
        var row = document.createElement("div");
        row.className = "lane";
        var totals = 0;
        spans.forEach(function (span) {
          var range = (span.lanes || {})[lane.key];
          if (range) totals += range[1] - range[0];
        });
        row.innerHTML = "<span class='lane-label'>" + esc(lane.label) +
          "<i>" + (totals ? totals.toFixed(1) + "s" : "") + "</i></span>";
        var track = document.createElement("div");
        track.className = "lane-track";
        spans.forEach(function (span, index) {
          var range = (span.lanes || {})[lane.key];
          if (!range) return;
          var width = range[1] - range[0];
          var bar = document.createElement("i");
          bar.className = "interval " + lane.key;
          bar.style.left = (100 * range[0] / duration) + "%";
          bar.style.width = Math.max(0.4, (100 * width / duration)) + "%";
          bar.title = "第 " + (index + 1) + " 步 · " + width.toFixed(1) + "s";
          bar.addEventListener("click", function () { current = index; render(); });
          track.appendChild(bar);
        });
        row.appendChild(track);
        lanesBox.appendChild(row);
      });
      for (var pct = 0; pct <= 100; pct += 5) {
        var tick = document.createElement("i");
        tick.className = pct % 25 === 0 ? "major" : "minor";
        tick.style.left = pct + "%";
        ruler.appendChild(tick);
        if (pct % 25 === 0) {
          var mark = document.createElement("span");
          mark.style.left = pct + "%";
          if (pct === 0) mark.className = "start";
          else if (pct === 100) mark.className = "end";
          mark.textContent = clock((duration * pct) / 100);
          ruler.appendChild(mark);
        }
      }
    }

    function renderCost() {
      var box = document.getElementById("cost");
      if (!box) return;
      var cost = task.cost || { total: {}, by_role: {} };
      var total = cost.total || {};
      var rows = Object.keys(cost.by_role || {}).map(function (role) {
        var bucket = cost.by_role[role];
        return "<tr><td>" + esc(role) + "</td><td class='num'>" + bucket.calls +
          "</td><td class='num'>" + num(bucket.prompt_tokens) +
          "</td><td class='num'>" + num(bucket.completion_tokens) +
          "</td><td class='num'>" + num(bucket.reasoning_tokens) + "</td></tr>";
      }).join("");
      box.innerHTML =
        "<table class='rank'><thead><tr><th>LLM 角色</th><th class='num'>调用</th>" +
        "<th class='num'>输入 token</th><th class='num'>输出 token</th>" +
        "<th class='num'>其中思考</th></tr></thead><tbody>" + rows + "</tbody></table>" +
        "<p class='sub'>合计 " + (total.calls || 0) + " 次调用 · " +
        num(total.prompt_tokens) + " 输入 token · " + num(total.completion_tokens) +
        " 输出 token（含 " + num(total.reasoning_tokens) + " 思考 token）· " +
        "快模型排序 " + (task.fast_calls || 0) + " 次 / " +
        (typeof task.fast_latency_ms_total === "number"
          ? (task.fast_latency_ms_total / 1000).toFixed(1) + "s" : "-") +
        " · 端到端 " + secs(task.wall_seconds) +
        "<br>成本以 token 用量与调用次数表达，未换算货币单价。</p>";
    }

    function renderEvidence(step) {
      var box = document.getElementById("evidence");
      if (!box) return;
      box.textContent = "正在加载完整证据…";
      var url = payload.evidence_url;
      if (!url) {
        box.textContent = JSON.stringify({ step: step.step, events: step }, null, 2);
        return;
      }
      fetch(url)
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(function (doc) {
          box.textContent = JSON.stringify(doc, null, 2);
        })
        .catch(function (error) {
          box.textContent =
            "无法加载完整证据文件（" + error.message + "）。\n" +
            "若用 file:// 直接打开页面，浏览器会拦截本地 fetch；" +
            "请用 python3 -m http.server 启动，或查看本页内联摘要：\n\n" +
            JSON.stringify({ step: step.step, events: step }, null, 2);
        });
    }

    function render() {
      var step = steps[current];
      if (!step) {
        if (T.fail) T.fail.renderZeroState();
        return;
      }
      var before = document.getElementById("img-before");
      var after = document.getElementById("img-after");
      var capBefore = document.getElementById("cap-before");
      var capAfter = document.getElementById("cap-after");
      var noBefore = document.getElementById("noshot-before");
      var noAfter = document.getElementById("noshot-after");
      var beforeSrc = frameSrc(step.before_frame);
      var afterSrc = frameSrc(step.after_frame);
      before.hidden = !beforeSrc;
      after.hidden = !afterSrc;
      noBefore.hidden = !!beforeSrc;
      noAfter.hidden = !!afterSrc;
      if (beforeSrc) before.src = beforeSrc;
      if (afterSrc) after.src = afterSrc;
      noBefore.textContent = beforeSrc ? "" :
        (current === 0
          ? "初始观察帧未随结果目录保留（obs_stage 结束即清）"
          : "该帧未随结果目录保留");
      noAfter.textContent = afterSrc ? "" :
        (steps.length && current === steps.length - 1
          ? "终态动作未记录后续观察帧"
          : "该帧未随结果目录保留");
      capBefore.textContent = "执行前（第 " + (current + 1) + " 步）" +
        (step.before_frame ? " · " + step.before_frame : "");
      capAfter.textContent = "执行后" + (step.after_frame ? " · " + step.after_frame : "");
      document.getElementById("step-label").textContent =
        "第 " + (current + 1) + " / " + steps.length + " 步";
      document.getElementById("prev").disabled = current === 0;
      document.getElementById("next").disabled = current >= steps.length - 1;
      renderTimeline();
      detail.innerHTML = renderDetail(step);
      renderEvidence(step);
    }

    function stepFromHash() {
      var match = /step=(\d+)/.exec(window.location.hash || "");
      if (!match) return null;
      var index = parseInt(match[1], 10) - 1;
      return index >= 0 && index < steps.length ? index : null;
    }

    document.getElementById("prev").addEventListener("click", function () {
      if (current > 0) { current -= 1; render(); }
    });
    document.getElementById("next").addEventListener("click", function () {
      if (current < steps.length - 1) { current += 1; render(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft" && current > 0) { current -= 1; render(); }
      if (event.key === "ArrowRight" && current < steps.length - 1) { current += 1; render(); }
    });
    var toggle = document.getElementById("toggle-evidence");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var box = document.getElementById("evidence");
        box.hidden = !box.hidden;
        toggle.textContent = box.hidden ? "运行证据（原始 JSON）" : "收起运行证据";
      });
    }
    renderCost();
    renderChapters();
    renderLanes();
    var initial = stepFromHash();
    if (initial !== null) current = initial;
    render();
    window.addEventListener("hashchange", function () {
      var next = stepFromHash();
      if (next !== null) { current = next; render(); }
    });
  }

  T.initPlayer = initPlayer;
  initPlayer();
})(window);
