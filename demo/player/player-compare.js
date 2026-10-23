/* 两个 run 的对比页模块：逐题并排 + 差值（成本 / 耗时 / 准确率）。 */
(function (global) {
  "use strict";

  var T = global.TANDEM;
  var payload = T.payload;
  var esc = T.esc;
  var num = T.num;
  var secs = T.secs;

  function cellOf(runId, taskId) {
    var entry = null;
    payload.tasks.forEach(function (item) { if (item.task_id === taskId) entry = item; });
    return entry && entry.runs[runId] ? entry.runs[runId] : null;
  }

  function scoreText(cell) {
    if (!cell) return "—";
    if (!cell.scored || cell.score === null) return "未出分";
    return cell.score.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }

  function delta(a, b, unit, lowerIsBetter) {
    if (a === null || b === null || typeof a !== "number" || typeof b !== "number") return "";
    var diff = b - a;
    if (Math.abs(diff) < 1e-9) return '<span class="delta same">持平</span>';
    var better = lowerIsBetter ? diff < 0 : diff > 0;
    var sign = diff > 0 ? "+" : "";
    var text = unit === "s" ? diff.toFixed(1) + "s" : num(Math.round(diff));
    return '<span class="delta ' + (better ? "better" : "worse") + '">' + sign + text + "</span>";
  }

  function render() {
    var selA = document.getElementById("cmp-a");
    var selB = document.getElementById("cmp-b");
    var summary = document.getElementById("cmp-summary");
    var table = document.getElementById("cmp-table");
    if (!selA || !selB || !summary || !table) return;

    var a = selA.value;
    var b = selB.value;
    var runA = null;
    var runB = null;
    payload.runs.forEach(function (run) {
      if (run.run_id === a) runA = run;
      if (run.run_id === b) runB = run;
    });
    if (!runA || !runB) return;

    var rows = "";
    payload.tasks.forEach(function (entry) {
      var ca = cellOf(a, entry.task_id);
      var cb = cellOf(b, entry.task_id);
      if (!ca || !cb) return;
      rows += "<tr>" +
        "<td><b>" + esc(entry.task_id) + "</b></td>" +
        "<td class='" + (ca.scored ? "ok" : "miss") + "'>" + esc(scoreText(ca)) + "</td>" +
        "<td class='" + (cb.scored ? "ok" : "miss") + "'>" + esc(scoreText(cb)) + "</td>" +
        "<td>" + delta(ca.score, cb.score, "", true) + "</td>" +
        "<td>" + num(ca.tokens) + "</td>" +
        "<td>" + num(cb.tokens) + "</td>" +
        "<td>" + delta(ca.tokens, cb.tokens, "", true) + "</td>" +
        "<td>" + secs(ca.wall_seconds) + "</td>" +
        "<td>" + secs(cb.wall_seconds) + "</td>" +
        "<td>" + delta(ca.wall_seconds, cb.wall_seconds, "s", true) + "</td>" +
        "<td>" + ca.steps + " / " + cb.steps + "</td>" +
        "<td>" + ca.llm_calls + " / " + cb.llm_calls + "</td>" +
        "<td>" + ca.fast_calls + " / " + cb.fast_calls + "</td>" +
        "</tr>";
    });

    var ta = runA.totals;
    var tb = runB.totals;
    function card(run, totals) {
      return "<article class='card'><h3>" + esc(run.run_id) + "</h3>" +
        "<p class='sub'>大脑=" + esc(run.slow_model) + " · 小脑=" + esc(run.fast_model) +
        " · git " + esc(run.git_describe) + "</p><dl>" +
        "<div><dt>已出分</dt><dd>" + totals.scored + " / " + totals.total + "</dd></div>" +
        "<div><dt>均分</dt><dd>" + (totals.average_score === null ? "—" : totals.average_score) + "</dd></div>" +
        "<div><dt>token</dt><dd>" + num(totals.cost.prompt_tokens + totals.cost.completion_tokens) + "</dd></div>" +
        "<div><dt>LLM 调用</dt><dd>" + totals.cost.calls + "</dd></div>" +
        "<div><dt>快模型排序</dt><dd>" + totals.fast_calls + "</dd></div>" +
        "<div><dt>总耗时</dt><dd>" + totals.wall_seconds_total + "s</dd></div>" +
        "</dl></article>";
    }
    summary.innerHTML = "<div class='cmp-cards'>" +
      "<div>" + card(runA, ta) + "</div><div>" + card(runB, tb) + "</div></div>";

    table.innerHTML = "<table class='grid cmpgrid'><thead><tr>" +
      "<th>任务</th><th>A 分数</th><th>B 分数</th><th>Δ分数</th>" +
      "<th>A token</th><th>B token</th><th>Δtoken</th>" +
      "<th>A 耗时</th><th>B 耗时</th><th>Δ耗时</th>" +
      "<th>步数 A/B</th><th>LLM A/B</th><th>小脑排序 A/B</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table>";
  }

  function initCompare() {
    var selA = document.getElementById("cmp-a");
    var selB = document.getElementById("cmp-b");
    if (!selA || !selB) return;
    selA.addEventListener("change", render);
    selB.addEventListener("change", render);
    if (payload.runs.length > 1) {
      selA.selectedIndex = 0;
      selB.selectedIndex = payload.runs.length - 1;
    }
    render();
  }

  T.initCompare = initCompare;
  initCompare();
})(window);
