# 阶段执行

通过 `--execution-mode stage` 启用：慢模型规划阶段，JEV/Kev 连续选择 GUI 动作，CLI 执行计划中的命令；优先使用规则验证，证据不足时调用模型 Verify，失败或状态偏离时按需重规划，最终完成仍需独立验证。默认保留原有 `step` 模式。

开发入口（相对 `src/tandem/`）：

- `planning/stage_planner.py`：阶段计划生成与响应校验。
- `runtime/stages.py`：里程碑进度、当前目标重新绑定及重规划。
- `verification/stage_rules.py`：基于回执与 A11y 的后置条件验证。
- `runtime/episode.py`：回执验证编排与独立终态检查。
- `components.py`：按 `execution_mode` 装配规划器，继续复用相同的 GUI 和模型组件。

目标绑定先尝试精确 name/role/parent，再尝试规范化名称和兼容 role；只有唯一匹配才绑定。
全部提案无法唯一绑定时，不再于 JEV 前直接累计 no_action，而是生成当前 scope 内的
有限恢复候选（click、double-click、Enter/Escape）以及 RETURN_TO_PLANNER。
提案已绑定但无法编译为动作时，也进入同一恢复流程；滚动场景额外提供
PageDown/PageUp 和上/下方向键，覆盖菜单内导航。
`stage_replan` 同时记录 `unbound_proposals`、`available_targets` 和 `recovery_scopes`，
供慢模型在下一次修复中选择不同目标或方法。多个匹配仍然不会被静默猜测。

## Goal：带任务记忆的局部连续执行

通过 `--execution-mode goal` 选择，默认模式仍为 step，stage 的里程碑流程保持不变。
该模式从 v7 实验组件迁入，不复制旧环境或覆盖 main 的模型客户端。

执行链路：任务要求 → 任务记忆 → 一个有界子目标 → JEV 连续选择当前可执行动作 →
真实回执/新观察 → 阶段结束时独立 Verify → 更新记忆、继续或回到 Planner。
不会在每个 JEV 动作之后例行调用慢模型 Verify。整题完成仍通过现有独立终态检查。

- `planning/goal_planner.py`：抽取交付单元和资料需求，每次规划一个子目标。
- `memory/state.py`、`memory/context.py`：宿主维护记忆，向 Planner/JEV 提供紧凑视图。
- `runtime/goal_stage.py`：多步执行、回执核对、局部循环限制和阶段边界。
- `verification/goal_verifier.py`：阶段验收、源资料增量提取和证据引用校验。
- `gui/goal_candidates.py`、`gui/grounding.py`：有界动作空间、字段绑定和按需截图候选。
- `components.py`：通过 memory_factory、stage_verifier 和已有组件字段注入，可分别替换。

### 记忆中保存什么

| 字段 | 内容与更新规则 |
|---|---|
| requirements | 原始交付要求、约束、单元及 unit_fact_keys；Planner 不能自行降低要求 |
| facts | 已观察的资料、source_ref、evidence_refs、scope、status、complete，可含 entries/observations；未知内容不猜填 |
| materials | 素材来源、已读 covered_parts、摘要和证据，供跨页面继续读取 |
| work_items | 固定单元、depends_on、缺失资料、status、delivery_state、remaining、停滞次数和上次方法 |
| artifacts | 真实工作/目标路径、保存状态与证据，不把文件存在等同于内容正确 |
| failures / execution_constraints | 执行失败、相同状态中的动作循环及无进展导航限制 |
| active_stage / stats | 当前子目标、输入、动作额度和进展计数；另保存更新拒绝记录与证据索引 |

资料缺一部分不再封锁整个单元：已知部分先制作、保存，需要未知值时再补读。
阶段增量完成与完整单元完成分开；部分资料不能冒充 complete，部分成果不能冒充 unit_met。
已确认源事实不能被“当前没看到”覆盖；修正需要明确 correction_reason 和当前已登记证据。
confirmed 是模型基于证据的判断，不是官方评分保证。内部记忆快照版本不改变消息协议 0.2。

### 与 main 的接口

- goal 同样经过 semantic_enricher，保留 A11y 的 application/description/scope 等字段及 CDP 融合。
  没有浏览器快照时继续使用 A11y/截图，不新增浏览器 mutation 或隐藏状态读取。
- 保留 JEV 的瞬态错误重试、Retry-After、1200 秒恢复窗口和 endpoint_file 地址切换。
  goal 使用联合具体动作选择，operation 排序仅作诊断，不提前剪掉其他动作种类。
- 文本必须绑定唯一观察字段或截图定位字段；不向任意焦点框暴露所有输入。
- 连续四次同类导航做一次阶段检查；两次检查均无资料/交付进展时，限制该窗口内此种导航。
  新资料或交付进展可解除导航限制，不把画面缩放本身当业务完成。
- Environment.observe 只刷新截图/A11y/CDP，不执行或重放动作，不消耗动作步数，仍消耗墙钟预算。
  缺少动作回执仍报错，不重放。观察文件有独立帧名，阶段证据在清理临时目录前持久化。
- API/观察/评分异常继续记 failed_unscored；不把 evaluator、答案或分数送进模型。

### 启动与结果

唯一私有配置仍是 infra/config.json。harness.execution 可配置 mode、stage_max_actions、
verify_max_tokens、verify_reasoning_effort、verify_max_chars；goal 的图片请求可配置
image_quality、max_request_bytes。其余模型、号池、VM 与服务发现沿用原配置。

```bash
bash scripts/run_experiment.sh \
  --experiment goal-memory-smoke --tasks 008 --concurrency 1 \
  --slow-model kimi-k3 --slow-key-ids 1,2,3 \
  --execution-mode goal --stage-max-actions 2 --max-steps 6 --max-wall 600
```

这只是链路短测预算，不代表完整解题预算。脚本默认仍为 stage/10 动作，新增参数会写入 manifest。
事件、回执、CDP 快照和逐角色模型请求沿用原目录；另有 task_memory.json 及 evidence/。
timing.json 增加环境分段、各角色时间/token 和快模型排序统计；没有 usage 的调用单独计数，
不编造 token。真机检查范围及未通过项见 VALIDATION_CN.md，不把短测零分当完整任务成绩。
