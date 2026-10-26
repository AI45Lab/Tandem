
const fs = require('fs');
const path = require('path');

function makeEl(tag) {
  const el = {
    tagName: tag, className: '', textContent: '', innerHTML: '', value: '',
    style: {}, dataset: {}, children: [], attributes: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) { if (on === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); } else if (on) { this._set.add(c); } else { this._set.delete(c); } }
    },
    appendChild(c) { this.children.push(c); return c; },
    // 真删：站点的 clear() 是 while(firstChild) removeChild(...)，不删就会死循环
    removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; },
    replaceChild(n, o) { this.children = this.children.filter((x) => x !== o); this.children.push(n); return o; },
    replaceWith(n) { if (this.parentNode) this.parentNode.replaceChild(n, this); return n; },
    insertBefore(n) { this.children.push(n); return n; },
    addEventListener() {}, removeEventListener() {},
    setAttribute(k, v) { this.attributes[k] = v; }, getAttribute(k) { return this.attributes[k]; },
    querySelectorAll() { return []; }, querySelector() { return null; },
    closest() { return null; }, getBoundingClientRect() { return { top: 0, left: 0 }; },
    scrollIntoView() {}, focus() {},
    get firstChild() { return this.children[0] || null; },
    get parentNode() { return null; }
  };
  return el;
}

const overview = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const compare = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const episode = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

const appEl = makeEl('div');
global.document = {
  createElement: makeEl,
  createTextNode: (t) => makeEl('#text'),
  getElementById: (id) => {
    if (id === 'data-overview') { const e = makeEl('script'); e.textContent = JSON.stringify(overview); return e; }
    if (id === 'data-compare') { const e = makeEl('script'); e.textContent = JSON.stringify(compare); return e; }
    if (id === 'app') return appEl;
    return null;
  },
  querySelectorAll: () => [],
  querySelector: () => null,
  body: makeEl('body')
};
global.window = { addEventListener() {}, removeEventListener() {}, location: { hash: '#/' } };
global.location = { hash: '#/' };
global.localStorage = { getItem: () => null, setItem() {} };
global.performance = { now: () => 0 };
// 给一个"未来"的时间戳：p 直接到 1，避免计数动画再递归调 rAF（同步 stub 会死循环）
global.requestAnimationFrame = (fn) => { fn(1000); return 0; };
global.setTimeout = (fn) => { try { fn(); } catch (e) {} return 0; };
global.setInterval = () => 0;
global.clearInterval = () => {};
global.fetch = (url) => {
  const name = String(url);
  if (name.includes('/assets/data/episode/')) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(episode) });
  }
  if (name.includes('/assets/data/sai_traj/')) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ task: '004', run: 'r', score: 0.8, steps: [], frames: {} }) });
  }
  return Promise.reject(new Error('unexpected fetch ' + name));
};

const web = process.argv[5];
for (const file of ['app.js', 'views/home.js', 'views/results.js', 'views/mechanism.js', 'views/browser.js']) {
  const code = fs.readFileSync(path.join(web, 'assets', file), 'utf8');
  // eslint-disable-next-line no-eval
  (0, eval)(code);
}

function collectText(node, acc) {
  acc = acc || [];
  if (node.textContent) acc.push(String(node.textContent));
  (node.children || []).forEach(function (c) { collectText(c, acc); });
  return acc;
}

function run(name, fn, ...args) {
  const host = makeEl('div');
  try {
    fn(host, ...args);
  } catch (error) {
    console.error('FAIL ' + name + ': ' + (error && error.stack ? error.stack : error));
    process.exit(1);
  }
  if (!host.children.length) {
    console.error('FAIL ' + name + ': 没有渲染出任何节点');
    process.exit(1);
  }
  console.log('ok ' + name + ' (' + host.children.length + ' 个顶层节点)');
}

run('home', window.TD.views.home);
run('results', window.TD.sections.results);
run('browser', window.TD.views.browser);

/* 走真实路由：'#/' 解析出的默认视图必须存在（踩过的坑：默认名没跟着改，
   页面报「视图渲染失败：view is not a function」） */
global.location.hash = '#/';
try {
  window.TD.render();
} catch (error) {
  console.error('FAIL route: ' + (error && error.stack ? error.stack : error));
  process.exit(1);
}
const app = document.getElementById('app');
const text = collectText(app).join(' ');
if (text.indexOf('视图渲染失败') >= 0) {
  console.error('FAIL route: 首页渲染报错 → ' + text.slice(0, 200));
  process.exit(1);
}
if (!text.length) {
  console.error('FAIL route: 首页没有内容');
  process.exit(1);
}
console.log('ok route (#/)');

global.location.hash = '#/browser';
window.TD.render();
const app2 = document.getElementById('app');
const text2 = collectText(app2).join(' ');
if (text2.indexOf('视图渲染失败') >= 0) {
  console.error('FAIL route browser: ' + text2.slice(0, 200));
  process.exit(1);
}
console.log('ok route (#/browser)');
process.exit(0);
