/* 任务页的详情渲染：规划 / 候选与排序 / 编译后动作 / 执行回执与独立验证 / 终态双确认。 */
(function (global) {
  "use strict";

  var T = global.TANDEM;
  var esc = T.esc;

  function rankTable(rows, winnerId, label) {
    if (!rows || !rows.length) return "";
    var max = 0;
    rows.forEach(function (row) {
      if (typeof row.score === "number" && row.score > max) max = row.score;
    });
    var body = rows.map(function (row) {
      var id = row.id || row.operation || "";
      var name = row.description || row.target_name || id;
      var pct = max > 0 && typeof row.score === "number" ? Math.round(row.score / max * 100) : 0;
      return "<tr class='" + (id && id === winnerId ? "win" : "") + "'>" +
        "<td>" + esc(label ? row.operation : name) + "</td>" +
        "<td class='num'>" + (typeof row.score === "number" ? row.score.toFixed(4) : "-") + "</td>" +
        "<td><span class='bar' style='width:" + pct + "%'></span></td></tr>";
    }).join("");
    return "<table class='rank'><thead><tr><th>" + (label ? "操作" : "候选") +
      "</th><th class='num'>softmax 分数</th><th>相对强度</th></tr></thead><tbody>" +
      body + "</tbody></table>";
  }

  function kv(pairs) {
    return "<div class='kv'>" + pairs.map(function (pair) {
      return "<span>" + esc(pair[0]) + "</span><span>" + pair[1] + "</span>";
    }).join("") + "</div>";
  }

  function renderDetail(step) {
    var plan = step.plan || {};
    var action = step.action || {};
    var params = action.parameters || {};
    var paramText = Object.keys(params).map(function (key) {
      return key + "=" + JSON.stringify(params[key]);
    }).join("  ");
    var ranking = step.ranking || {};
    var verification = step.verification || {};
    var receipt = step.receipt || {};
    var proposals = plan.action_proposals || [];

    var html = "<h3>规划（planner）</h3>";
    html += kv([
      ["当前目标", esc(plan.current_goal || "-")],
      ["预期观察", esc(plan.expected_observation || "-")],
      ["路由", esc(plan.route || "-")],
      ["任务状态", esc(plan.task_status || "-")],
      ["提案数", String(proposals.length)]
    ]);
    if (proposals.length) {
      html += "<pre>" + esc(proposals.map(function (p, i) {
        return (i + 1) + ". " + p.operation + " → " + (p.target_name || "") +
          (p.target_role ? " [" + p.target_role + "]" : "") +
          (p.target_id ? "  (" + p.target_id + ")" : "");
      }).join("\n")) + "</pre>";
    }

    if (ranking.winner || (ranking.operation_ranked || []).length) {
      html += "<h3>候选与排序（" + esc(ranking.score_type || "ranking") + "）</h3>";
      html += "<p class='note'>分数为 softmax 输出，非校准正确率；margin=" +
        (typeof ranking.operation_margin === "number"
          ? ranking.operation_margin.toFixed(4) : "-") +
        "，排序延迟 " + (typeof ranking.latency_ms === "number"
          ? ranking.latency_ms.toFixed(0) + "ms" : "-") + "</p>";
      if ((ranking.operation_ranked || []).length) {
        html += "<h3>操作级排序</h3>" +
          rankTable(ranking.operation_ranked, ranking.winner && ranking.winner.operation, true);
      }
      if ((ranking.action_ranked || []).length) {
        html += "<h3>目标级排序</h3>" +
          rankTable(ranking.action_ranked, ranking.winner && ranking.winner.id, false);
      }
    }

    html += "<h3>编译后动作</h3>";
    html += kv([
      ["类型", esc(action.kind || "-")],
      ["动作", esc(action.action_type || "-")],
      ["参数", esc(paramText || "-")],
      ["目标", esc(action.target_id || "-")],
      ["描述", esc(action.description || "-")]
    ]);
    if (action.command) {
      html += "<h3>CLI 命令</h3><pre>" + esc(action.command) + "</pre>";
    }

    if (Object.keys(verification).length || Object.keys(receipt).length) {
      html += "<h3>执行回执与独立验证</h3>";
      html += kv([
        ["回执 kind", esc(receipt.kind || "-")],
        ["returncode", esc(receipt.returncode === undefined ? "-" : receipt.returncode)],
        ["验证结论", esc(verification.outcome || "-")],
        ["状态变化", esc(String(verification.state_changed === undefined
          ? "-" : verification.state_changed))],
        ["证据", esc(verification.evidence || "-")],
        ["stdout", "<pre>" + esc((receipt.stdout || "").slice(0, 900) || "-") + "</pre>"],
        ["stderr", "<pre>" + esc((receipt.stderr || "").slice(0, 500) || "-") + "</pre>"]
      ]);
      var checks = verification.requirement_checks || [];
      if (checks.length) {
        html += "<h3>需求逐条核验</h3><pre>" + esc(checks.map(function (c) {
          return c.id + " [" + c.status + "] " + (c.evidence || "");
        }).join("\n")) + "</pre>";
      }
    }
    var terminal = step.terminal || {};
    if (Object.keys(terminal).length) {
      html += "<h3>终态双确认</h3><pre>" +
        esc(JSON.stringify(terminal.completion_check || terminal, null, 2)) + "</pre>";
    }
    return html;
  }

  T.detail = { rankTable: rankTable, kv: kv, renderDetail: renderDetail };
})(window);
