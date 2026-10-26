# Tandem demo 重建计划（stage+memory 批次 × 官方 harness 对照）

> 分支：`feature/demo-rebuild`（base `2dec957`）。本分支是**纯 demo 分支**，不并回 main。
> 唯一输入：`tandem_osworld21_stage_memory_c10_20261025_0450/rjob_logs`；不使用 `osw21-500-jevfull` / kev 臂。

## Summary

把 `demo/` 从「多页静态站 + 表格/散点」重建成**单页工作台**（左任务轨 / 中双轨同步轨迹播放器 / 右机制·评估·成本面板），
数据源**只用** `tandem_osworld21_stage_memory_c10_20261025_0450/rjob_logs`（85 题有结果的 stage+memory 批次），
对比对象是**官方 leaderboard 的 harness 型条目**（`Sai w/ Claude Opus 5` 等），并用其 **HF 公开参考 run 的逐题轨迹**做同题对照。

**关键前提（已核实）**：我们的 stage+memory 批次用 `source: "official_benchmark_evaluator"`（**原生官方评测器**），
官方 Sai 参考 run 同样用官方 grader，且双方都是 **OSWorld v2.1**、同题号 →
**逐题对比同口径合法**（不再有 06.24 跨 release 的老问题）。Sai 的 per-task best 均值 **0.7938**
= 官方榜 `Sai w/ Claude Opus 5` 的 partial **79.38**（口径锚点自证）。

**三件已经成立的事实（demo 的叙事地基）**：

| 维度 | 我们（stage+memory，v2.1，原生评测器） | Sai w/ Claude Opus 5（官方 harness，v2.1/500 步） | 关系 |
|---|---|---|---|
| Partial（共同已出分 69 题） | **0.2993** | **0.8030**（per-task best） | 37.3% |
| Binary | **4/85**（001/013/027/061） | 32/69（同 69 题内 per-task best=1.0） | — |
| 逐题打平 | 8 题（001/013/023/024/026/027/035/061） | 同 | 其中 4 题同为满分 |
| 逐题领先 | **0 题** | — | 诚实披露要点 |
| 成本/题 | **$0.756**（278.3M token / 85 题 / 16,050 次调用） | **$14.34**（官方发布，estUSD 1548.72 ÷ 108） | **1/19** |

**范围**：只动 `demo/`（读取层 + 站点 + 测试），**不改 harness、不 bump 协议、不改配置纪律、不重跑评测**。
**关键设计决策**：① 数字同源（复用 `tools/batch_summary.py` 已验证的聚合语义，空转口径与团队一致）；
② 读取层**全流式**（`llm_calls.jsonl` 单题 64MB、批次 39GB，绝不整文件载入）；
③ **MVP 优先**：先交付总览 + 逐题对照 + 精选题轨迹，站点体积 ≤300MB；
④ 底座差异与基础设施失败**必须显式标注**（我们 M3.1-Flash vs Sai Claude Opus 5；16 题未出分中 5 题 Sai 拿满分）。

---

## 1. 目标 / 非目标 / 约束

### 1.1 目标（MVP 优先，按此顺序交付）

| # | 目标 | 验收形态 |
|---|---|---|
| G1 | 单页工作台取代 index/compare/54 个任务页 | `demo/site/index.html` + hash 路由，四视图 |
| G2 | 总览数字可复现、与 `tools/batch_summary.py` 同源 | 一致性测试（同 runs-root，两处输出相同） |
| G3 | 官方 harness 对照（同 release 同评测器逐题） | 12 题子集的逐题 Δ + 官方榜位置 + 轨迹对照 |
| G4 | 双主题、零外部请求、离线可开 | `grep` 断言无外链；双主题截图 |
| G5 | 机制可视化四块全要 | 双轨动画 / 候选漏斗 / replan 闭环 / 成本流水 |
| G6 | 诚实披露红线逐条可核 | 导出器每条红线一个断言 |

### 1.2 非目标（明确不做）

- 不改 `src/tandem/**`、不 bump `protocol_version`、不碰 `infra/config.json` 结构。
- **不使用** `osw21-500-jevfull` / `kev` 臂的结果（用户明确排除）；jev-vs-kev 双臂对照**从本计划移除**。
- 不下载 Sai 全部 2620 个文件；只 vendor 对比子集的 12 题。
- 不引入 npm 构建链（node 仍 v16.14）→ 核心 vanilla，炫酷模块走**可选** CDN，主链路离线可用。
- 不做公网部署（内网共享目录，发布前路径脱敏）。
- 不生成任何我们的预测分/目标分；虚线只画**官方已发布参照值**。
- 不在本分支上重跑评测（重跑由 `scripts/run_osw21.sh` 另行发起）。

