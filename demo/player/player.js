/* Tandem demo 播放器内核：共享工具与索引页。页面模块挂在 window.TANDEM 上。 */
(function (global) {
  "use strict";

  var payloadEl = document.getElementById("payload");
  var payload = payloadEl ? JSON.parse(payloadEl.textContent) : null;

  function esc(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function num(value) {
    return typeof value === "number" ? value.toLocaleString("en-US") : "-";
  }
  function secs(value) {
    return typeof value === "number" ? value.toFixed(1) + "s" : "-";
  }
  function clock(seconds) {
    if (typeof seconds !== "number") return "-";
    var m = Math.floor(seconds / 60);
    var s = Math.floor(seconds % 60);
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  /* ---------------- 索引页：可排序对比表 ---------------- */
  function initIndex() {
    var table = document.querySelector("table.grid");
    if (!table) return;
    var tbody = table.tBodies[0];
    var headers = Array.prototype.slice.call(table.tHead.rows[0].cells);
    headers.forEach(function (th, index) {
      th.addEventListener("click", function () {
        var asc = th.dataset.dir !== "asc";
        headers.forEach(function (other) { delete other.dataset.dir; });
        th.dataset.dir = asc ? "asc" : "desc";
        var rows = Array.prototype.slice.call(tbody.rows);
        rows.sort(function (a, b) {
          var av = a.cells[index].textContent.trim();
          var bv = b.cells[index].textContent.trim();
          var an = parseFloat(av.replace(/[^0-9.-]/g, ""));
          var bn = parseFloat(bv.replace(/[^0-9.-]/g, ""));
          var bothNum = !isNaN(an) && !isNaN(bn) && av !== "" && bv !== "";
          var cmp = bothNum ? an - bn : av.localeCompare(bv);
          return asc ? cmp : -cmp;
        });
        rows.forEach(function (row) { tbody.appendChild(row); });
      });
    });
  }

  global.TANDEM = {
    payload: payload,
    esc: esc,
    num: num,
    secs: secs,
    clock: clock,
    initIndex: initIndex
  };
  initIndex();
})(window);
