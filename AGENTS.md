# AGENTS.md — Tandem 开发纪律

本文件是协作与代码合入的硬约束。与重构计划（`../TANDEM_REFACTOR_PLAN_CN.md`）冲突时，先改计划再改本文件。

## 仓库定位

主体是 **Tandem harness**（快慢双模 CUA，`src/tandem/`）；`src/tandem_eval/` 仅为适配集群 rjob 的测评薄适配层（6 文件封顶）。任何"往 eval 里加功能"的冲动先自问：它是不是属于 harness 组件、demo 工具或根本不该存在。

## 五条硬纪律（CI/评审强制）

1. **运行时依赖白名单只有 Pillow。** 新增依赖必须在 PR 里单独论证并过维护者确认（共享 venv 冻结，worker 内不能装包，见下"共享资源"）。
2. **每个公开函数必须有主路径调用者或测试调用者**，否则不合并。不留"以后会用"的函数。
3. **单模块 ≤300 行**，超过必须拆分职责。
4. **一个 PR = 一个组件改动 + 单测 + smoke 结果链接**（真机 smoke 在 M3 后可用；此前以 mock 全链路测试代替）。
5. **ruff + pytest + 契约测试三件套从第一天齐上**：本地提交前 `ruff check src tests && pytest` 必须绿。

## 协议纪律（`src/tandem/protocol/`）

- `schema/*.json` 是唯一真源；`validate.py` 是运行时强制者；`samples/*.json` 是 golden 样例。三者由 `tests/protocol/` 锚定，改动必须同步。
- 任何字段增删/语义变化 = bump `protocol_version` 次版本号，并同步全部 golden 样例与 schema。
- **MCP-ready 约束**：消息必须是纯 JSON；二进制一律文件引用（path + sha256）；禁止 Python 对象泄漏（bytes、set、自定义类）。
- 校验器必须严格：未知字段、bool 冒充 int、枚举越界一律拒绝。

## 开发闭环

```
改代码 → ruff check src tests → pytest →（若触碰协议）tandem check → PR（附单测 + smoke 链接）
```

- `tandem check`：协议样例自检（CI 也跑）。
- `tandem-eval entry --spec …`：集群测评入口（M2 实装）。

## 共享资源纪律（worker 侧）

依赖/VM/runtime 在 `/mnt/shared-storage-user/evobox-share-gpfs2/xuyuanxun/shared_resources/sa_cua`，**只读**：

- 寻址一律走其 `env.sh` 导出的环境变量（`OSWORLD_PYTHON`、`OSWORLD1_ROOT`、`OSWORLD1_VM`、`OSWORLD2_ROOT`、`OSWORLD2_VM`、`OSWORLD2_ASSET_ROOT`、`JEV_ENDPOINT` 等），不得硬编码绝对路径。
- 共享 venv 冻结：不在其中安装/升级任何包；本仓库代码经 `PYTHONPATH=repo/src` 挂载即用（纯 Python、零新增依赖、Python 3.12 兼容）。
- 每个 run 的 `code_version.json` 必须记录 git describe、protocol_version、resources.json 的 schema_version、内外镜像 digest。

## 参考实现锚点（旧仓库，已冻结）

旧仓库 `/mnt/shared-storage-user/adpc-share/chenxinquan/fastslow/SA-CUAharness`，只读对照：

| 用途 | 分支/commit |
|------|------------|
| harness 行为参考 | `main @ bc290e3` |
| demo 平移源 | `feature/demo-studio @ 050291a` |
| 可复现运行参考 | `feature/reproducible-runs @ 6489cdc` |

与旧仓库的一切已知行为差异记入 `DEVIATIONS.md`（M1 建立）。

## 目录地图

```
src/tandem/          harness 主体（组件、协议、CLI）
src/tandem/protocol/ 消息层协议：schema/ 真源、validate/ 校验、samples/ golden
src/tandem_eval/     worker 侧 6 文件（entry/env/runner/recorder/scoring/manifest）
                     + 开发机侧 rjob.py 生命周期客户端（DEVIATIONS #14）
tests/               protocol/ harness/ eval/ 三组
infra/worker.sh      rjob worker 入口（mock 即跑；真实基准 M3 接共享 env.sh+docker）
infra/envs/          双视角环境档案：dev.json（开发机）+ rjob.json（worker 容器）
benchmarks/          任务清单（OSW1 指向共享目录 test_nogdrive.json = 361 题；OSW2 smoke 5 题）
tools/               render_summary.py（demo 占位；完整 studio 后续平移）
docs/                RESULT_DIR_CONTRACT.md（eval↔demo 唯一接口）
```