### 1.3 实施阶段的硬约束

- **分支**：以 `2dec957` 为 base 切 `feature/demo-rebuild`；**回摘** `ca78369`+`7b3b5a7`（纯新增到 `tools/` 与 `tests/`，
  无冲突）——因为 `2dec957` 相对 HEAD 缺 `tools/` 879 行，而 `tools/batch_summary.py` 正是团队已认可的聚合实现
  （空转口径 10-25 修正过），直接复用可避免口径分叉。
- **一个 PR = 一个组件改动 + 单测 + smoke 链接**；`ruff check src tests && pytest` 必绿；`tandem check` 必绿。
- **单模块 ≤300 行**（`demo/reader/*` 逐模块受此约束）。
- **运行时依赖白名单只有 Pillow** → demo 侧只用标准库（Pillow 可用于帧缩放）。
- **demo 层纪律**：不 import `tandem` / `tandem_eval`、不调模型、不碰 VM；唯一输入是结果目录契约。
- 本次（计划阶段）除本计划文件外不写任何文件、不改 Git 状态。

---

## 2. 当前实现状态（已核实）

### 2.1 Git

- HEAD = `cb02c65`；`2dec957` 是其祖先；`2dec957..HEAD` 15 个提交、44 文件、+5215/−222。
- 协议**未变**（`PROTOCOL_VERSION = "0.1"`）。
- 工作区有未提交改动（`DEVIATIONS.md`、`docs/compare-kev-vs-jev.md` + 5 个未跟踪文档）——**实施时不要动它们**。
- `2dec957..HEAD` 中 `demo/` 仅改 18 行（`e7090bb`）；`tools/` 新增 879 行（`ca78369`/`7b3b5a7`/`15dc71e`）。

### 2.2 现有 demo 层（15 文件 / 2485 行）

| 文件 | 行 | 职责 | 处置 |
|---|---|---|---|
| `demo/adapter.py` | 279 | 结果目录 → 逐步视图 | **拆**为 `demo/reader/` |
| `demo/build_site.py` | 139 | 扫描 run → index/compare/task 页 + 帧 + evidence | **重写** |
| `demo/pages.py` | 282 | index/compare HTML | **重写**（单页） |
| `demo/render.py` | 212 | 任务页 + evidence doc | **重写**（新 view model） |
| `demo/timeline.py` | 253 | 泳道时间轴 | 复用算法 |
| `demo/metrics.py` | 106 | 指标计算 | 随聚合归位 |
| `demo/frames.py` | 65 | 帧缩放 | **复用** |
| `demo/player/*.js` | 6 个 / 1061 | player 内核 | **全砍重做** |
| `tests/demo/` | 3 文件 / 16 测试 | adapter/site/timeline | 随新层重写 |

现产物 `demo/site` **3.3GB**（54 个任务目录）→ 新版目标 **≤300MB**（§4.3）。

### 2.3 结果目录契约（现行，recorder 未变）

**每题**：`task.json`、`traj.jsonl`、`events.jsonl`、`llm_calls.jsonl`、`screenshots/step_NN.png`、
`a11y_digests.jsonl`(+`a11y/step_NN.xml`)、`deliverables/`、`artifacts.json`、`evaluation.json`、
`result.txt`、`episode.json`、`timing.json`。**每 run**：`summary.json`、`heartbeat.json`、
`code_version.json`、`episodes/manifest.resolved.json`。

`episode.json` = `{task_id, harness, stop_reason, steps, status, score, exception_type}`（异常题另有 `error`/`error_traceback`）。
`summary.json` = `{run_id, benchmark, harness{name,mode,models}, total, scored, failed_unscored, average_score, tasks[]}`。

**`events.jsonl` 的 route 取值**（viewer 的权威输入契约）：`planner` / `cli` / `gui` / `cli_verified` /
`gui_verified` / `terminal` / `done_probe` / `stage_local` / `stage_progress` / `stage_replan` / `{"kind":"action"}`。
- `gui` 载荷：`plan`、`candidates[]`、`ranking`（两阶段 softmax + margin + `latency_ms`）、`winner`、`action`、`blocked_action`。
- `gui_verified` 载荷：`execution`、`verification{outcome, evidence, state_changed, requirement_checks[]}`、`control_state_check`。
- `stage_replan` 载荷：`{reason, stage_goal, milestone, step}` —— **本批次为 stage 模式，原生就有**。

