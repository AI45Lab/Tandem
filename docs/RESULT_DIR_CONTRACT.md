# 结果目录契约（Result Directory Contract）

> eval ↔ demo/分析 的唯一接口。demo/分析工具只读本契约描述的目录；任何一侧改动必须先改本文档。
> 契约版本：`v0.2`（M3 后）。tandem_eval.recorder 是唯一写入者。

## run 目录（`rjob_logs/<run_id>/`，唯一落盘位置）

```
<run_root>/
├── code_version.json        # harness_version / protocol_version / git_describe / images / run_spec（secrets 段全部 *** 脱敏）
├── heartbeat.json           # {time, done, total, current_task}；runner 逐题刷新
├── summary.json             # run 级汇总（demo 与人工验收入口）
├── platform.status.txt      # rjob get 输出（fetch 写入）
├── platform.tail.log        # rjob 平台日志尾部（fetch 写入）
├── worker/entry.log         # worker 侧运行日志（LLM 审计事件流 + 错误栈）
└── episodes/
    ├── manifest.resolved.json   # 实际执行清单（task_id / domain / episode_dir）
    └── <task_id>/               # episode 目录（有 domain 时为 <domain>-<task_id>）
```

## episode 目录（自包含：不依赖共享目录与旧仓库即可复盘）

| 文件 | 内容 | 写入时机 |
|------|------|---------|
| `task.json` | 任务定义完整副本 | episode 开始 |
| `traj.jsonl` | 每执行步一行：`{step_idx, wall_time, protocol_version, observation{screenshot(sha256/path/w/h), accessibility_tree(present/source/digest/node_count), budget(steps_remaining, wall_seconds_remaining), last_receipt}, action{kind, …}}` | 每步 env.execute 后 |
| `llm_calls.jsonl` | 全量 LLM 请求/响应，每行 `{role, time, request{payload, messages}, response, attempt}`；Bearer/api_key 脱敏 | KimiClient 成功响应时（llm_sink → LlmTap → 本文件） |
| `events.jsonl` | harness 决策事件（route 字段区分）：`planner`（发给 LLM 的计划全文 + 有效响应）/ `gui`（候选列表 + ranking{operation_request, action_request, operation_ranked, action_ranked, winner, margins, latency_ms, used_image} + 编译后动作）/ `cli`（路由决策 + 命令）/ `gui_verified` / `cli_verified`（验证裁决 + 回执）/ `terminal`（终态双确认）/ `action`（runner 写的执行记录，与 session 事件穿插） | session.act() 后增量排水 |
| `a11y_digests.jsonl` | 每步 a11y sha256 + 节点数（`{step_idx, sha256, node_count}`） | 每步（全量 xml 默认关闭，record.a11y_full=true 时另写 `a11y/step_XX.xml`） |
| `screenshots/step_XX.png` | 逐步截图（**契约正本**） | 每步 env.execute 后 |
| `deliverables/` | finish 时从 VM 导出的交付物文件（含 export_paths） | episode 终态 |
| `artifacts.json` | deliverables 导出记录（`[{vm_path, exported, local_path, bytes}]`） | episode 终态 |
| `evaluation.json` | 官方评分（`{source: "official_benchmark_evaluator", raw, score}`） | episode 终态（评分成功时） |
| `result.txt` | 分数（`score\n`） | 同上 |
| `episode.json` | `{task_id, harness, stop_reason, steps, status(scored\|failed_unscored), score, exception_type}` | episode 终态（必写） |
| `timing.json` | `{wall_seconds, status}` | episode 终态 |

## llm_calls.jsonl 的 role 值

| role | 调用方 | 触发时机 |
|------|--------|---------|
| `task_requirements` | verifier.task_requirements | episode 开始时抽取任务需求（1-12 条） |
| `plan_step` | planner.plan_step | 每步规划（截图+可见控件+需求+近期动作→下一步决策） |
| `verify_observation` | verifier.verify_observation | 每步动作执行后独立验证（BEFORE/AFTER 截图→achieved/not_achieved/uncertain）|

`verify_observation` 不信任 planner 的自我宣称：它拿前后截图+预期变化独立裁决，驱动 recent 历史、no_action 连击计数、toggle 检查、以及终态双确认（terminal_claim 模式下逐条核验 requirements + 输出文件存在性）。

## events.jsonl 的 route 值

| route | 内容 |
|-------|------|
| `planner` | plan 的完整请求负载（不含截图二进制）与 LLM 有效响应（done/task_status/goal/proposals 或 route=cli 的 command） |
| `gui` | 候选空间（candidates 列表含描述/坐标）+ ranking（**排序服务的完整输入输出**：两阶段请求全文 + 每选项分数 + margin + latency + used_image）+ 编译后动作 |
| `cli` | planner 的 route=cli 决策 + 命令 |
| `gui_verified` / `cli_verified` | 验证裁决（outcome/task_status/evidence/state_changed）+ 回执 |
| `terminal` | 终态裁决（planner 声称完成后的 verifier 双确认全文） |
| `action`（kind 字段） | runner 写的执行记录 `{step, kind: "action", action: {…协议动作…}}` |

## failed_unscored 纪律

API/VM/评分异常 ≠ 0 分——异常题不写 `result.txt`，`episode.json.status=failed_unscored`，run 继续下一题。`summary.json.failed_unscored` 单独计数，不计入均分。

## stop_reason 取值

| 值 | 含义 |
|---|------|
| `done` | planner 声称完成且 verifier 双确认通过（FinishAction） |
| `<planner 的 infeasible 理由>` | planner 声称不可行且 verifier 确认（FailAction） |
| `max_steps` | 步数预算耗尽 |
| `wall_time_limit` | 墙钟预算耗尽 |
| `no_action_limit` | 连续 3 步无有效动作 |
| `exception` | 环境异常（API/VM/评分/网络） |

## 变更规则

- 新增字段允许（向后兼容）；改名/删除/语义变化 = bump 契约版本并同步 recorder 与全部读取方；
- demo 侧永远不得假设未在本文档列出的文件存在。
