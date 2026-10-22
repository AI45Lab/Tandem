# demo/ — OSWorld2 轨迹回放与对比站点

把 `rjob_logs/<run_id>/` 的结果目录变成一个**静态站点**：逐步回放每道 OSW2
任务的桌面轨迹与模型操作，并横向对比多个 run 的**成本 / 耗时 / 准确率**。

demo 层与 harness 完全解耦：**不 import `tandem` / `tandem_eval`，不调用模型，
不碰 VM**。唯一输入是 `docs/RESULT_DIR_CONTRACT.md` 描述的结果目录契约。

## 用法

```bash
# 构建全部 OSW2 run（默认输出 demo/site）
python demo/build_site.py --runs-root rjob_logs --out demo/site --benchmark osworld2

# 只构建指定 run
python demo/build_site.py --runs-root rjob_logs --out demo/site --run rjob_logs/osw2-20-s1

# 本地预览（file:// 也能开，但证据抽屉需要 http 才能拉取完整 JSON）
python -m http.server 8899 --directory demo/site
```

产物：

```
site/
├── index.html                      # 总览：run 卡片 + 成本×准确率散点 + 缩略图网格 + 可排序对比表
├── compare.html                    # 两个 run 的并排对比（选择器切换 + 差值）
├── task/<run_id>/<task_id>.html    # 单题轨迹回放
└── assets/
    ├── player.css / player-v2.css  # 样式
    ├── player.js                   # 内核：共享工具 + 索引页排序
    ├── player-compare.js           # 对比页模块
    ├── player-detail.js            # 任务页详情渲染（规划/排序/动作/验证）
    ├── player-fail.js              # 0 步任务的失败态（没有轨迹时讲清原因）
    ├── player-task.js              # 任务页：泳道时间轴 / 需求章节 / 步骤回放
    ├── frames/<run_id>/<task_id>/  # 缩放后的帧（step_NN.jpg）+ thumb.jpg
    └── evidence/<run_id>/<task>.json # 完整原始证据（事件全文 + LLM 请求/响应）
```

## 页面能看什么

### 总览页

- 每个 run 一张卡（已出分 / 未出分 / 均分 / 总耗时 / LLM 调用数 / 输入输出与思考
  token / JEV 排序次数 / 失败分类）；
- **成本 × 准确率散点**：横轴 token 用量（平方根刻度），纵轴官方评分，气泡半径 ∝
  耗时；绿=有分、红=零分，未出分的题单独排在底部一排（不计入均分）；
- **任务缩略图网格**（无帧的题显示"未进入决策步"占位）；
- 逐题对比表——点表头按分数、耗时、token 排序。

### 对比页（`compare.html`）

任选两个 run 并排：逐题的分数 / token / 耗时 / 步数 / LLM 调用 / JEV 排序，以及
Δ差值（绿=更优、红=更差）。当前数据里 jev 与 kev 在任务 001 上可直接对照。

### 任务页

- **读数带**：官方评分、token 用量、真实用时、步数与 JEV 排序次数；
- 左侧执行前 / 执行后双帧对照；
- **需求清单 · 逐条核验**：从结构化字段（`verification.requirement_checks` +
  `task_requirements` 抽取结果）得到每条需求的终态结论与"在第几步被核验"，
  点条目直接跳到那一步；
- 右侧是这一步的完整模型操作链：
  1. **规划**：当前目标、预期观察、路由、任务状态、动作提案；
  2. **候选与排序**：JEV 两阶段（操作级 → 目标级）softmax 分数与相对强度条、
     margin、排序延迟；
  3. **编译后动作**：kind / action_type / 参数 / 目标 id / 描述；CLI 路由附命令全文；
  4. **执行回执与独立验证**：verifier 裁决、状态变化、证据、逐条需求核验、
     stdout/stderr；
  5. **终态双确认**：planner 声称完成后的终态核验全文；
- **真实时钟轨迹**：四条泳道（KIMI 规划 / 排序服务 / 动作与观察 / KIMI 验证），
  横轴是**实测**时间——由 `llm_calls[].time`、`traj[].wall_time`、
  `ranking.latency_ms` 还原，不做比例重建、不估算未记录的时间；点泳道条跳到该步；
- 底部步骤时间轴（每步一个 chip，颜色=验证结论，标注 gui/cli 路由），
  支持键盘 ←/→ 翻步、`#step=N` 深链；
- 右上角「运行证据」抽屉按需拉取完整原始 JSON。

### 0 步任务（失败态）

本批次有 9 题在 import 期即死——0 步 / 0 次模型调用 / 0 帧。这类页面不画轨迹，
而是直接讲清楚「为什么没有轨迹」：

- 失败态卡片：终止原因（`exception_type` / `stop_reason`）、耗时、
  终止前的模型调用次数与 role 分布；
- **调用数也是 0 ⇒ 失败发生在模型被调用之前**（环境 / 依赖 / 配置），
  与「模型跑了但没做对」是两回事；
