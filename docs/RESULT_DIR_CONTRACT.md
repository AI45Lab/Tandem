# 结果目录契约（Result Directory Contract）

> eval ↔ demo 的唯一接口。demo/分析工具只读本契约描述的目录；任何一侧改动必须先改本文档。
> 契约版本：`v0.1`（M2 起）。tandem_eval.recorder 是唯一写入者。

## run 目录（`<output_root>/<run_id>/`）

```
<run_root>/
├── code_version.json        # harness_version / protocol_version / git_describe / images / resources / run_spec（完整 job spec 副本）
├── heartbeat.json           # {time, done, total, current_task}；runner 逐题刷新
├── summary.json             # run 级汇总（demo 与人工验收入口）：total/scored/failed_unscored/
│                            #   average_score/tasks[{task_id, score, status, stop_reason, steps, ...}]
└── episodes/
    ├── manifest.resolved.json   # 实际执行清单（task_id / domain / episode_dir）
    ├── logs/                     # （预留：worker 侧日志，M3）
    └── <domain>-<task_id>/       # episode 目录（无 domain 时为 <task_id>）
```

## episode 目录（自包含：不依赖共享目录与旧仓库即可复盘）

| 文件 | 内容 | 备注 |
|------|------|------|
| `task.json` | 任务定义完整副本 | 自包含要求 |
| `traj.jsonl` | 每执行步一行：`{step_idx, wall_time, protocol_version, observation{screenshot, accessibility_tree, budget, last_receipt}, action}` | 观察/动作即协议消息（文件引用，不内嵌二进制） |
| `llm_calls.jsonl` | 全量 LLM 请求/响应（`role, time, request{payload,messages}, response, attempt`），Bearer 密钥脱敏 | M2 起；KimiClient llm_sink |
| `events.jsonl` | harness 决策事件（planner 计划 / GUI 排序 / 终态裁决） | session.events 逐条 |
| `a11y_digests.jsonl` | 每步 a11y sha256 + 节点数 | `record.a11y_full=true` 时另有 `a11y/step_XX.xml` 全量 |
| `screenshots/step_XX.png` | 逐步截图 | M3 真实环境写入；mock 链路为占位 |
| `artifacts.json` | deliverables 导出记录（vm_path/exported/local_path） | finish.outputs |
| `evaluation.json` / `result.txt` | 官方评分（source/raw/score） | 评分失败时不写（见下） |
| `episode.json` | `{task_id, harness, stop_reason, steps, status(scored|failed_unscored), score, exception_type}` | 终态 |
| `timing.json` | `{wall_seconds, status}` | |

**failed_unscored 纪律**：API/VM/评分异常 ≠ 0 分——异常题不写 `result.txt`，`episode.json.status=failed_unscored`，run 继续下一题；`summary.json.failed_unscored` 单独计数，不计入均分。

**stop_reason 取值**：`done`（Finish）/ Fail.reason（含 `max_steps`、`wall_time_limit`、`no_action_limit`、planner 的 infeasible 理由）/ `exception`。

## 变更规则

- 新增字段允许（向后兼容）；改名/删除/语义变化 = bump 契约版本并同步 recorder 与全部读取方；
- demo 侧永远不得假设未在本文档列出的文件存在。
