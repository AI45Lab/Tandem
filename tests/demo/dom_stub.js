/* 最小 DOM 桩：让站点的视图代码能在 node 里跑起来。
 *
 * 两个脚本共用：
 * - tests/demo/render_stub.js   渲染冒烟（断言）
 * - tests/demo/flow_svg_dump.js  流程图导出（给 Pillow 栅格化做视觉检查）
 *
 * 桩要满足的坑（都是真踩过的）：
 * - nodeType 必须有：站点的 el() 用它判断「这是不是个节点」，没有的话
 *   子节点会被当成普通对象渲染成 [object Object]
 * - setAttribute('class', …) 必须同步进类列表：查询要认
 * - removeChild/replaceChild 必须真删：站点的 clear() 是
 *   while(firstChild) removeChild(...)，不删就会死循环
 */

function makeEl(tag) {
  const el = {
    nodeType: 1,
    tagName: tag, _classes: [], _text: '', innerHTML: '', value: '',
    style: {}, dataset: {}, children: [], attributes: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) {
        if (on === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); }
        else if (on) { this._set.add(c); } else { this._set.delete(c); }
      }
    },
    appendChild(c) { this.children.push(c); if (c) c.parentNode = this; return c; },
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
      if (k === 'class') this._classes = String(v).split(/\s+/).filter(Boolean);
    },
    getAttribute(k) { return this.attributes[k]; },
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

/* 装一套全局 DOM。opts.fetchResponse 可选：给 fetch 塞一个固定的响应。 */
function installDom(opts) {
  const options = opts || {};
  const appEl = makeEl('div');
  const documentBody = makeEl('body');
  global.document = {
    createElement: makeEl,
    createElementNS: (ns, tag) => makeEl(tag),   // SVG 节点
    addEventListener() {},
    removeEventListener() {},
    createTextNode: (t) => makeEl('#text'),
    getElementById: (id) => {
      if (id === 'data-overview' && options.overview !== undefined) {
        const e = makeEl('script'); e.textContent = JSON.stringify(options.overview); return e;
      }
      if (id === 'data-compare' && options.compare !== undefined) {
        const e = makeEl('script'); e.textContent = JSON.stringify(options.compare); return e;
      }
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
  global.setTimeout = (fn) => { try { fn(); } catch (e) { /* stub 里忽略 */ } return 0; };
  global.setInterval = () => 0;
  global.clearInterval = () => {};
  global.fetch = options.fetch || (() => Promise.reject(new Error('unexpected fetch')));
  return { appEl, documentBody };
}

/* DOM 树 → 纯 JSON（给 Python 端栅格化用） */
function serializeNode(node) {
  return {
    tag: node.tagName,
    class: (node._classes || []).join(' '),
    attrs: Object.assign({}, node.attributes),
    text: node._ownText !== undefined ? node._ownText : '',
    children: (node.children || [])
      .filter((c) => c && c.tagName && c.tagName !== '#text')
      .map(serializeNode)
  };
}

module.exports = { makeEl, installDom, serializeNode };
