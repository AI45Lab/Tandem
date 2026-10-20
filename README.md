# Tandem

**本仓库主体是 Tandem harness**（快慢双模 CUA agent）；`tandem_eval` 仅为适配集群 rjob 的测评薄适配层。

```
Tandem harness ──Observation/Action/Receipt（消息层协议 v0.1）──▶ tandem_eval（rjob/VM/评分）
                                                                      │ 写
                                                              结果目录（自包含契约）
                                                                      │ 读
                                                                  Demo 离线回放
```

三个硬边界：harness ↔ eval 只走协议消息；demo ↔ 其余只走结果目录；本仓库 ↔ 共享资源只读（环境变量寻址，零新增依赖）。

## 状态

- **M0（当前）**：repo 骨架 + 协议 schema v0.1 + golden 测试 + CI。
- 里程碑排期见 [重构计划](../TANDEM_REFACTOR_PLAN_CN.md)；开发纪律见 [AGENTS.md](AGENTS.md)。

## 快速开始

```bash
pip install -e '.[dev]'
ruff check src tests   # lint
pytest                 # 测试（协议 golden 样例 + 负例 + 往返一致）
tandem check           # 协议样例自检
```

## 协议 v0.1 一览

- **Observation**（环境→harness）：task_id / instruction / step_idx / budget / screenshot(文件引用) / accessibility_tree(可选, vm|jev 来源) / last_receipt / protocol_version
- **Action**（harness→环境）：`gui`（OSWorld 动作集）| `cli`（VM 内 bash -lc，timeout≤120s，want_observation=screenshot|none）| `wait` | `finish` | `fail`。**1 个动作 = 1 步，共用 max_steps 预算。**
- **Receipt**（环境→harness）：returncode / stdout / stderr（截尾 12000，全文见 full_output_ref）/ kind / acknowledged

真源：`src/tandem/protocol/schema/`；样例：`src/tandem/protocol/samples/`。
