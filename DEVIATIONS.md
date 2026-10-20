# 与旧仓库（SA-CUAharness，冻结于 main@bc290e3）的已知行为差异

人工验收与代码评审对照本清单。按计划 §3.1 有意排除的项标注【计划内】，接口移植中的取舍标注【重构】。

## M1（planner_led 主路径移植）

1. 【计划内】**visual_fallback / ground_visual 延后**：planner 提 visual_fallback 或候选不可编译时，旧版经视觉 grounding 恢复；新版 `components.grounder=None`，胜出者 visual_fallback → compile None → 记 no_action，连续 3 次停止。**影响：依赖视觉坐标定位的任务（含全部 drag 场景）在 grounder 回归前会失败**。grounder 作为普通组件回归后此差异消除。
2. 【计划内】**drag 动作不可产生**：旧版 drag 仅经 visual_point（视觉 grounding）产生；M1 无 grounder → 无 drag。协议保留 `drag` 类型，参数 `{x, y, end_x, end_y}`。
3. 【重构】**输出文件存在性检查改为 CLI 探针**：旧版 done 分支经 `env.controller.execute_python_command` 同步查询（不占步数）；协议化后 harness 无法直访 VM，改为一条 `CliAction`（`python3 -c …isfile…`，`want_observation="none"`，timeout 30s），**多消耗 1 步预算**。仅当 requirements 含 output_path 时发生。
4. 【重构】**完成被拒后的重规划发生在同一 act() 内**：旧版 `continue` 后重取环境观察（无动作执行，内容等价）；新版不重读观察，直接再次调用 planner。
5. 【重构】**export_paths 移至 eval**：旧 `RuntimeConfig.export_paths` 参与交付物导出；新版该配置归 tandem_eval job spec（M2），harness 的 `FinishAction.outputs` 只含需求 output_path。
6. 【重构】**pyautogui 代码生成移至执行层**：harness 输出声明式 GuiAction（坐标/文本/键序列），M2 执行层负责展开（type 前的 ctrl+a、table_cell 的 F2、scroll ±5 clicks、多键序列间 sleep 0.2 等语义已编码在 parameters 中）。set_slider 仍编译为按分数位置的 click（与旧一致）。
7. 【重构】**预算强制主责在 runner（M2）**：harness 在 budget 耗尽时返回 `FailAction(max_steps / wall_time_limit)` 作镜像防御；墙钟以 runner 侧计时为准。
8. 【重构】**a11y 缺失（OSW2 JEV 降级）可继续**：旧版假设始终有 accessibility_tree；新版 tree=None 时以空目标列表 + `"<empty/>"` 上下文运行 planner，由 CLI 路由或 no_action 兜底。
9. 【重构】**CLI `want_observation="none"` 时验证截图复用**：AFTER 与 BEFORE 可能同图；验证仍携带 execution_result（回执优先）。旧版 CLI 步骤总有新截图。
10. 【重构】**停止原因由终态动作承载**：旧版 stop_reason 写 episode.json；新版 `FailAction.reason` / Finish 表达，runner（M2）负责落盘。新增 `no_action_limit` 兜底上限（同一观察内最多 NO_ACTION_LIMIT+3 次重规划）。
11. 【阶段】**LLM 全量请求/响应落盘（llm_calls.jsonl）在 M2 recorder 实现**；M1 保持与旧版一致的 kimi_http.jsonl 审计（仅元数据 + 错误路径脱敏 body）。
12. 【重构】**selector opener 可注入**：`JevOmniPolicy(endpoint_file, timeout_seconds, opener=None)`，默认行为与旧版一致（唯一接口差异，为可测试性）。
13. 【重构】**SessionConfig 校验 cli_timeout_seconds ∈ [1,120]**（协议上限）；旧版无此约束（默认 90 未越界，实际无行为差异）。

## 保持一致（重点核对项）

- planner / verifier / requirements 的 system prompt 与响应校验逻辑**逐字一致**；
- 候选构建、focus_candidates、prune_stalled、action_key、toggle_transition、A11yTargetBuilder 逻辑一致；
- 停止条件语义一致（no_action 连续 3 次、完成双确认、failed_toggles 记忆）；
- CLI 回执 schema（returncode/stdout/stderr 截尾 12000/kind/acknowledged）一致；
- JEV 排序两阶段（operation→action）、单候选捷径、1200s 恢复循环一致。