### 2.4 本次数据源（唯一）—— stage+memory 批次

路径 `/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/tandem_osworld21_stage_memory_c10_20261025_0450/rjob_logs`
（39GB 整目录；`rjob_logs` 内 105 个 run 目录）。

- 口径：`execution_mode=stage`、`stage_max_actions=24`、`max_steps=500`、`max_wall=14400s`(4h)、
  慢模型 `MiniMax-M3.1-Flash`（`reasoning_effort=max`、`max_tokens=32768`、`slow_direct_api=true`）、
  快模型 `jev`（`qwen-jev-choice`）、**原生官方评测器**（`evaluation.json.source = official_benchmark_evaluator`）。
- 代码树：`experiment.json.source = /home/xuyuanxun/Tandem-osworld21-stage-run-20261024`（`git_describe=unknown`），
  含仓库没有的 `evidence.py` / `model_transport.py` / `visual_grounding.py` → **演示时必须标注**"另一代码树的实验批次"。
- 完成度：105 个 run 目录中 **85 个有 summary**；20 个被控制器/用户停掉（024–035 的 r1 已被 r2 取代；
  083/084/087/088/090–095 无 r2）；**23 题从未覆盖**（083–108 段为主）。
- 逐题结果（69 已出分 / 16 未出分 / 85 总）：

| 分档 | 题数 | 例 |
|---|---|---|
| 满分 1.0 | 4 | 001, 013, 027, 061 |
| 部分分 >0 | 24 | 004=0.6556, 023=0.93, 089=0.79, 076=0.85, 054=0.7997, 007=0.4667, 031=0.5714 … |
| 零分 | 41 | 002/003/005/008/010/014/018/020/024/028/030/032/034/036/038/039/042/046/047/048/050/058/059/060/062/064/065/067/069/070… |
| 未出分（异常） | 16 | 025(判分)、033(RuntimeError)、043/045/086(ValueError)、052/070/071/072/073/080/081/082(APIUnavailable)、055(TypeError)、056(EvalInfra)、075(BadRequest) |

- 停止原因：`done` 31 / `wall_time_limit` 37 / `exception` 16 / `no_action_limit` 1 → **墙钟（4h）是主约束**
  （步数中位 98、最大 491，远未到 500 上限）。
- 慢模型用量：16,050 次调用；prompt 224,712,408 + completion 53,615,400 = **278,327,808 token**；
  其中 cached 11,872,786、**reasoning 46,831,385**（占 completion 87%）；每题 total 中位 2.82M / 均值 3.27M。
- 成本（M3.1-Flash 挂牌价 2026-10-23：in $0.15 / out $0.60 / cached $0.015 per 1M）：
  **合计 $64.27 → $0.756/题**（Sai $14.34/题 → 约 1/19）。

### 2.5 官方对照数据（两个来源）

**(a) 官方 leaderboard**（`https://osworld-v2.xlang.ai/static/data/leaderboard/official-results.json`，55 行，
`updatedAt 2026-10-15`，`datasetSize 108`，`defaultStepBudget 500`）中的 **harness 型行**（`modelType=agent`，全表仅 3 行）：

| 条目 | release | 题集 | 步数 | Binary | Partial | 每题成本 |
|---|---|---|---|---|---|---|
| **Sai w/ Claude Opus 5** | v2.1 | full 108 | 500 | **41.67** | **79.38** | **$14.34**（estUSD 1548.72） |
| Darwinx w/ Claude Opus 4.8 | v2.1 | full 108 | 450 | 44.44 | 75.97 | 未发布 |
| Darwinx w/ Claude Opus 4.8 | v2026.08.08 | full 108 | 450 | 37.65 | 66.62 | 未发布 |

其余 52 行是 `modelType=e2e`（官方 runner 直跑，如 Opus 5 max 44.33/77.67）→ **只作背景，不作主对比**。

**(b) Sai 逐题参考 run**（HF `simular-ai/sai-osworld-v21-reference-runs`，2620 文件，18 个参考 run）：

- `index.jsonl`：134 行干净运行（task, run, build, score, infra, text_dir, media_tar, source_path）
- `scorecard/ref-scorecard.json`：per-task `runs/mean/first/best` + 24.04 base + `tag`/`evidence`
- `runs/<run>/<task>/`：`instruction.txt`、`traj.jsonl`（step_num/action/reward/screenshot_file/osworld_action/sai_trajectory，~108KB）、
  `full_trajectory/{messages.json(956KB), events.jsonl(470KB), system_prompt.txt, manifest.json}`、
  `api_logs/`、`eval.log`、`result.txt`、`task_record.json`(3.4KB)
