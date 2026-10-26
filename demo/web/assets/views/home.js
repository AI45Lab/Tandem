/* 首页 = 简介 → 机制（滚动变化）→ OSWorld v2.1 结果
 *
 * 排版参考 sai.work 的骨架：深色 hero → 粘性滚动区（滚动时内容切换）→
 * 分区（eyebrow + 引导句 + 编号卡）→ 数据区。
 */
(function () {
  "use strict";
  var TD = window.TD;

  /* ------------------------------------------------------------ 1. 简介 */
  function intro() {
    return TD.el("section", { class: "intro" }, [
      TD.el("p", { class: "eyebrow", text: "TANDEM · 快慢双模 CUA HARNESS" }),
      TD.el("h1", { class: "intro-title", text: "一个大脑，一个小脑，一起操作电脑" }),
      TD.el("p", { class: "intro-lede", html:
        "慢模型（<b>MiniMax-M3.1-Flash</b>）负责规划与纠错：给当前观察定目标、预期结果与候选动作；" +
        "快模型（<b>JEV / qwen-jev-choice</b>）只做一件事——在候选空间里排序并挑出赢家。" +
        "两者用同一份状态接力，跑在真实的 OSWorld v2.1 任务上。" }),
      TD.el("div", { class: "intro-cards" }, [
        introCard("01", "慢模型 · 大脑", "一步一次规划与纠错。stage 模式下先拆里程碑（stage_goal + milestones），核验不通过就按 stage_replan 重规划。"),
        introCard("02", "快模型 · 小脑", "不规划、不纠错，只在慢模型给的候选里排序。两阶段：先选 operation，再选 target。"),
        introCard("03", "双模协同", "慢模型的原文、快模型的排序、实际动作与核验结论，全部落在事件流里，可逐帧回看。")
      ])
    ]);
  }

  function introCard(num, title, text) {
    return TD.el("article", { class: "intro-card" }, [
      TD.el("span", { class: "card-num", text: num }),
      TD.el("h3", { text: title }),
      TD.el("p", { text: text })
    ]);
  }

  /* ------------------------------------------- 2. 机制（滚动时内容切换） */
  function mechanism(episode, taskLabel) {
    var steps = buildMechanismSteps(episode);
    var layout = TD.el("div", { class: "mech-layout" });
    var sticky = TD.el("div", { class: "mech-sticky" });
    var column = TD.el("div", { class: "mech-steps" });

    var cards = steps.map(function (step, index) {
      var card = TD.el("div", { class: "mech-card" + (index === 0 ? " active" : "") }, [
        TD.el("div", { class: "mech-card-head" }, [
          TD.el("span", { class: "mech-step-no", text: String(index + 1).padStart(2, "0") }),
          TD.el("b", { text: step.title }),
          TD.el("span", { class: "mech-role", text: step.role })
        ]),
        TD.el("pre", { class: "text", text: step.body })
      ]);
      sticky.appendChild(card);
      return card;
    });

    steps.forEach(function (step, index) {
      var block = TD.el("div", { class: "mech-step" + (index === 0 ? " active" : "") }, [
        TD.el("div", { class: "mech-step-no", text: String(index + 1).padStart(2, "0") }),
        TD.el("h3", { text: step.title }),
        TD.el("p", { text: step.desc })
      ]);
      column.appendChild(block);
    });

    /* 滚动到哪一步，粘性卡片就切到哪一步 */
    function syncActive() {
      var blocks = column.querySelectorAll(".mech-step");
      var best = 0;
      var bestDistance = Infinity;
      blocks.forEach(function (block, index) {
        var rect = block.getBoundingClientRect();
        var distance = Math.abs(rect.top - 140);
        if (distance < bestDistance) { bestDistance = distance; best = index; }
      });
      blocks.forEach(function (block, index) { block.classList.toggle("active", index === best); });
      cards.forEach(function (card, index) { card.classList.toggle("active", index === best); });
    }
    window.addEventListener("scroll", syncActive, { passive: true });
    window.addEventListener("resize", syncActive);
    setTimeout(syncActive, 60);

    layout.appendChild(sticky);
    layout.appendChild(column);

    var section = TD.el("section", { class: "mech" }, [
      TD.el("p", { class: "eyebrow", text: "机制 · 双模怎么协同" }),
      TD.el("h2", { class: "section-title", text: "一次决策，经过两个模型" }),
      TD.el("p", { class: "section-lede", html:
        "下面是真实跑批里的一条链路（" + (taskLabel || "") + "）：慢模型写规划，快模型排候选，" +
        "动作执行后由核验判定要不要重规划。往下滚动，每一步展开。" }),
      layout
    ]);
    if (TD.sections && TD.sections.swimlane) {
      TD.sections.swimlane(section, episode, taskLabel);
    }
    return section;
  }

  /* 从真实 episode 的 timeline 里抽出五个环节 */
  function buildMechanismSteps(episode) {
    var timeline = (episode && episode.timeline) || [];
    var planner = null;
    var ranked = null;
    var executed = null;
    var verified = null;
    var replanned = null;
    timeline.forEach(function (entry) {
      // timeline 里的 kind 是「这一步执行了什么」（gui/cli），不是事件类型；
      // 规划原文要看 slow.text（该步窗口里慢模型吐出来的内容）
      if (!planner && (entry.slow || {}).text) planner = entry;
      if (!ranked && entry.fast && entry.fast.n_candidates) ranked = entry;
      if (!executed && entry.action && entry.kind === "gui") executed = entry;
      if (!verified && entry.outcome) verified = entry;
      if (!replanned && entry.replan) replanned = entry;
    });
    var steps = [];
    steps.push({
      title: "慢模型写规划",
      role: "slow_model",
      desc: "慢模型看着当前屏幕与任务状态，输出这一步的目标、预期结果与候选动作提案。",
      body: planner
        ? ((planner.slow.text || "").slice(0, 900) || "（无原文）")
        : "（这一题没有记录到规划原文）"
    });
    steps.push({
      title: "快模型排候选",
      role: "fast_model",
      desc: "候选空间交给小脑排序：先选 operation，再选 target；分数是 softmax 的相对强度，不是校准概率。",
      body: ranked
        ? ("候选 " + ranked.fast.n_candidates + " 个 → 赢家 " + (ranked.fast.winner || "?") +
           "\noperation margin " + ranked.fast.operation_margin +
           " · target margin " + ranked.fast.target_margin +
           "\n排序耗时 " + ranked.fast.latency_ms + " ms" +
           (ranked.fast.used_image ? "（用了截图）" : "（只用结构）"))
        : "（没有排序事件）"
    });
    steps.push({
      title: "执行动作",
      role: "action",
      desc: "赢家被编译成可执行动作送进 VM；动作有没有真的生效，由下一步的核验说话。",
      body: executed
        ? (JSON.stringify(executed.action || {}, null, 2).slice(0, 700) +
           "\n本步花费 $" + (executed.cost_usd || 0).toFixed(5) +
           " · 用时 " + ((executed.elapsed_ms || 0) / 1000).toFixed(1) + "s")
        : "（没有动作事件）"
    });
    steps.push({
      title: "核验结果",
      role: "verify",
      desc: "核验给出 achieved / not_achieved 与逐条要求的达成情况；不达成就回到规划。",
      body: verified
        ? ("outcome = " + verified.outcome +
           "\n要求核验 " + (((episode || {}).requirements) || []).length + " 条" +
           ((episode || {}).requirements || []).slice(0, 4).map(function (req) {
             return "\n  " + req.id + " → " + req.status;
           }).join(""))
        : "（没有核验事件）"
    });
    steps.push({
      title: "必要时重规划",
      role: "replan",
      desc: "stage 模式下重规划是原生事件：带着失败原因换一个新目标继续，而不是原地重试。",
      body: replanned
        ? ("reason = " + replanned.replan +
           "\n新的 stage_goal：\n" + String((replanned.slow || {}).text || "").slice(0, 500))
        : "（这一题没有触发重规划）"
    });
    return steps;
  }

  /* -------------------------------------------------------------- 页面 */
  TD.views.home = function (container) {
    var overview = TD.state.overview;
    var compare = TD.state.compare;
    container.appendChild(intro());
    if (!overview) {
      container.appendChild(TD.el("div", { class: "callout bad", text: "没有内联的总览数据——请用构建脚本生成站点。" }));
      return;
    }
    var placeholder = TD.el("div", { class: "mech" }, [
      TD.el("p", { class: "eyebrow", text: "机制 · 双模怎么协同" }),
      TD.el("h2", { class: "section-title", text: "一次决策，经过两个模型" }),
      TD.el("p", { class: "section-lede", text: "载入真实链路…" })
    ]);
    container.appendChild(placeholder);

    var row = (compare.rows || []).filter(function (item) { return item.group && item.ours > 0; })[0];
    function loadMechanism() {
      function finish() {
        // 结果段无论如何都要渲染——机制段载入失败也不能让首页少一半
        if (TD.sections && TD.sections.results) TD.sections.results(container);
      }
      if (!row) {
        TD.clear(placeholder);
        placeholder.appendChild(TD.el("p", { class: "section-lede", text: "没有可展示的机制样例。" }));
        finish();
        return;
      }
      TD.loadEpisode(row.run_id || "", row.task, function (episode) {
        if (!episode) {
          TD.clear(placeholder);
          placeholder.appendChild(TD.el("p", { class: "section-lede", text: "载入机制样例失败。" }));
          finish();
          return;
        }
        placeholder.replaceWith(mechanism(episode, "Task " + row.task));
        finish();
      });
    }
    loadMechanism();
  };
})();
