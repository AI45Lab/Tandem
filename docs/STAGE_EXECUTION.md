# 阶段执行、规则验证与按需重规划

## 目的与边界

这是对 Tandem 决策策略的可选扩展，不替换环境、排序模型或动作协议。
默认 `step` 模式保持原有逐步 Planner → 执行 → 模型 Verify 的行为。
`stage` 模式一次规划一个有边界的阶段，阶段内按新观察持续执行，阶段结束再规划后续工作。
不强制整任务只规划一次，也不保证固定数量动作内可以完成任意阶段。

```text
原始任务 → 需求抽取 → 慢模型规划当前阶段（1–8 个里程碑）
  → 当前截图与 A11y → 当前里程碑目标重绑定 → 候选构造 → JEV/Kev 选择 → 真实执行
  → 回执与后续观察 → 规则检查优先，证据不足才用模型 Verify
      → 已达成：推进下一里程碑；阶段完成后规划下一阶段
      → 仍可安全滚动：留在当前里程碑，继续观察和选择
      → 失败／无法绑定／证据不足未获确认：请求剩余工作的重规划
  → Planner 声称完成 → 原有输出文件探针与独立终态 Verify → Finish 或返回规划
```

CLI 里程碑执行慢模型明确给出的命令，stdout/stderr 和真实退出码进入验证。
退出码为零、命令打印“成功”、文件名或界面变化都不能单独证明任务完成。
本版没有“任意自然语言目标自动转换成完整 GUI 程序”的能力；不确定的新界面必须返回规划。

## 配置和启动

唯一用户配置仍是 `infra/config.json`。增加可选段，省略时等同下列默认值：

```json
"execution": {
  "mode": "step",
  "stage_max_actions": 24
}
```

该段放在 `harness` 下。`stage_max_actions` 是单个阶段内实际执行动作的上限，
不是强制每隔 24 步调用模型；提前完成、不确定或失败可以更早返回规划。
全任务步数、墙钟限制仍由现有 budget 和 runner 管理。

完成正常集群配置后，在仓库根执行：

```bash
PYTHONPATH=src python -m tandem_eval rjob run \
  --config infra/config.json --repo . --run-id stage-smoke \
  --benchmark osworld1 --tasks bb5e4c0d-f964-439c-97b6-bdb9747de3f4 \
  --execution-mode stage --stage-max-actions 24 \
  --allow-cli true --route-policy auto --max-steps 50 --max-wall 1800
```

模型仍用现有 `--slow-model NAME`、`--fast-model NAME` 选择。
恢复单步模式只需使用 `--execution-mode step`。
集群权限、服务发现、共享环境与 rjob 生命周期约定见 `CLUSTER_RUNTIME.md`。
当前主线 rjob 客户端存在实际任务名可能追加后缀的已知监控问题；本 PR 不修改该客户端。
若平台追加后缀，必须按 submit 返回的完整名称检查、归档及清理，不能误判 worker 未启动。

## 内部计划格式

阶段计划是组件内部数据，不是 Action/Observation/Receipt 协议的新字段。
计划由 `stage_planner.valid_stage` 校验。示例中的控件名只是说明，不能当真实任务预制动作：
校验失败时向既有客户端的下一次尝试提供格式纠正信息，不增加重试次数、不截断计划或放宽类型。

```json
{
  "done": false,
  "stage_goal": "打开设置并启用选项",
  "milestones": [
    {
      "route": "gui",
      "current_goal": "打开设置对话框",
      "expected_observation": "出现设置中的 Enabled 控件",
      "action_proposals": [
        {"operation": "click", "target_name": "Settings", "target_role": "push_button"}
      ],
      "checks": [
        {"target": {"name": "Enabled", "role": "check_box"}, "property": "visible", "expected": true}
      ]
    },
    {
      "route": "gui",
      "current_goal": "启用选项",
      "expected_observation": "Enabled 处于选中状态",
      "action_proposals": [
        {"operation": "click", "target_name": "Enabled", "target_role": "check_box"}
      ],
      "checks": [
        {"target": {"name": "Enabled", "role": "check_box"}, "property": "checked", "expected": true}
      ]
    }
  ]
}
```