- `media/<run>/<task>.tar`：逐步 PNG + `recording.mp4` + `initial_state.png`
- 口径锚点：per-task **best** 均值 = **0.7938** = 官方榜 partial **79.38** ✅（证明官方榜那行 = 每题最佳干净运行）

### 2.6 逐题对照（我们 vs Sai best，同 69 题）

- 我们 0.2993 vs Sai 0.8030 → **37.3%**；**我们领先 0 题**。
- **完全打平 8 题**：001(1.0=1.0)、013(1.0=1.0)、027(1.0 vs 1.0)、061(1.0=1.0)、
  023(0.93=0.93)、026(0.5=0.5)、035(0.5=0.5)、024(0=0)。
- 差距最大：002/003/005/018/028/030/032/037/038/046/059/064/065（Sai 1.0，我们 0）。
- **003/028 是"声称 done 却 0 分"**（Sai 1.0）→ 机制视图要能指出「完成判定与评测不一致」。
- **16 题未出分里 5 题 Sai 拿满分**（070/072/073/075/082）→ 我们的基础设施失败直接吃掉了 5 个潜在满分。
- 已有聚合工具验证：`python3 tools/batch_summary.py --runs-root <stage_memory>/rjob_logs --prefix …` **开箱可用**，
  题号/空转率/token/域分类全部正确（仅 episode 目录名是 `004` 而非 `tasks-004`，需在 reader 里归一）。

---

## 3. 目标形态

### 3.1 路由（单页工作台，hash 深链，←/→ 翻步，主题切换常驻）

| 路由 | 内容 |
|---|---|
| `#/` 总览 | 我们的 run 卡（85 题：已出分/未出分/partial/binary/token/成本/墙钟）· 官方 harness 榜定位（虚线=官方发布值）· 85 题矩阵（按分/停止原因/域着色）· 停止原因分布（done 31 / wall 37 / exception 16 / no_action 1）· 成本×分数散点 |
| `#/task/<run>/<task>` 轨迹 | 双轨同步播放器 + 机制面板 + 需求核验 + 成本流水 + 帧序列 |
| `#/compare` 官方对照 | 12 题子集逐题 Δ（我们 vs Sai best/mean）· 官方榜位置（Sai / Darwinx / e2e 背景）· 成本轴（$0.756 vs $14.34）· 底座差异与基础设施失败标注 |
| `#/mechanism` 机制 | 快慢双模协同说明 + 失败模式解剖（空转/墙钟/异常/完成不一致） |

### 3.2 轨迹播放器

- **上轨 · 慢模型**：`planner` 原文流式打字 + 结构化 plan 卡（`stage_goal` / `milestones[]` / `expected_observation`）；
  原文取 `llm_calls.jsonl` 的 `response.choices[0].message.content`（**只搬运，不改写**）。
- **下轨 · 快模型**：候选漏斗（`a11y_digests.node_count` → `len(candidates)` → `winner`）+ 两阶段 softmax 强度条 +
  margin + `latency_ms`；分数恒标 **softmax，非校准概率**。
- **侧轨 · 帧序列**：`screenshots/step_NN.png` 离散帧（缺失帧标原因，不做伪连续）。
- **叠层 · 空转标记**：`gui` 事件 `action == null` 的决策标"空转"（与 `tools/batch_summary.py` 同口径）。

### 3.3 机制面板

`plan → act → verify → replan` 闭环可点击：
- `planner` → 计划节点；`{"kind":"action"}` → 执行节点；`gui_verified/cli_verified` → 核验节点（`outcome` 决定绿/红）。
- **replan**：本批次是 stage 模式 → **直接用原生 `stage_replan` 事件**（`reason` / `stage_goal` / `milestone`），
  不做推断；`stage_local` / `stage_progress` 渲染为里程碑时间线。
- 需求核验：`verification.requirement_checks[]` 的 `id/status/evidence` 逐条流转。

### 3.4 成本面板

三轴同屏：**token 燃烧**（prompt/completion/cached/reasoning 分色，按 role 堆叠）· **美元累计**（价格表估算 + 快照日期）·
**快模型侧轴**（排序调用数 + 排序总时长/题，**不折美元**，标注"本地 GPU，成本未计入美元"）。

### 3.5 官方对照视图（MVP 的核心）

