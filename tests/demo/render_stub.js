const fs = require('fs');
const path = require('path');
const { makeEl, installDom } = require('./dom_stub');

const overview = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const compare = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const episode = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

const realSetTimeout = setTimeout;
installDom({
  overview,
  compare,
  fetch: (url) => {
    const name = String(url);
    if (name.includes('assets/data/episode/')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(episode) });
    }
    if (name.includes('assets/data/sai_traj/')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ task: '004', run: 'r', score: 0.8, steps: [], frames: {} }) });
    }
    return Promise.reject(new Error('unexpected fetch ' + name));
  }
});

const web = process.argv[5];
for (const file of ['app.js', 'views/flow.js', 'views/facts.js', 'views/home.js', 'views/results.js', 'views/browser_player.js', 'views/browser.js', 'boot.js']) {
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

function byTag(node, tag) {
  return (node.children || []).filter(function (c) { return c && c.tagName === tag; });
}

function num(value) { return Number(value || 0); }

/* 矩形是否相交（贴边不算相交） */
function overlaps(a, b) {
  return a.x < b.x + b.w - 0.5 && b.x < a.x + a.w - 0.5 &&
         a.y < b.y + b.h - 0.5 && b.y < a.y + a.h - 0.5;
}

/* 流程图版式自检：文字不出框 + 框与框不重叠 + 标签互不压字
 *
 * 这三条正是「框中字体超出」「摆放位置不对」的机器可判定形式——
 * 截图没法做 smoke，但几何是可以断言的。 */
function checkFlowGeometry() {
  const tw = window.TD.flow.textWidth;
  const problems = [];

  document.querySelectorAll('.fedge-label').forEach(function (group) {
    const rect = byTag(group, 'rect')[0];
    const label = byTag(group, 'text')[0];
    if (!rect || !label) { problems.push('标签缺 rect/text'); return; }
    const text = String(label.textContent || '');
    const need = tw(text, 12) + 18;
    const have = num(rect.getAttribute('width'));
    if (need > have + 0.5) {
      problems.push('标签「' + text + '」字宽 ' + need.toFixed(1) + ' > 胶囊宽 ' + have.toFixed(1));
    }
  });

  const boxes = [];
  document.querySelectorAll('.fnode').forEach(function (group) {
    const rect = byTag(group, 'rect')[0];
    if (!rect) return;
    const box = {
      x: num(rect.getAttribute('x')), y: num(rect.getAttribute('y')),
      w: num(rect.getAttribute('width')), h: num(rect.getAttribute('height'))
    };
    boxes.push(box);
    byTag(group, 'text').forEach(function (label) {
      const cls = label.getAttribute('class') || '';
      const size = cls.indexOf('fnode-sub') >= 0 ? 12 : 15;
      const need = tw(String(label.textContent || ''), size) + 22;
      if (need > box.w + 0.5) {
        problems.push('节点文字「' + String(label.textContent || '') + '」字宽 ' +
          need.toFixed(1) + ' > 框宽 ' + box.w.toFixed(1));
      }
    });
  });
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      if (overlaps(boxes[i], boxes[j])) {
        problems.push('节点框 #' + i + ' 与 #' + j + ' 重叠');
      }
    }
  }

  const labels = [];
  document.querySelectorAll('.fedge-label').forEach(function (group) {
    const rect = byTag(group, 'rect')[0];
    if (!rect) return;
    labels.push({
      x: num(rect.getAttribute('x')), y: num(rect.getAttribute('y')),
      w: num(rect.getAttribute('width')), h: num(rect.getAttribute('height'))
    });
  });
  for (let i = 0; i < labels.length; i++) {
    for (let j = i + 1; j < labels.length; j++) {
      if (overlaps(labels[i], labels[j])) {
        problems.push('连线标签 #' + i + ' 与 #' + j + ' 互相压字');
      }
    }
  }
  return problems;
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
  const choices = document.querySelectorAll('.choice');
  const subs = document.querySelectorAll('.sub');
  const cards = document.querySelectorAll('.mech-card');
  if (!flows.length) { console.error('FAIL: 流程图没渲染出来'); process.exit(1); }
  if (nodes.length < 6) { console.error('FAIL: 流程图节点不足：' + nodes.length); process.exit(1); }
  if (!choices.length) { console.error('FAIL: 候选选择方块没渲染出来'); process.exit(1); }
  if (cards.length < 4) { console.error('FAIL: 环节卡片不足：' + cards.length); process.exit(1); }
  if (document.querySelectorAll('.swim').length) {
    console.error('FAIL: 真实 case 泳道还在（应已删除）'); process.exit(1);
  }
  /* 子任务要展示整轮累积的那一串，不该只有第一次规划的两三个 */
  if (subs.length < 5) { console.error('FAIL: 子任务行不足：' + subs.length); process.exit(1); }
  /* 候选要画到动作级（≥5 个具体动作），不能只有 3 个 operation */
  const candidateRows = choices.length - subs.length;
  if (candidateRows < 5) { console.error('FAIL: 动作级候选不足：' + candidateRows); process.exit(1); }

  const problems = checkFlowGeometry();
  if (problems.length) {
    console.error('FAIL flow 版式：' + problems.join('；'));
    process.exit(1);
  }
  console.log('ok flow: ' + flows.length + ' 图 / ' + nodes.length + ' 节点 / ' +
              candidateRows + ' 动作候选 / ' + subs.length + ' 子任务 / ' +
              cards.length + ' 环节卡 / 版式无出框无重叠');

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
