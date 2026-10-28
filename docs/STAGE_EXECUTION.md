# 阶段执行

通过 `--execution-mode stage` 启用：慢模型规划阶段，JEV/Kev 连续选择 GUI 动作，CLI 执行计划中的命令；优先使用规则验证，证据不足时调用模型 Verify，失败或状态偏离时按需重规划，最终完成仍需独立验证。默认保留原有 `step` 模式。

开发入口（相对 `src/tandem/`）：

- `planning/stage_planner.py`：阶段计划生成与响应校验。
- `runtime/stages.py`：里程碑进度、当前目标重新绑定及重规划。
- `verification/stage_rules.py`：基于回执与 A11y 的后置条件验证。
- `runtime/episode.py`：回执验证编排与独立终态检查。
- `components.py`：按 `execution_mode` 装配规划器，继续复用相同的 GUI 和模型组件。