- 逐题表：我们 vs Sai `best` / `mean`（**同 release、同原生评测器、同题号**），Δ 列 + 排名。
- 12 题精选子集（覆盖 4 种模式，见 §4.3）提供 **Sai 侧轨迹对照**（vendored `traj.jsonl` + 关键帧）。
- 官方榜位置：Sai w/ Opus 5（41.67/79.38/$14.34）、Darwinx（44.44/75.97）、e2e 背景行（标注非 harness 型）。
- **三处必须同屏的口径声明**：① 我们用 M3.1-Flash vs Sai 用 Claude Opus 5（底座不同）；
  ② 我们 85 题尝试、Sai 108 题全量（题集不同）；③ 我们 16 题未出分中 5 题 Sai 拿满分（基础设施失败，非能力差距）。

---

## 4. 架构与端到端流程

### 4.1 分层

```
<stage_memory>/rjob_logs/<run_id>/…     （只读，唯一输入）
        │
        ▼  demo/reader/                  ← 纯标准库，逐行流式
   runs.py       发现 run、读 summary.json / code_version.json
   episodes.py   读 episode.json / evaluation.json / timing.json / task.json
   events.py     流式解析 events.jsonl → 步骤（planner/gui/cli/verify/stage_*）
   llm.py        流式解析 llm_calls.jsonl → 只取 usage + 原文（丢 base64）
   traj.py       流式解析 traj.jsonl + a11y_digests.jsonl → 帧索引 / node_count
   viewmodel.py  episode view model（站点唯一数据契约）
        │
        ├─► demo/build_site.py → demo/site/（静态快照）
        ├─► demo/server.py      → 本地实时 API（同一读取层，第二个出口）
        └─► demo/reader/aggregate.py ← 委托自 tools/batch_summary.py（保持口径一致）
```

**硬约束**：
- `llm_calls.jsonl` 单题 64MB、批次 39GB → **必须逐行 `json.loads` 后立即丢弃图片字段**，禁止 `read()`/`readlines()`。
- `events.jsonl` 单题 2.4MB → 可逐题读入。
- view model 单题 **≤300KB**（慢模型原文每题 ≤8 次调用 × ≤4KB，候选只留前 20 个）。
- 聚合语义**不重写**：直接调用 `tools/batch_summary.py` 的 `collect_rows()`（已在新数据源上验证可用），
  demo 只加"题号归一"（`tasks-004` / `004` → `004`）与"Sai 对照列"。

### 4.2 episode view model（站点唯一数据契约）

```jsonc
{
  "task_id": "004", "run_id": "osw21-stagememory-004-20261025-0450",
  "status": "scored", "score": 0.6556, "stop_reason": "done", "steps": 40,
  "wall_seconds": 2944.5, "domain": "libreoffice_impress", "noop_rate": 0.0,
  "evaluator": {"source": "official_benchmark_evaluator", "raw": 0.6556},
  "tokens": {"prompt": 1264219, "completion": 306318, "cached": 0, "reasoning": 268801,
             "calls": 74, "usd_estimate": 0.373, "price_snapshot": "2026-10-23"},
  "fast_model": {"rank_calls": 34, "rank_ms_total": 41230},
  "steps_detail": [ {"step": 0, "kind": "planner", "plan": {...}, "llm_text": "…"},
                    {"step": 1, "kind": "stage_local", "stage_goal": "…"},
                    {"step": 2, "kind": "gui", "candidates": [...], "ranking": {...},
                     "winner": {...}, "action": {...}, "noop": false},
                    {"step": 3, "kind": "gui_verified", "verification": {...}} ],
  "replans": [ {"step": 5, "reason": "execution_failed_or_unverified", "milestone": 0} ],
  "requirements": [ {"id": "font_name", "status": "achieved", "evidence": "…"} ],
  "frames": [ {"step": 0, "src": "frames/<run>/004/step_00.jpg", "sha256": "…"} ],
  "sai": {"best": 0.8, "mean": 0.8, "runs": 1, "traj_ref": "sai/004"},
  "provenance": {"code_version": "unknown(experiment)", "benchmark": "osworld21",
                 "inner_image": "weavebench@sha256:0e6497a9…"}
}
```

### 4.3 MVP 范围与站点体积

**对比子集 = 12 题**（覆盖 4 种模式，全部落在我们已出分的题里，便于逐题对照）：

