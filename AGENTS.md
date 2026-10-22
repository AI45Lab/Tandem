# AGENTS.md — Tandem 开发纪律

本文件是协作与代码合入的硬约束。与重构计划（`../TANDEM_REFACTOR_PLAN_CN.md`）冲突时，先改计划再改本文件。

## 仓库定位

主体是 **Tandem harness**（快慢双模 CUA，`src/tandem/`）；`src/tandem_eval/` 仅为适配集群 rjob 的测评薄适配层（worker 侧 6 文件 + 开发机侧 rjob.py 生命周期客户端）。

## 五条硬纪律（CI/评审强制）

1. **运行时依赖白名单只有 Pillow。** 新增依赖必须在 PR 里单独论证并过维护者确认（共享 venv 冻结，worker 内不能装包）。
2. **每个公开函数必须有主路径调用者或测试调用者**，否则不合并。不留"以后会用"的函数。
3. **单模块 ≤300 行**，超过必须拆分职责。
4. **一个 PR = 一个组件改动 + 单测 + smoke 结果链接**（真机 smoke 已可用：`--benchmark mock` 走 mock 链路；真实基准走 OSW1/OSW2）。
5. **ruff + pytest + 契约测试三件套从第一天齐上**：本地提交前 `ruff check src tests && pytest` 必须绿。

## 协议纪律（`src/tandem/protocol/`）

- `schema/*.json` 是唯一真源；`validate.py` 是运行时强制者；`samples/*.json` 是 golden 样例。三者由 `tests/protocol/` 锚定，改动必须同步。
- 任何字段增删/语义变化 = bump `protocol_version` 次版本号，并同步全部 golden 样例与 schema。
- **MCP-ready 约束**：消息必须是纯 JSON；二进制一律文件引用（path + sha256）；禁止 Python 对象泄漏（bytes、set、自定义类）。
- 校验器必须严格：未知字段、bool 冒充 int、枚举越界一律拒绝。

## 配置纪律

- `infra/config.json` 是**唯一**配置文件（含密钥 → gitignore；模板 `config.example.json` 提交）。
- 所有值为绝对路径；开发机与 worker 内一致（adpc 和 evobox 两卷挂载点两侧相同）。
- 排序服务 endpoint（JEV/Kev）留空 = 自动从 `services/qwen_jev.json` / `kev.json` 发现文件读取最新地址（worker 侧建 session 时解析）。
- LLM 凭据（kimi 三件套）和 docker registry auth 内联在 config 中，经 job spec 传入 worker（`code_version.json` 中 run_spec 的 secrets 段自动脱敏为 `***`）。
- **禁止**新增任何形式的环境档案/占位符展开/多配置文件。

## 开发闭环

```
改代码 → ruff check src tests → pytest →（若触碰协议）tandem check → PR（附单测 + smoke 链接）
```

- `tandem check`：协议样例自检（CI 也跑）。
- `tandem-eval rjob run …`：一站式提交（sync→spec→submit→watch→fetch→cleanup）。
  **收尾默认删 rjob**——成功/失败/超时/异常都删，不在集群上留残留；`--keep` 保留现场。
- `tandem-eval entry --spec …`：worker 侧入口（infra/worker.sh 调用）。

## 共享资源纪律（worker 侧）

依赖/VM/runtime 在 `/mnt/shared-storage-user/evobox-share-gpfs2/xuyuanxun/shared_resources/sa_cua`，**只读**：

- `infra/worker.sh` 在真实基准时 source 共享 `env.sh`（`OSWORLD_PYTHON`、`EVAL_TOOLS`、`LD_LIBRARY_PATH` 等）。
- 共享 venv 冻结：不在其中安装/升级任何包；本仓库代码经 rsync 部署副本 + `PYTHONPATH` 挂载即用（纯 Python、零新增依赖、Python 3.12 兼容）。
- 每个 run 的 `code_version.json` 必须记录 git describe、protocol_version、镜像 digest、run spec（secrets 脱敏）。
- OSW2 任务资产经 `OSWORLD_FILE_BASE_URL` 指向本地 `asset_root`（避免外网下载）；必须在任务模块 import **前**设置（见 osworld.py `_bootstrap_runtime`）。

## LLM 调用纪律（KimiClient）

- `reasoning_effort` 默认 `low`（探测 97→22 token）；`off` 映射 `enable_thinking=false`（归零）。
- 空正文（全留在思考通道）→ 下一次重试自动升档（low→medium→high）。
- 叙述文字包裹 JSON → `extract_json_object` 自动抢救（剥围栏 + 首个平衡 `{…}`）。
- 403（TPM 配额限流）→ 指数退避（60/120/240/480s），总计 5 次尝试。
- `finish_reason=length` → 明确报错提示调大 `kimi_max_tokens`（默认 16384）。

## JEV 排序服务纪律

- `/rank` 要求 `image_path` 是**服务宿主机可读的文件路径**——截图暂存到 evobox 中转目录（`jev_image_stage_write/read`），payload 携带 JEV 宿主机视角路径。
- 暂存按内容哈希命名去重（`step_00_<sha16>.png`），断点无害。
- endpoint 地址随闲时 GPU 重新部署变化 → 留空走自动发现文件（含 `ready`/`status` 就绪位检查）。

## 参考实现锚点（旧仓库，已冻结）

旧仓库 `/mnt/shared-storage-user/adpc-share/chenxinquan/fastslow/SA-CUAharness`，只读对照：

| 用途 | 分支/commit |
|------|------------|
| harness 行为参考 | `main @ bc290e3` |
| demo 平移源 | `feature/demo-studio @ 050291a` |
| 可复现运行参考 | `feature/reproducible-runs @ 6489cdc` |

与旧仓库的一切已知行为差异记入 `DEVIATIONS.md`。

## 目录地图

```
src/tandem/              harness 主体（组件、协议、CLI）
src/tandem/protocol/     消息层协议：schema/ 真源、validate/ 校验、samples/ golden
src/tandem_eval/         worker 侧 6 文件（entry/env/runner/recorder/scoring/manifest）
                         + 开发机侧 rjob.py / rjob_spec.py / rjob_status.py 生命周期客户端
tests/                   protocol/ harness/ eval/ demo/ 四组
infra/worker.sh          rjob worker 入口（mock 即跑；真实基准走共享 env.sh+docker）
infra/config.json        唯一配置文件（含密钥 → gitignore；模板 config.example.json 提交）
scripts/                 批量运行脚本（run_osw2_20x5.sh 等）
tools/                   render_summary.py（demo 占位；完整 studio 后续平移）
demo/                    轨迹回放与对比站点（adapter/metrics/frames/render + player/）
                         只读结果目录，不 import harness、不调模型、不碰 VM
docs/                    RESULT_DIR_CONTRACT.md（eval↔demo 唯一接口）
                         CLUSTER_RUNTIME.md（内部集群运行手册：rjob/共享资源/已知坑）
```

## 结果目录纪律

- 唯一落盘位置 `rjob_logs/<run_id>/`；`obs_stage/`（episode 内工作区）结束即清。
- `events.jsonl` 必须包含 planner/gui(ranking)/cli/verified/terminal 全部事件（增量排水，游标推进）。
- `llm_calls.jsonl` 只记 Kimi 调用（3 种 role）；JEV/Kev 排序的输入输出记在 `events.jsonl` 的 gui 事件 `ranking` 字段。
- secrets 段（api_key/registry auth）在 `code_version.json` 的 run_spec 副本中全部脱敏为 `***`。
