/* 0 步任务的失败态：没有轨迹时，把「为什么没有轨迹」讲清楚。
 *
 * 本批次 20 题里有 9 题在 import 期即死（0 步 / 0 次模型调用 / 0 帧）。
 * 这些页面若只留一个空盒子，读者无法区分「模型没做」与「环境没起来」。
 */
(function (global) {
  "use strict";

  var T = global.TANDEM;
  var esc = T.esc;
  var kv = T.detail.kv;

  function roleBreakdown(calls) {
    var counts = {};
    calls.forEach(function (call) {
      var role = call.role || "unknown";
      counts[role] = (counts[role] || 0) + 1;
    });
    return Object.keys(counts).map(function (role) {
      return role + " × " + counts[role];
    });
  }

  function renderZeroState() {
    var task = T.payload.task;
    var steps = task.steps || [];
    var media = document.getElementById("stage-media");
    var box = document.getElementById("zero-state");
    var detail = document.getElementById("detail");
    var nav = document.getElementById("timeline");
    if (steps.length) {
      if (media) media.hidden = false;
      if (box) box.hidden = true;
      if (nav) nav.hidden = false;
      return;
    }
    if (media) media.hidden = true;
    if (nav) nav.hidden = true;
    if (!box) return;
    box.hidden = false;

    var calls = task.llm_calls || [];
    var roles = roleBreakdown(calls);
    var reason = task.exception_type || task.stop_reason || "原因未记录";
    var wall = task.wall_seconds;
    box.innerHTML =
      "<h2>未产生任何动作（0 步）</h2>" +
      "<p>该任务在任何动作执行之前就终止了 —— 因此没有轨迹、没有截图、没有排序服务调用。" +
      "终止原因：<b>" + esc(reason) + "</b>" +
      (typeof wall === "number" ? "，耗时 " + wall.toFixed(3) + "s。" : "。") + "</p>" +
      "<p class='muted'>终止前模型共调用 " + calls.length + " 次" +
      (roles.length ? "（" + esc(roles.join("、")) + "）" : "") +
      "。若调用数也为 0，说明失败发生在模型被调用之前（环境 / 依赖 / 配置）。" +
      "完整原始记录见页面底部「运行证据」。</p>";

    if (detail) {
      detail.innerHTML =
        "<h3>执行摘要</h3>" +
        kv([
          ["状态", esc(task.status || "-")],
          ["官方评分", task.scored && task.score !== null && task.score !== undefined
            ? String(task.score) : "未出分（不计 0 分）"],
          ["终止原因", esc(reason)],
          ["决策步", "0"],
          ["JEV 排序", String(task.jev_calls === undefined ? "-" : task.jev_calls) + " 次"],
          ["模型调用", String(calls.length) + " 次" +
            (roles.length ? "（" + esc(roles.join("、")) + "）" : "")],
          ["真实用时", typeof wall === "number" ? wall.toFixed(3) + "s" : "-"]
        ]);
    }
  }

  T.fail = { renderZeroState: renderZeroState };
})(window);