| 组 | 题 | 我们的分 | Sai best | 看点 |
|---|---|---|---|---|
| 满分打平 | 001, 013, 027, 061 | 1.0 | 1.0 | 我们也能做对 |
| 同分非满分 | 023, 026, 035 | 0.93/0.5/0.5 | 0.93/0.5/0.5 | 逐位相同 |
| 接近但落后 | 004, 054, 089 | 0.6556/0.7997/0.79 | 0.8/1.0/0.85 | 差在哪（轨迹对照） |
| 失败模式 | 003, 034 | 0.0 / 0.0 | 1.0 / 0.875 | 声称 done 却 0 分 / no_action_limit |

- **帧只对这 12 题生成**（`demo/frames.py` 复用）；其余 73 题只出数据不出帧。
- Sai 侧只 vendor 这 12 题的 `traj.jsonl` + `task_record.json` + `result.txt`（每题约 110KB）+ 少量关键帧
  （`media/<run>/<task>.tar` 体积较大 → 每题只取 `initial_state.png` 与末帧，或先只做轨迹文本对照）。
- 站点目标 **≤300MB**（现 3.3GB）；`demo/site/` 与源目录分离，导出只拷站点。

### 4.4 成本模型（我们 vs 官方 harness）

我们的 85 题：278,327,808 token（prompt 224.7M / completion 53.6M / cached 11.9M / reasoning 46.8M），
16,050 次慢模型调用。按 `MiniMax-M3.1-Flash` 挂牌价（**2026-10-23 抓取**，in $0.15 / out $0.60 / cached $0.015 per 1M）：

| 项 | 计算 | 金额 |
|---|---|---|
| 输入（不含 cache） | 212.84M × $0.15/M | $31.93 |
| cache read | 11.87M × $0.015/M | $0.18 |
| 输出（含 46.8M 思考 token） | 53.62M × $0.60/M | $32.17 |
| **合计 / 每题** | | **$64.27 / $0.756** |

对照 `Sai w/ Claude Opus 5` **$14.34/题**（官方发布）→ **1/19**。
**必须标注**：底座不同（我们 M3.1-Flash vs Sai Claude Opus 5）、步数口径不同（我们 500 上限但 37 题撞 4h 墙钟、
Sai 也是 500 步）、官方成本含其自身工具费与缓存定价，我们只计 API token。

### 4.5 两个出口

- **静态快照**：`python3 demo/build_site.py --runs-root <stage_memory>/rjob_logs --out demo/site --benchmark osworld21`
  （对外分发用，内网共享目录）。
- **本地实时**：`demo/server.py`（标准库 `http.server`，零新依赖）：`/api/runs`、`/api/episode/<run>/<task>`、
  `/api/compare`；页面轮询 30s。两条出口**共用 `demo/reader/`**。

### 4.6 官方数据与价格表（vendored）

`demo/data/official/leaderboard.json`（官方榜快照 + `source_url` + `fetched_at`）、
`demo/data/official/sai_tasks.json`（Sai per-task mean/first/best + runs 数，源自 HF `index.jsonl` + `ref-scorecard.json`）、
`demo/data/official/sai_traj/<task>.json`（12 题的 Sai 轨迹摘要）、
`demo/data/prices.json`（模型 → in/out/cache，每条带 `source_url` + `fetched_at`）。
`demo/sync_official.py` 负责刷新（下载 → 校验字段 → 写回 → 更新 `fetched_at`）。**页面显示价格与官方数据的快照日期**。

### 4.7 诚实披露红线（9 条，导出器逐条断言）

1. 只渲染**真实 run** 的数字；`failed_unscored` 显示"未出分"，**不折算 0**（Partial 口径需另注"官方按 0 计"）。
2. 虚线只画**官方已发布参照值**；**不生成我们的预测分/目标分**。
3. 美元成本标注「按 YYYY-MM-DD 挂牌价估算」+ 底座型号（我们 M3.1-Flash vs 官方 M3 / Sai 的 Opus 5）。
4. 快模型 GPU 成本单列第二轴，不藏、不折美元。
5. release / 题集 / 步数预算差异出现在每处对比旁（v2.1 / 我们 85 尝试 vs Sai 108 / 500 步）。
6. 慢模型原文只搬运 `llm_calls.jsonl` 真实内容，不生成"思考字幕"。
7. 排序分数恒标 **softmax，非校准概率**。
8. 帧是离散帧不是录屏；缺失帧标缺失原因。
9. **失败与口径披露**（首屏红字）：① 我们 16 题未出分（8×APIUnavailable、3×ValueError 等），
   其中 5 题 Sai 拿满分 → **基础设施失败不是能力差距**；② 37 题撞 4h 墙钟（步数中位 98/500）→
   **墙钟是主约束**；③ 3 题"声称 done 却 0 分"（003/028 等）→ 完成判定与评测不一致；
   ④ 本批次是**另一代码树的实验**（`git_describe=unknown`），非仓库主干。
