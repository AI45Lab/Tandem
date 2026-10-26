"""用 node 跑一遍站点视图代码（最小 DOM stub）。

**为什么要有这个**：站点是纯前端，改视图名、改结构都可能让首页直接白屏
（踩过：「view is not a function」——路由默认视图名没跟着改名）。
本机没有浏览器，但可以用 node + 最小 DOM stub 把 `TD.views.*` 真跑一遍，
把"渲染期崩不崩"这类问题挡在测试里。

node 不在的环境自动跳过（CI 可能没有 node）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "demo" / "web"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node 不在 PATH，跳过渲染冒烟")

# 最小 DOM stub：够站点视图跑起来，不追求规范
STUB = r"""
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
"""


@pytest.mark.skipif(NODE is None, reason="node 不在 PATH")
def test_views_render_without_error(tmp_path):
    """把首页/结果/轨迹浏览三个视图真跑一遍，不许抛异常。"""
    site = REPO_ROOT / "demo" / "site"
    overview_path = site / "assets" / "data" / "overview.json"
    compare_path = site / "assets" / "data" / "compare.json"
    if not overview_path.is_file():
        pytest.skip("站点还没构建（demo/site/assets/data/overview.json 不存在）")
    episode_path = next((site / "assets" / "data" / "episode").rglob("*.json"), None)
    if episode_path is None:
        pytest.skip("站点里没有逐题数据，跳过渲染冒烟")

    script = tmp_path / "render.js"
    script.write_text(STUB, encoding="utf-8")
    result = subprocess.run(
        [NODE, str(script), str(overview_path), str(compare_path), str(episode_path), str(WEB)],
        capture_output=True, text=True, check=False, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok home" in result.stdout
    assert "ok browser" in result.stdout
    assert "ok route (#/)" in result.stdout
    assert "ok route (#/browser)" in result.stdout