- 每个里程碑给出一条具体状态转换；GUI 可以给 1–4 个动作提案供候选构造。
- 不缓存 `target_id` 或坐标。按每帧的精确名称、role、可选 `parent_contains` 重绑。
- 多个同名控件不能随意选第一个；无法唯一绑定会请求重规划。
- CLI 里程碑使用 `route: cli`、`command`、目标和预期结果；通常 `checks: []`。
- GUI 操作沿用现有 click、double_click、type_text、keypress、scroll、slider、wait 路径。
- 条件支持 `visible: boolean`、精确 `value`、checked/selected/focused/expanded 状态。
  缺失、歧义和未知状态返回 uncertain；不把“未找到”直接当作“不存在”的证明。
- 所有后置条件满足且至少一个条件是动作后新出现的证据，才规则确认 achieved。
  点击前已经可见的按钮本身不能证明点击成功。
- 无规则、证据未知或所有条件动作前已满足时，交给原有独立模型 Verify。
- 明确不满足的状态请求修复；仅在界面确有变化的滚动动作中允许局部继续，仍受阶段上限约束。
- CLI 失败或回执未确认直接记录失败，不自动重放该命令。

## 代码地图与开发入口

| 文件 | 职责 |
|---|---|
| `src/tandem/stage_planner.py` | 阶段 prompt 和内部计划校验；慢模型请求 role 为 plan_stage |
| `src/tandem/stages.py` | 每个 session 的阶段进度、语义重绑定、推进和重规划决策 |
| `src/tandem/stage_rules.py` | A11y 可观察条件与回执检查，不调用模型、不执行环境动作 |
| `src/tandem/components.py` | 根据执行模式选用规划组件，排序后端不变 |
| `src/tandem/session.py` | 保留单步路径，接入阶段组件；动作仍逐个交给环境 |
| `src/tandem/episode.py` | 动作验证分流；终态独立验证沿用原实现 |
| `src/tandem/config.py` | execution_mode、stage_max_actions 的会话配置 |
| `src/tandem_eval/config_schema.py`、`rjob_spec.py`、`__main__.py` | 配置校验、spec 和 CLI 接线 |
| `src/tandem_eval/entry.py` | mock 模式也识别阶段计划，仅用于明确标识的开发测试 |
| `tests/harness/test_stages.py`、`tests/eval/test_stage_config.py` | 执行与配置回归 |
| `tests/eval/test_mock_chain.py` | 明确标识的 step/stage 开发链路与结果目录回归 |
| `infra/config.example.json` | 可提交的执行模式配置模板，不含真实凭据 |
| `README.md`、`DEVIATIONS.md` | 功能入口及相对旧实现的行为差异 |
| `docs/CLUSTER_RUNTIME.md`、`docs/RESULT_DIR_CONTRACT.md`、本文 | 启动参数、事件字段与开发说明 |

增加规则条件时先修改 `stage_rules.py` 和计划校验，再补对应证据不足/矛盾单测。
更换阶段规划方法走 `components.py`，不要把特定厂商、任务 ID 或 benchmark 答案写进状态机。
本 PR 不增加依赖，不修改官方任务、评分器、环境安装或模型服务部署。
阶段 prompt 明确保留用户原始范围，不能自行增加匹配模式、选择过滤或例外来缩小要求。

## 记录与验收

沿用 `rjob_logs/<run_id>/episodes/<task_id>/`，不另设结果系统：

- `events.jsonl`：planner 只在真实调用时记录；stage_local 表示消费阶段计划，不是新模型调用。
  stage_progress 记录里程碑证据；stage_replan 记录修复原因。
- gui/cli 与 gui_verified/cli_verified 保留现有事件，验证增加 source 与 seconds。
  source 为 rule_receipt、rule_a11y 或 model。planner 事件增加 seconds。
- `llm_calls.jsonl`：沿用原始请求/响应和 usage；新增 plan_stage role。
  统计模型次数以该文件为准，不把阶段执行器每次运行计为 Planner 调用。
- `timing.json`、`episode.json`、`evaluation.json`：继续使用原有 recorder 和官方评分。
  本 PR 不改变 API 异常耗时的统计口径，不声称已经实现完整的异常开销剔除。

开发测试必须验证：阶段内至少两个动作不重复规划、每帧目标重新绑定、失败和未知证据不误报、
单步路径保持通过、最终完成仍独立检查。真实 smoke 必须明确使用真实模型/JEV/VM，
单题通过不等于固定 50 题效果无退化；大规模同题对比仍需另跑。

