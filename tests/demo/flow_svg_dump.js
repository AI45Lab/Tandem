/* 把首页**真实渲染出来**的流程图导成 JSON，交给 demo/render_svg.py 栅格化。
 *
 * 为什么要有这条链路：本机没有浏览器，截图 smoke 做不了。但「框里字出框」
 * 「标签互相压字」这类问题是**能用真实字体度量判定**的——把真实 SVG 拿出来，
 * 用 Pillow + Noto Sans CJK 量一遍，既能出图给人看，也能给机器可判定的结论。
 *
 * 用法：
 *   node tests/demo/flow_svg_dump.js <overview.json> <compare.json> <episode.json> \
 *        <site_dir> /tmp/flow.json
 */
const fs = require('fs');
const path = require('path');
const { makeEl, installDom, serializeNode } = require('./dom_stub');

const overview = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const compare = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const episode = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const web = process.argv[5];
const out = process.argv[6];

installDom({
  overview,
  compare,
  fetch: (url) => {
    if (String(url).includes('assets/data/episode/')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(episode) });
    }
    return Promise.reject(new Error('unexpected fetch ' + url));
  }
});

/* 加载 app + 视图 + boot（boot 负责把内联数据读进 TD.state 并首屏渲染） */
for (const file of ['app.js', 'views/flow.js', 'views/facts.js', 'views/home.js', 'boot.js']) {
  // eslint-disable-next-line no-eval
  (0, eval)(fs.readFileSync(path.join(web, 'assets', file), 'utf8'));
}

global.location.hash = '#/';
window.TD.render();

(async function () {
  /* 等逐题数据兑现（fetch 是 Promise，setImmediate 让微任务先跑完） */
  for (let i = 0; i < 20; i += 1) await new Promise((r) => setImmediate(r));
  const svg = document.querySelector('.flow');
  if (!svg) {
    console.error('FAIL: 没找到流程图（首页没渲染出来？）');
    process.exit(1);
  }
  fs.writeFileSync(out, JSON.stringify(serializeNode(svg), null, 1));
  console.log('ok svg dump: ' + out);
})();