10. 集群路径/账号脱敏后进内网共享目录。

---

## 5. PR 序列（MVP 优先）

| PR | 范围 | 关键文件 | 验收 |
|---|---|---|---|
| **PR0** | 切 `feature/demo-rebuild`（base `2dec957`）+ 回摘 `ca78369`/`7b3b5a7` + 计划落库 | 分支 + `docs/DEMO_REDESIGN.md` | `git log` 含两个 tools 提交；ruff/pytest 绿 |
| **PR1** | `demo/reader/` 读取层（runs/episodes/events/llm/traj）+ 题号归一 | 新增 5 模块 | 单测用合成 fixture；**断言不整文件读 llm_calls** |
| **PR2** | 聚合对接：reader 委托 `tools/batch_summary.collect_rows` + Sai 对照列 | `demo/reader/aggregate.py` | **一致性测试**：同 runs-root 两处输出相同；题号归一生效 |
| **PR3** | 官方数据 vendored（榜 / Sai per-task / Sai 12 题轨迹）+ 价格表 + `sync_official.py` | `demo/data/**` | 单测校验字段 + 锚点断言（Sai best 均值 == 0.7938 == 榜上 79.38） |
| **PR4** | 单页骨架：路由 + 三栏 + **双主题 token** | `demo/site/index.html` + `assets/app.css/js` | 主题切换无硬编码颜色残留（grep 断言） |
| **PR5** | 总览视图（run 卡 / 85 题矩阵 / 停止原因分布 / 成本散点 / 官方定位 / 红字声明） | `assets/views/overview.js` | 快照测试（HTML 结构断言） |
| **PR6** | 官方对照视图（12 题逐题 Δ + Sai 轨迹对照 + 三处口径声明） | `assets/views/compare.js` | Δ 与 `demo/reader/aggregate.py` 一致 |
| **PR7** | 双轨播放器（慢模型原文流 + 快模型排序漏斗 + 帧序列） | `assets/player/dual.js` | 12 题可完整回放；离线可开 |
| **PR8** | 机制面板（stage replan 闭环 + 需求核验 + 空转标记 + 失败模式解剖） | `assets/views/mechanism.js` | replan 用原生事件（无推断） |
| **PR9** | 成本视图（token 燃烧 + 美元 + 快模型 GPU 侧轴） | `assets/views/cost.js` | 美元值 == 价格表手算（单测） |
| **PR10** | 导出：内网共享目录 + 路径脱敏 + 9 条红线自检 | `demo/export_share.py` | 脱敏后 `grep -r "/mnt/"` 为空；红线断言全绿 |

**MVP 交付 = PR0–PR6 + PR10**（总览 + 官方对照 + 发布闭环）；PR7–PR9（轨迹/机制/成本）为第二批，
但**总览页的成本与机制摘要先在 PR5/PR6 里以静态形式给出**（不阻塞）。

**闸门**：G-A 数字可信（PR2 一致性 + PR3 锚点）→ G-B 口径诚实（PR5/PR6 的三处声明）→ G-C 可发布（PR10 红线全绿）。

---

## 6. 状态、并发、失败与恢复语义

- **读取层只读**：任何 `demo/` 代码不得写入源目录；写只发生在 `demo/site/` 与导出目录。
- **增量更新**：`build_site.py --only-changed` 按 `summary.json` 的 mtime+大小判定需重建的 run；
  产物按 `run_id/task_id` 寻址，天然可增量。
- **实时出口并发**：`ThreadingHTTPServer` + 每题 view model 的 LRU 缓存（≤32 题 / ≤256MB）；
  缓存 key = `(run_id, task_id, episode.json mtime)`。
- **大文件保护**：`llm_calls.jsonl` 设单行长度上限（8MB）与单题调用数上限（2000），超限记 `truncated: true` 并在 UI 标注。
- **失败态也要能看**：0 步 / 未出分的题渲染失败态页（原因 + 异常类型 + 首次失败栈尾），不空白页。
- **多 run 去重**：同一题多个 run（r1/r2）→ 取「已出分优先，其次批次时间戳晚」（`tools/batch_summary._row_rank`）。
- **回滚**：每个 PR 独立可回滚；`demo/site/` 是产物，可删了重建。

---

## 7. 测试与验收

### 7.1 自动化