## 2026-10-24 实际检查与真实试跑

本次检查：`ruff check src tests demo` 通过，`PYTHONPATH=src pytest -q` 为 274 passed，
`PYTHONPATH=src python -m tandem check` 为 16 个样例通过；`git diff --check` 通过。
没有修改 Action/Observation/Receipt schema；没有训练或替换模型，没有添加运行时依赖。

真实试跑使用 MiniMax-M3.1-Flash（命名 API 为 minimax-shared）、reasoning_effort=low、
max_tokens=32768，以及已有训练好的 Qwen-JEV。不是 Kimi/max 强度的历史成绩复现。
每个 VM worker 为 evobox_proxy/private-machine=group、4 CPU、16384 MiB、0 GPU，
JEV 复用已有 GPU 服务。每次试跑是独立 VM，保留官方任务和原生评分。
以下全部是模型实时执行，不是 mock 或固定动作回放。

结果根目录：

```text
/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/tandem_stage_execution_pr_20261024/rjob_logs
```

| run_id | 题目与模式 | 原生分数 | 结论 |
|---|---|---:|---|
| stage-real-gui-20261024 | Chrome 默认搜索引擎，GUI-only 阶段模式 | 1.0 | 5 个真实 GUI 动作；轨迹有同一计划连续两次执行；一次 JEV 超时后自行恢复 |
| stage-real-cli-gui-20261024 | VS Code 替换，初版 CLI+GUI 阶段模式 | 0.0 | Planner 擅自收窄为完整单词匹配，Verify 也接受了收窄解释；不是成功案例 |
| stage-real-scope-v2-20261024 | 同题，第一次约束修订 | 0.0 | 仍错误收窄范围；还暴露过长计划和条件字段格式问题，记录保留 |
| step-real-scope-v2-20261024 | 同题，原有单步模式 | 1.0 | 6 个真实 GUI 动作；允许 CLI，但模型本次选择 GUI |
| stage-real-scope-v3-20261024 | 同题，原文优先、明确字段、紧凑控件与格式纠正后的阶段模式 | 1.0 | 1 CLI + 1 JEV GUI，2 次有效 Planner 调用（含最终完成声明） |
| stage-real-final-20261024 | 同题，最终代码快照 | 1.0 | 8 JEV GUI + 1 CLI；6 次规则检查、3 次模型动作 Verify；4 次 Planner（含完成声明），另有独立终态 Verify |

初次失败后只补通用约束：原文优先于抽取笔记、不得引入未请求的匹配范围、阶段不要覆盖整条
未知任务、条件 property 使用明确枚举、格式失败在既有尝试内纠正。没有写入题目 ID、答案、
目标文件内容或按评分结果修改任务。动作提案是同一前态下的备选，不是有序动作列表。
修复请求携带本阶段已验证的里程碑，避免重做已确认工作。
最终记录中 9 次动作验证有 6 次来自 rule_a11y，3 次来自 model，证明真实任务已走规则分流，
但这一个任务的覆盖率不能外推为整个 benchmark 的覆盖率。

每次部署保留独立源码目录（deploy、deploy-cli、deploy-scope-v2、deploy-scope-v3、
deploy-final），不在运行中覆盖 worker 源码。对应私有 spec 在各目录的 job_specs 下，权限 600；
不进入 Git 或 PR。最终任务在 worker 内的实际入口为：

```bash
bash /mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/tandem_stage_execution_pr_20261024/deploy-final/infra/worker.sh \
  /mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/tandem_stage_execution_pr_20261024/deploy-final/job_specs/stage-real-final-20261024.json
```

该命令只应在已申请的 worker 中执行，不能在开发机直接启动 VM。
真实任务轨迹、截图、原始 LLM usage、timing 和 evaluation 在上述结果根的各 run 内。
完成任务的平台记录先归档到同级 `rjob_archive/<完整任务名>/`，再删除 rjob；不删除轨迹。
worker 创建的 run 目录由容器 root 所有，开发机归档使用独立的用户可写目录，未放宽共享目录权限。

尚未完成的验收：固定 50 题同题性能回归、OSWorld2/2.1 阶段模式回归，以及真实任务中规则
验证覆盖率的充分验证。这些小样本不能证明准确率无退化或平均时间/token 的因果改善。
原有单步模式仍为默认，新模式尚不应直接作为默认生产配置。
