/* 轨迹页：左任务轨 / 中双轨播放器 / 右机制·评估·成本面板
 *
 * 逐题数据从 `assets/data/episode/<run>/<task>.json` 取（按需加载）。
 * file:// 打开时浏览器会拦 fetch —— 此时给出明确提示，而不是白屏。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function rail(overview, currentTask) {
    var items = (overview.rows || []).map(function (row) {
      var score = row.score === null || row.score === undefined ? "—" : row.score.toFixed(2);
      return TD.el("div", {
        class: "item" + (row.task === currentTask ? " active" : ""),
        onclick: function () { TD.navigate("#/task/" + row.run_id + "/" + row.task); },
        title: row.stop || ""
      }, [
        TD.el("span", { class: "tid", text: row.task }),
        TD.el("span", { class: "sc", text: score })
      ]);
    });
    return TD.el("div", { class: "card rail" }, [TD.el("h2", { text: "任务轨" })].concat(items));
  }

  TD.views.task = function (container, params) {
    var overview = TD.state.overview;
    var runId = params[0];
    var taskId = params[1];
    var workbench = TD.el("div", { class: "workbench" });
    container.appendChild(workbench);
    workbench.appendChild(rail(overview || { rows: [] }, taskId));

    var center = TD.el("div", { class: "stack" });
    var side = TD.el("div", { class: "stack" });
    workbench.appendChild(center);
    workbench.appendChild(side);

    center.appendChild(TD.el("div", { class: "card" }, [
      TD.el("h2", { text: "载入中…" })
    ]));

    TD.loadEpisode(runId, taskId, function (episode, error) {
      TD.clear(center);
      TD.clear(side);
      if (!episode) {
        center.appendChild(TD.el("div", { class: "callout bad" }, [
          TD.el("strong", { text: "载入逐题数据失败：" + (error || "未知错误") }),
          TD.el("div", { class: "small", style: "margin-top:6px", text:
            "浏览器用 file:// 打开时会拦截本地 fetch。请在 demo/site 下跑 " +
            "python3 -m http.server 8899，再访问 http://localhost:8899/ 。" })
        ]));
        return;
      }
      TD.state.episode = episode;
      TD.player.renderDual(center, episode);
      TD.player.renderSide(side, episode);
    });
  };
})();
