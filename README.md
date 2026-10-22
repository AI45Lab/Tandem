# Tandem

快慢双模 CUA harness + 集群测评适配层。

```
┌─────────────────┐      消息层协议 v0.1       ┌──────────────────┐
│  Tandem harness  │ ◀──Observation/Action──▶  │  tandem_eval      │
│  (src/tandem)    │      Receipt (JSON)        │  (src/tandem_eval)│
│  planner_led     │                            │  rjob / VM / 评分  │
└─────────────────┘                            └────────┬─────────┘
                                                        │ 写
                                                ┌───────▼────────┐
                                                │ rjob_logs/<id>/  │
                                                │ (自包含结果目录)  │
                                                └───────┬────────┘
                                                        │ 读
                                                ┌───────▼────────┐
                                                │  Demo / 分析     │
                                                │  render_summary  │
                                                └────────────────┘
```

## 快速开始

```bash
# 安装（Python ≥ 3.10，运行时依赖仅 Pillow）
pip install -e '.[dev]'

# 验证
ruff check src tests && pytest && tandem check
```

## 配置

唯一配置文件 [infra/config.json](infra/config.json)（含密钥，已 gitignore；模板见 [config.example.json](infra/config.example.json)）。所有值为绝对路径，开发机与 worker 内一致（adpc 和 evobox 两卷挂载点两侧相同），无占位符、无多档案。

```jsonc
{
  "repo_root":    "…/fastslow/tandem",           // 本仓库
  "deploy_root":  "…/fastslow/tandem-deploy",     // rsync 部署副本（worker 读代码）
  "results_root": "…/tandem/rjob_logs",           // 唯一落盘位置（run 目录 = rjob_logs/<run_id>/）
  "mounts":  [ … ],                               // rjob --mount 参数
  "rjob":    { … },                               // charged_group / cpu / memory / image
  "osw1_root": "…/sa_cua/benchmarks/osworld1",   // 共享资源路径
  "kimi":    { "base_url": "…", "api_key": "…" }, // LLM 凭据（内联值，不通过文件）
  "jev_endpoint": "",                             // 空 = 自动从发现文件读取
  "jev_endpoint_file": "…/services/qwen_jev.json" // 部署侧维护的活地址
}
```

## 运行单题

```bash
tandem-eval rjob run --run-id <name> --benchmark osworld1 \
  --tasks <task-id> \
  --repo . --config infra/config.json --poll 60 --timeout 3600
```

常用参数：

| 参数 | 说明 |
|------|------|
| `--benchmark` | `mock` / `osworld1` / `osworld2` |
| `--tasks` | 逗号分隔 task id（覆盖 manifest） |
| `--limit N` | 取清单前 N 题 |
| `--shard I/N` | 把（limit 后的）清单交错切成 N 片，本 run 跑第 I 片（并发用） |
| `--selector jev/kev` | 排序后端（默认 jev；kev 走 System One API） |
| `--max-steps / --max-wall` | 单题预算（步数/墙钟秒） |
| `--allow-cli true/false` | 是否允许 planner 选 CLI 路由 |
| `--kimi-reasoning off/low/medium/high` | LLM 思考强度（默认 low） |
| `--export-paths` | 逗号分隔的 VM 内交付物路径（finish 时导出） |

## 批量运行

```bash
bash scripts/run_osw2_20x5.sh    # 20 题、5 并发（自动切片+提交+等收敛+汇总）
```

## 结果目录结构

所有产物落盘在 **唯一位置** `rjob_logs/<run_id>/`（无其它副本）：

```
rjob_logs/<run_id>/
├── summary.json           # run 级汇总（demo/人工验收入口）
├── heartbeat.json         # 进度心跳（done/total/current_task）
├── code_version.json      # git describe + 协议版本 + 镜像 + run spec（secrets 已脱敏）
├── platform.status.txt    # rjob get 输出
├── platform.tail.log      # rjob 平台日志尾部
├── worker/entry.log       # worker 侧运行日志（LLM 审计 + 事件流）
└── episodes/<task_id>/
    ├── task.json          # 任务定义副本（自包含）
    ├── traj.jsonl         # 每步：观察(截图/a11y/预算) + 动作 + 回执 + protocol_version
    ├── llm_calls.jsonl    # 全量 LLM 请求/响应（role: plan_step / verify_observation / task_requirements）
    ├── events.jsonl       # 决策事件（planner 计划 / JEV/Kev 排序 / 验证裁决 / 终态）
    ├── screenshots/       # 逐步截图（契约正本）
    ├── a11y_digests.jsonl # 每步 a11y 摘要（sha256 + 节点数）
    ├── deliverables/      # finish 时导出的 VM 文件
    ├── evaluation.json    # 官方评分（source/raw/score）
    ├── result.txt         # 分数
    └── episode.json       # 终态（score/status/stop_reason/steps）
```

## Demo（轨迹回放与对比）

`demo/` 只读结果目录，把 OSWorld2 的运行变成静态站点：逐步回放桌面轨迹与模型操作链
（规划 → 候选排序 → 编译动作 → 独立验证 → 终态双确认），并横向对比多个 run 的
**成本 / 耗时 / 准确率**。

```bash
python demo/build_site.py --runs-root rjob_logs --out demo/site --benchmark osworld2
python -m http.server 8899 --directory demo/site    # 本地预览
```

详见 [demo/README.md](demo/README.md)。

## 排序服务（JEV / Kev）

两个后端跑同一套两阶段排序（operation → action），harness 侧一行开关切换：

| 后端 | 协议 | 截图 | endpoint 发现 |
|------|------|------|--------------|
| **jev**（默认） | `GET /` + `POST /rank` | 需要（暂存到 evobox 中转目录） | `qwen_jev.json` |
| **kev** | System One `POST /v1/systemone` | 不需要（纯文本） | `kev.json` |

两个服务部署在闲时 GPU，地址随重新部署变化 → 配置里 endpoint 留空即自动从发现文件读取最新地址（worker 侧建 session 时解析，含就绪位检查和双视角符号链接兜底）。

## 架构要点

| 边界 | 规则 |
|------|------|
| harness ↔ eval | 只走消息层协议（Observation/Action/Receipt JSON Schema） |
| eval ↔ demo/分析 | 只读结果目录（契约见 [docs](docs/RESULT_DIR_CONTRACT.md)） |
| 仓库 ↔ 共享资源 | 只读，经 `infra/config.json` 寻址，零新增依赖 |
| 落盘 | 唯一位置 `rjob_logs/<run_id>/`；`obs_stage/`（episode 内工作区）结束即清 |

## 更多文档

- [docs/RESULT_DIR_CONTRACT.md](docs/RESULT_DIR_CONTRACT.md) — 结果目录契约（字段级定义）
- [DEVIATIONS.md](DEVIATIONS.md) — 与旧仓库的行为差异清单（M1–M3 全量）
- [AGENTS.md](AGENTS.md) — 开发纪律与目录地图
- [TANDEM_REFACTOR_PLAN_CN.md](../TANDEM_REFACTOR_PLAN_CN.md) — 重构总计划