- 右侧「执行摘要」列出状态、评分口径、决策步、JEV 次数、调用分布、用时。

例：任务 017 的模型调用是 `task_requirements × 1 + plan_step × 3`（规划连续三次
非法 JSON 后抛 ValueError）；任务 020 是 0 次调用（环境问题）。

## 数据契约（只读这些）

| 文件 | 用途 |
|------|------|
| `summary.json` | run 级汇总（已出分 / 未出分 / 均分） |
| `code_version.json` | harness 版本、协议版本、git describe、镜像 digest、run_spec（selector 后端） |
| `episodes/manifest.resolved.json` | task_id → episode_dir 映射 |
| `episodes/<dir>/task.json` | 任务指令、snapshot |
| `episodes/<dir>/episode.json` | status / score / stop_reason / exception_type |
| `episodes/<dir>/timing.json` | wall_seconds |
| `episodes/<dir>/evaluation.json` | 官方评分 |
| `episodes/<dir>/events.jsonl` | planner / gui / cli / verified / terminal 事件（含 ranking 全量输入输出） |
| `episodes/<dir>/traj.jsonl` | 每步观察、回执与 wall_time |
| `episodes/<dir>/llm_calls.jsonl` | LLM 请求/响应、usage 与响应落盘时刻 |
| `episodes/<dir>/screenshots/step_NN.png` | 逐步截图（帧来源） |

### 步号语义（契约 §步号语义，已写进 docs/RESULT_DIR_CONTRACT.md）

- 截图索引 0 基，且是**动作执行后**的屏幕；`traj.step_idx = 截图索引 + 1`；
- 动作步 s 的「执行后」帧 = `step_{s:02d}.png`，「执行前」帧 = `step_{s-1:02d}.png`；
  第 0 步没有执行前帧（初始观察只在 `obs_stage`，结束即清）；
- 验证事件落在动作的**下一步骤**桶，故动作步 s 的裁决取自 s+1 桶。

### 时间轴是怎么还原的

| 泳道 | 区间 | 数据来源 |
|------|------|----------|
| `plan` | 上一步结束 → Kimi 规划调用结束 | `llm_calls[].time`（响应落盘时刻） |
| `rank` | 规划结束 → +排序延迟 | `ranking.latency_ms`（服务端实测） |
| `act` | 排序结束 → 本步观察采集时刻 | `traj[].wall_time` |
| `verify` | 观察时刻 → 验证调用结束 | `llm_calls[].time` |

LLM 调用按事件顺序归属步骤（实测序列恒为 `plan* → 观察 → verify → plan* → …`）。
**没有 LLM 调用痕迹的步骤不画段**——没有数据就不画条。

## 诚实披露纪律

1. 只搬运**模型公开输出**，不生成任何虚构的"思考字幕"；
2. `failed_unscored` 一律显示「未出分」，**不折算 0 分、不计入均分**；
3. JEV `/rank` 分数始终标注 **softmax，非校准概率**；
4. 成本以 **token 用量 + 调用次数** 表达（成本代理指标），本仓库没有 Kimi 计价信息，
   不臆造货币单价；
5. 截图为**逐步离散帧**，非连续录屏；初始观察帧与终态动作后的帧不随结果目录保留，
   页面如实标注缺失原因；
6. 展示载荷中的长文本会被截断并标注字数，**完整原文在「运行证据」抽屉里**；
7. 集群挂载路径（`/mnt/…`、账号名）发布前统一替换为占位符；VM 内的
   `/home/user/…` 属任务语义，保留。

## 代码

| 文件 | 行数 | 职责 |
|------|-------|------|
| `adapter.py` | 272 | 结果目录 → 文档（逐题轨迹、成本、耗时、路径清洗） |
| `timeline.py` | 253 | 真实时钟时间轴 + 需求章节 + 结构化需求抽取 |
| `metrics.py` | 106 | 成本/耗时/准确率聚合与多 run 对齐 |
| `frames.py` | 65 | 帧缩放（Pillow，仅构建期） |
| `render.py` | 206 | 任务页渲染 + 展示载荷/证据载荷分离 |
| `pages.py` | 282 | 总览页与对比页渲染（散点图服务端生成 SVG） |
| `build_site.py` | 138 | 编排 + CLI |
| `player/player*.js` | 60–276 | 播放器（内核 / 对比 / 详情 / 任务页四块，零第三方依赖） |
| `player/player*.css` | 112–215 | 样式 |

依赖：Python 标准库 + Pillow（**仅构建期**用于缩放截图；缺失时退化为原样拷贝 PNG）。
页面本身零第三方依赖、零外部请求。

## 测试

```bash
pytest tests/demo -q          # 15 个单测：合成结果目录 → 文档 → 站点
ruff check src tests demo     # demo 也在 lint 范围内
```

单测不依赖 `rjob_logs/` 里的真实 run，CI 上可独立运行。