| 层次 | 内容 |
|---|---|
| 单元（`tests/demo/`） | reader 解析正确性；view model 字段契约；题号归一；价格换算；脱敏 |
| 契约 | view model 用到的每个结果目录路径都必须在 `docs/RESULT_DIR_CONTRACT.md` 列出（新增断言） |
| 一致性 | 同 runs-root：`demo` 聚合 == `tools/batch_summary.py` 输出（逐位）；Sai per-task best 均值 == 0.7938（榜上 79.38） |
| 站点 | `build_site.py` 对小 fixture 端到端产出 index.html + 对照视图；HTML 结构快照断言 |
| 纪律 | `ruff check src tests` + `pytest`（313 → 新增后全绿）+ `tandem check`；`grep` 断言 demo 无外链、无 `import tandem` |

### 7.2 人工 smoke（每个 PR 附链接）

- 总览页截图（双主题各一张）+ 关键数字截图；
- 对照页 12 题 Δ 截图 + Sai 轨迹对照截图；
- 与 `tools/batch_summary.py` 输出并排截图（人工确认一致）。

### 7.3 Definition of Done

- [ ] `ruff check src tests` 绿；`pytest` 全绿；`tandem check` 绿
- [ ] demo 层无 `import tandem` / `import tandem_eval`
- [ ] 站点离线可开（无外链请求），深浅主题均可读
- [ ] 总览与对照数字与 `tools/batch_summary.py` / Sai 官方数据逐位一致
- [ ] 9 条红线在导出物上全部成立（自动断言 + 人工复核）
- [ ] `demo/site` ≤ 300MB
- [ ] 12 题可完整回放（双轨 + 帧 + 原生 replan 闭环 + Sai 轨迹对照）

---

## 8. 未决决策与风险

### 8.1 需要维护者拍板（本计划已给默认建议）

| # | 决策 | 默认 | 备选 |
|---|---|---|---|
| **R1** | `2dec957` 缺 `tools/` 879 行 | **回摘** `ca78369`+`7b3b5a7`（纯新增、无冲突），复用团队已认可的聚合口径 | 自写聚合（口径分叉风险）；或改以 HEAD 为 base |
| **R2** | 分支生命周期 | 纯 demo 分支，**不并回 main**；发布物走内网共享目录 | 合回 main（需 rebase，会带入 harness 侧改动） |
| **R3** | Sai 侧媒体素材 | 先只 vendor **文本轨迹**（traj.jsonl + task_record.json，每题 ~110KB）；关键帧按需再取 | 全量下载 media tar（数 GB，阻塞 MVP） |
| **R4** | 对比子集 | §4.3 的 **12 题** | 扩到全部 85 题（工作量大、收益递减） |
| **R5** | e2e 官方行 | 只作背景灰行，标注"非 harness 型" | 不展示（丢失"我们 vs 同族 e2e"参照） |

### 8.2 风险

1. **数字分叉（最高）**：站点与 `tools/batch_summary.py` 若两套实现，迟早对不上 → PR2 的"单一实现 + 一致性测试"是硬闸门。
2. **底座差异被误读**：我们 M3.1-Flash $0.756/题 vs Sai Claude Opus 5 $14.34/题，1/19 的成本差**主要来自底座**，
   不是 harness 更省 → 页面必须并排写型号。
3. **分数差距的真实构成**：partial 37.3% 的差距里，**16 题未出分（其中 5 题 Sai 满分）**占相当比重；
   若只看"能力差距"会高估问题严重性 → 未出分必须单列。
4. **我们从未领先**（0 题 > Sai）→ demo 不做"我们更强"的暗示；可讲的是"1/19 成本 + 同题打平 + 失败模式可解释"。
5. **"声称 done 却 0 分"**（003/028 等）触及完成判定可信度 → 机制视图必须能指出这类不一致，不要藏。
6. **墙钟是主约束**（37 题撞 4h，步数中位 98/500）→ 任何"提高步数预算"的建议都无效；优化点是墙钟内的效率与空转率。
7. **推理 token 占 completion 87%**（46.8M/53.6M，`reasoning_effort=max`）→ 成本优化空间主要在思考预算与 prompt（a11y 全量入 prompt）。
8. **源数据在仓库外**（39GB 共享目录）→ 不保证常驻（此前 OSW2 实验已被清进回收站）→ 站点必须自包含（view model + 帧），
   导出物不能依赖源目录。
9. **实验批次代码树不同**（`git_describe=unknown`，含仓库没有的模块）→ 站点 provenance 字段必须如实标注。
