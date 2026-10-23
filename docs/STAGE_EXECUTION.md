# 阶段执行

`stage` 模式让慢模型一次规划多个里程碑，由 JEV/Kev 连续选择 GUI 动作，或执行计划中的 CLI 命令。
默认仍为 `step` 模式，不改变原有单步流程和动作协议。

## 执行规则

- 每步重新读取截图和 A11y、绑定控件、构造候选，不复用旧坐标或控件 ID。
- 动作后先检查真实回执与规则条件；证据不足时调用模型 Verify。
- 里程碑完成后继续执行，阶段完成后规划下一阶段。
- 目标无法唯一绑定、执行失败、验证未通过或达到阶段动作上限时，请求重规划，并保留已验证进度。
- 仅有状态变化的滚动动作可在当前里程碑内继续；不盲目重放点击或 CLI 命令。
- 整任务完成仍经过独立终态 Verify，阶段完成不等于任务完成。

## 启用

在 `infra/config.json` 的 `harness` 下设置：

```json
"execution": {
  "mode": "stage",
  "stage_max_actions": 24
}
```

也可通过 CLI 覆盖：

```bash
--execution-mode stage --stage-max-actions 24
```

`stage_max_actions` 是阶段动作上限，不是固定的模型调用间隔。
切回原模式使用 `--execution-mode step`；完整集群启动方式见 [CLUSTER_RUNTIME.md](CLUSTER_RUNTIME.md)。

## 开发入口

| 文件 | 职责 |
|---|---|
| `src/tandem/stage_planner.py` | 阶段规划 prompt 与内部计划校验 |
| `src/tandem/stages.py` | 阶段进度、目标重绑定、推进与重规划 |
| `src/tandem/stage_rules.py` | 回执和 A11y 规则验证 |
| `src/tandem/components.py` | 按模式组装规划组件 |
| `src/tandem/session.py`、`episode.py` | 接入执行循环、动作验证与终态检查 |

内部计划包含 `done`、`stage_goal` 和 1–8 个 `milestones`。
每个里程碑描述一个状态转换：GUI 使用 `action_proposals`，CLI 使用 `command`，并给出目标、预期观察和可选 `checks`。
`action_proposals` 是同一前态下的备选动作，不是有序动作序列。

规则支持可见性、精确文本值和 checked/selected/focused/expanded 状态。
缺失或歧义证据不能判成功；退出码为零、打印成功或动作前已满足的条件也不能单独证明达成。

## 日志与测试

沿用现有结果目录；`events.jsonl` 新增 `stage_local`、`stage_progress`、`stage_replan`，
`llm_calls.jsonl` 新增 `plan_stage` role。字段定义见 [RESULT_DIR_CONTRACT.md](RESULT_DIR_CONTRACT.md)。

配置与入口测试在 `tests/eval/test_stage_config.py`、`test_mock_chain.py`。
已做 OSWorld1 小样本真实验证，固定 50 题及 OSWorld2/2.1 阶段模式回归尚未完成。
