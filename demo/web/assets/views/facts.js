/* 机制段的「事实提取」：从一条真实 episode 里抽出各环节的真实数据。
 *
 * 拆出来是因为 home.js 会超 300 行（纪律 3），而且「抽事实」和「画页面」
 * 是两件事：这里只读 episode，不碰 DOM。
 */
(function () {
  "use strict";
  var TD = window.TD;

  function buildFacts(episode) {
    var timeline = (episode && episode.timeline) || [];
    var frames = (episode && episode.frames) || [];
    var steps = (episode && episode.steps_detail) || [];
    var facts = {
      planner: null, ranked: null, executed: null, verified: null, replanned: null,
      bars: [], opBars: [], nodes: 0, gui: null, winner: null, candidates: 0,
      plan: null, milestones: [], frames: frames,
      subtasks: [], plans: 0, replan: null
    };

    /* 规划：整轮**累积**的子任务链。
       只看第一次规划会以为整个任务就两三个子任务——实际上慢模型会重规划很多次，
       每次都拆出新的子任务，这里按出现顺序去重累积。 */
    var seen = {};
    steps.forEach(function (step) {
      if (step.kind !== "planner" || !step.plan) return;
      facts.plans += 1;
      if (!facts.plan) facts.plan = step.plan;
      (step.plan.milestones || []).forEach(function (item) {
        var goal = String((item && item.current_goal) || "").trim();
        if (!goal || seen[goal]) return;
        seen[goal] = true;
        facts.subtasks.push(goal);
      });
    });
    facts.milestones = facts.subtasks;

    timeline.forEach(function (entry) {
      // timeline 的 kind 是「这一步执行了什么」（gui/cli），不是事件类型；
      // 规划原文要看 slow.text（该步窗口里慢模型吐出来的内容）
      if (!facts.planner && (entry.slow || {}).text) facts.planner = entry;
      if (!facts.ranked && entry.fast && entry.fast.n_candidates) facts.ranked = entry;
      if (!facts.executed && entry.action && entry.kind === "gui") facts.executed = entry;
      if (!facts.verified && entry.outcome) facts.verified = entry;
      if (!facts.replanned && entry.replan) facts.replanned = entry;
    });

    /* 排序：画**动作级**候选（action_ranked × 候选表 join）。
       operation_ranked 只有 3 条（click / visual_fallback / return_to_planner），
       那是「操作类型」的分布；真正的候选空间是那 8~9 个具体动作。 */
    steps.forEach(function (step) {
      if (facts.gui || step.kind !== "gui" || !step.ranking) return;
      var ranked = step.ranking.action_ranked || [];
      if (!ranked.length) return;
      var byId = {};
      (step.candidates || []).forEach(function (item) { byId[item.id] = item; });
      facts.gui = step;
      facts.winner = step.winner || null;
      facts.candidates = step.n_candidates || ranked.length;
      facts.bars = ranked.map(function (item) {
        var meta = byId[item.id] || {};
        return {
          id: item.id, operation: item.operation, score: item.score,
          description: meta.description || ""
        };
      });
      facts.opBars = (step.ranking.operation_ranked || []).map(function (item) {
        return { operation: item.operation, score: item.score };
      });
    });

    /* 重规划：stage_replan 事件 + 它之后慢模型写下的新计划 */
    var replanIndex = -1;
    steps.forEach(function (step, index) {
      if (replanIndex < 0 && step.kind === "stage_replan") replanIndex = index;
    });
    if (replanIndex >= 0) {
      var event = steps[replanIndex];
      var next = null;
      for (var j = replanIndex + 1; j < steps.length; j += 1) {
        if (steps[j].kind === "planner" && steps[j].plan) { next = steps[j].plan; break; }
      }
      facts.replan = {
        reason: event.reason || "",
        stage_goal: event.stage_goal || "",
        goal: next ? next.stage_goal || "" : "",
        milestones: next ? (next.milestones || []).map(function (item) {
          return String((item && item.current_goal) || "").trim();
        }).filter(Boolean) : []
      };
    }

    frames.forEach(function (frame) {
      if ((frame.node_count || 0) > facts.nodes) facts.nodes = frame.node_count;
    });

    /* 流程图节点上显示的真实数字（不是文案，是这条 case 的实际值） */
    facts.concept = {
      plan: facts.subtasks.length
        ? ("拆出 " + facts.subtasks.length + " 个子任务 · 规划 " + facts.plans + " 次")
        : "拆解子任务 + 定目标",
      task: facts.candidates
        ? (facts.candidates + " 个候选进排序")
        : "候选空间：a11y 解析 + 慢模型",
      rank: facts.ranked ? (facts.ranked.fast.latency_ms + " ms") : "选出一个动作",
      verify: facts.verified ? facts.verified.outcome : "子任务是否达成",
      fix: facts.replan ? (facts.replan.reason || "换个目标再来") : "换个目标再来",
      next: facts.subtasks.length
        ? ("还剩 " + Math.max(facts.subtasks.length - 1, 0) + " 个子任务")
        : "循环直到任务完成"
    };
    return facts;
  }


  TD.facts = { build: buildFacts };
})();
