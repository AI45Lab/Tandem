/* 启动：读内联数据 → 主题 → 路由 → 首屏披露条 */
(function () {
  "use strict";
  var TD = window.TD;

  TD.state.overview = TD.readInline("data-overview");
  TD.state.compare = TD.readInline("data-compare");

  try {
    var saved = localStorage.getItem("td-theme");
    if (saved) TD.setTheme(saved);
  } catch (error) { /* file:// 下 localStorage 可能不可用 */ }

  var toggle = document.getElementById("theme-toggle");
  if (toggle) toggle.addEventListener("click", TD.toggleTheme);

  var snapshot = document.getElementById("snapshot");
  if (snapshot && TD.state.overview) {
    var official = TD.state.overview.official || {};
    snapshot.textContent = "官方数据 " + (official.snapshot || "—") +
      " · 价格表 " + ((TD.state.overview.ours || {}).price || {}).snapshot + "";
  }

  window.addEventListener("hashchange", TD.render);
  TD.renderDisclaimer();
  TD.render();
})();
