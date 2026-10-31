# Goal／任务记忆接入验证

## 范围

2026-10-31，从 AI45Lab/Tandem main 建立独立工作区和 `feature/goal-memory-integration`。
迁入 v7 的 goal、任务记忆和阶段 Verify，保留 main 的 A11y／CDP 语义融合、协议 0.2、
API 号池与 JEV 服务恢复。未修改 `integration/components` 分支、既有实验或共享 VM/依赖。
step/stage 默认路径保留。没有训练模型、没有改评分器、没有加入题号特例。

## 本地检查

```bash
ruff check src tests demo
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m tandem check
PYTHONPATH=src python -c 'from tandem_eval.config_schema import load_config; load_config("infra/config.json")'
```

- Ruff 通过。
- pytest：404 passed。包含 step/stage/goal mock 全链路、部分资料先交付、记忆保护、字段绑定、
  重复导航、goal 消费 CDP 元素、只读刷新不重放、联合选择保留 JEV 地址切换与恢复。
- 协议 0.2：17 个 golden 样例通过；未改 schema/models/validate/samples。
- 私有配置校验通过；凭据文件保持 600 且被 Git 忽略。
- 修改的运行时模块均小于 500 行；无新增运行时依赖。

上述 synthetic/mock 测试不代表真实任务完成或 benchmark 得分。

## 真实 GUI 短测

命令从仓库现有脚本启动，仅测试链路，不等待完整任务：

```bash
bash scripts/run_experiment.sh \
  --experiment goal-memory-gui-smoke-20261031-1806 \
  --tasks 008 --concurrency 1 --slow-model kimi-k3 --slow-key-ids 1,2,3 \
  --execution-mode goal --stage-max-actions 2 --max-steps 6 --max-wall 600
```

这次私有配置为 GUI-only（route.policy=gui、allow_cli=false）；CPU worker 使用
evobox_proxy、private-machine=group、2 CPU、8192 MiB、GPU=0；JEV 复用现有训练服务。
配置及部署、输出路径与正在运行的 v7 双模型实验独立。脚本可通过
TANDEM_EXPERIMENT_ROOT 将归档根设置到下列共享目录的 experiments/。

共享根目录：
`/mnt/shared-storage-gpfs2/evobox-share-gpfs2/xuyuanxun/v0_goal-integration-6step_20261031_smoke`

- 实际源码：`deploy/`。
- 轨迹：`rjob_logs/goal-memory-gui-smoke-20261031-1806-008/episodes/008/`。
- 命令与批次日志：`experiments/goal-memory-gui-smoke-20261031-1806/`。
- 平台状态、日志及人工停止记录：`manual_platform/`。

实际 rjob 为 `tandem-goal-memory-gui-smoke-20261031-1806-0-b3d4b`。
确认 STOPPED 后已归档并删除该记录，原始轨迹保留；只停止了本次 smoke 的本地 watcher。

已验证：

1. Kimi 需求抽取和 goal 规划均返回 HTTP 200，并产生有效结构化计划。
2. 取得真实桌面截图、A11y 及 1337 端口 CDP 快照（首次 4 个元素）。9222 的连接失败未阻断采集。
3. 真实 JEV 连续选择两次向下滚动，排序 used_image=true，耗时约 2.54／2.09 秒。
4. 两次 GuiAction 均经 VM 实际执行，回执 acknowledged=true、returncode=0；
   两条 traj 的 protocol_version 均为 0.2，并保留 browser_snapshot。
5. 人工查看执行后截图，真实 LibreOffice Writer 中的报销指南滚动到填写报告说明。
   不是脚本直接修改文件、mock 或 replay。
6. 已触发 verify_stage 请求，并保存 task_memory.json。按用户要求在两步后主动停止，
   没有等待 Verify 返回、整题完成或评分，不将停止包装为完整验收通过。

## 未通过／未执行的部分

- **未执行整题、长任务或准确率回归**。无正式分数，也不能据两次滚动判断性能提升。
- **真实阶段 Verify 未等待返回**；其契约、记忆提交和阶段出口由本地测试覆盖，尚未完成真机验收。
- **原生 rjob 名称监控／收尾仍有上游已知问题**：main 使用提交前名称监控，而平台返回带后缀
  的完整名称。本 PR 不混入通用集群修复；本次按实际名称人工归档和停止。
- 该短测没有检查真实 GUI 保存／重新打开、跨软件长程恢复或闲时服务抢占。这些不宣称已通过。
- 按用户最新要求，仅推送 fork 分支，PR 由用户手动创建，不自动合并。

## 修改地图

- `src/tandem/memory/`：宿主记忆及角色视图。
- `planning/goal_planner.py`、`verification/goal_verifier.py`、`runtime/goal_stage.py`：规划、执行与验收。
- `components.py`、`config.py`、`runtime/session.py`：可替换装配和可选 goal 入口。
- `gui/targets.py`、`goal_candidates.py`、`grounding.py`、`compile.py`：目标恢复与候选编译；
  保留 main 的 UITarget 语义字段及 semantic_enricher。
- `models/jev.py`：goal 联合具体动作选择，保留 main 的恢复路径；
  `models/slow.py`：goal 图片发送预算和阶段 Verify 额度，不替换 main 号池/传输恢复。
- `tandem_eval/`：仅补 goal 必需的配置传递、只读观察刷新、回执全文和证据/计时落盘；
  `browser.py`、评分器、任务清单、共享环境与 `rjob.py` 不改。
- `scripts/run_experiment.sh`：新增执行模式和阶段额度参数，沿用原默认 stage/10。
- 配置模板、README、阶段说明、结果目录契约和对应测试同步更新。

凭据、截图、轨迹、模型权重和 VM 均不进入 Git；文档只引用共享目录。
