
const fs = require('fs');
const path = require('path');

function makeEl(tag) {
  const el = {
    // nodeType 必须有：站点的 el() 用它判断「这是不是个节点」，没有的话
    // 子节点会被当成普通对象渲染成 [object Object]
    nodeType: 1,
    tagName: tag, _classes: [], _text: '', innerHTML: '', value: '',
    style: {}, dataset: {}, children: [], attributes: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) { if (on === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); } else if (on) { this._set.add(c); } else { this._set.delete(c); } }
    },
    appendChild(c) { this.children.push(c); if (c) c.parentNode = this; return c; },
    // 真删：站点的 clear() 是 while(firstChild) removeChild(...)，不删就会死循环
    removeChild(c) { this.children = this.children.filter((x) => x !== c); if (c) c.parentNode = null; return c; },
    replaceChild(n, o) {
      this.children = this.children.filter((x) => x !== o);
      this.children.push(n);
      if (n) n.parentNode = this;
      if (o) o.parentNode = null;
      return o;
    },
    replaceWith(n) { if (this.parentNode) this.parentNode.replaceChild(n, this); return n; },
    insertBefore(n) { this.children.push(n); return n; },
    addEventListener() {}, removeEventListener() {},
    setAttribute(k, v) {
      this.attributes[k] = String(v);
      // SVG 节点用 setAttribute('class', ...) 设类，查询也要认
      if (k === 'class') this._classes = String(v).split(/\s+/).filter(Boolean);
    }, getAttribute(k) { return this.attributes[k]; },
    querySelectorAll(sel) {
      const want = String(sel || '').replace(/^\./, '');
      const out = [];
      (function walk(node) {
        (node.children || []).forEach(function (c) {
          if (want && (c._classes || []).indexOf(want) >= 0) out.push(c);
          walk(c);
        });
      })(this);
      return out;
    },
    querySelector() { return this.querySelectorAll('.' + String(arguments[0] || '').replace(/^\./, ''))[0] || null; },
    closest() { return null; }, getBoundingClientRect() { return { top: 0, left: 0 }; },
    scrollIntoView() {}, focus() {},
    get className() { return this._classes.join(' '); },
    set className(v) { this._classes = String(v).split(/\s+/).filter(Boolean); },
    get textContent() {
      if (this._ownText !== undefined) return this._ownText;
      return this.children.map((c) => (c && c.textContent) || '').join('');
    },
    set textContent(v) { this._ownText = String(v); this.children = []; },
    get firstChild() { return this.children[0] || null; },
    parentNode: null
  };
  return el;
}

const overview = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const compare = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const episode = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

const appEl = makeEl('div');
const documentBody = makeEl('body');
global.document = {
  createElement: makeEl,
  createElementNS: (ns, tag) => makeEl(tag),   // SVG 节点
  addEventListener() {},
  removeEventListener() {},
  createTextNode: (t) => makeEl('#text'),
  getElementById: (id) => {
    if (id === 'data-overview') { const e = makeEl('script'); e.textContent = JSON.stringify(overview); return e; }
    if (id === 'data-compare') { const e = makeEl('script'); e.textContent = JSON.stringify(compare); return e; }
    if (id === 'app') return appEl;
    return null;
  },
  querySelectorAll(sel) { return documentBody.querySelectorAll(sel); },
  querySelector(sel) { return documentBody.querySelector(sel); },
  body: documentBody
};
documentBody.appendChild(appEl);
global.window = { addEventListener() {}, removeEventListener() {}, location: { hash: '#/' } };
global.location = { hash: '#/' };
global.localStorage = { getItem: () => null, setItem() {} };
global.performance = { now: () => 0 };
// 给一个"未来"的时间戳：p 直接到 1，避免计数动画再递归调 rAF（同步 stub 会死循环）
global.requestAnimationFrame = (fn) => { fn(1000); return 0; };
const realSetTimeout = setTimeout;
global.setTimeout = (fn) => { try { fn(); } catch (e) {} return 0; };
global.setInterval = () => 0;
global.clearInterval = () => {};
global.fetch = (url) => {
  const name = String(url);
  if (name.includes('assets/data/episode/')) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(episode) });
  }
  if (name.includes('assets/data/sai_traj/')) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ task: '004', run: 'r', score: 0.8, steps: [], frames: {} }) });
  }
  return Promise.reject(new Error('unexpected fetch ' + name));
};

const web = process.argv[5];
for (const file of ['app.js', 'views/flow.js', 'views/home.js', 'views/results.js', 'views/mechanism.js', 'views/browser.js', 'boot.js']) {
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

/* 机制段是异步构建的（等逐题数据兑现）——等它画完，断言首页的流程图真的出来了。
   注意：必须在切到 #/browser 之前断言，否则 app 里已经是轨迹浏览页了。 */
realSetTimeout(function () {
  const flows = document.querySelectorAll('.flow');
  const nodes = document.querySelectorAll('.fnode');
  const mini = document.querySelectorAll('.mini');
  const cards = document.querySelectorAll('.mech-card');
  if (!flows.length) { console.error('FAIL: 概念流程图没渲染出来'); process.exit(1); }
  if (nodes.length < 6) { console.error('FAIL: 流程图节点不足：' + nodes.length); process.exit(1); }
  if (!mini.length) { console.error('FAIL: 迷你图没渲染出来'); process.exit(1); }
  if (cards.length < 5) { console.error('FAIL: 环节卡片不足：' + cards.length); process.exit(1); }
  console.log('ok flow: ' + flows.length + ' 图 / ' + nodes.length + ' 节点 / ' +
              mini.length + ' 迷你图 / ' + cards.length + ' 卡片');

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
}, 400);
