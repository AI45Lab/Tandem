"""rjob 测试的共享假件：假命令执行器 / 最小配置 / 真机捕获样本。

单独成模块，避免 test_rjob_client.py 与 test_rjob_cleanup.py 互相 import。
"""

from __future__ import annotations

import copy


class FakeRunner:
    """假命令执行器：rjob 按子命令路由到脚本化输出（列表逐个弹出，最后一个常驻）。
    fail_on 中的子命令永远返回退出码 1（模拟 rjob CLI 自身崩溃）；
    fail_times 中的子命令前 N 次失败、之后成功（模拟"仍在终止中"这类瞬时拒绝）。"""

    def __init__(self, script: dict | None = None, fail_on: set[str] | None = None,
                 fail_times: dict[str, int] | None = None):
        self.script = script or {}
        self.fail_on = fail_on or set()
        self.fail_times = dict(fail_times or {})
        self.failed_counts: dict[str, int] = {}
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:1] == ["rjob"]:
            sub = argv[1]
            if sub in self.fail_on:
                return 1, "TypeError: 'NoneType' object is not iterable"
            budget = self.fail_times.get(sub, 0)
            if budget > 0:
                self.fail_times[sub] = budget - 1
                self.failed_counts[sub] = self.failed_counts.get(sub, 0) + 1
                return 1, f"rjob {sub}: job is still terminating"
            outputs = self.script.get(sub, [""])
            value = outputs.pop(0) if len(outputs) > 1 else outputs[0]
            return 0, value
        return 0, ""


# 2026-10-20 真机捕获的 rjob get 输出（tandem-mocktest-1，Succeeded）
REAL_SUCCEEDED = (
    "10-20 20:14:08 [INFO] rjob tandem-mocktest-1: Succeeded\n"
    "10-20 20:14:08 [INFO]   |- task generated-task-0: 1 replicas "
    "{'active': 0, 'succeeded': 0, 'failed': 0, 'created_failed': 0, 'pending': 0}\n"
    "10-20 20:14:08 [INFO]        |- replica tandem-mocktest-1-fdq75: SUCCEED, "
    "lg-cmc-h-cpu-0097.host.h.pjlab.org.cn"
)
REAL_RUNNING = (
    "10-20 20:13:29 [INFO] rjob tandem-mocktest-1: Running\n"
    "10-20 20:13:29 [INFO]   |- task generated-task-0: 1 replicas "
    "{'active': 1, 'succeeded': 0, 'failed': 0, 'created_failed': 0, 'pending': 0}"
)

#: 最小配置（结构同 infra/config.json：harness / eval / log 三段）
CONFIG = {
    "harness": {
        "slow_model": {
            "default": "kimi-k3",
            "apis": {
                "kimi-k3": {
                    "base_url": "https://k.example/v1", "api_key": "sk-x", "model": "kimi-k3",
                    "max_tokens": 4096, "timeout_seconds": 60,
                    "reasoning_effort": "low", "direct_api": False,
                },
            },
        },
        "fast_model": {
            "default": "jev",
            "apis": {
                "jev": {
                    "backend": "jev", "endpoint": "http://10.1.1.1:8891",
                    "endpoint_file": "/shared/services/qwen_jev.json", "timeout_seconds": 30,
                },
                "kev": {
                    "backend": "kev", "endpoint": "",
                    "endpoint_file": "/shared/services/kev.json", "timeout_seconds": 30,
                },
            },
            "image_stage": {"write": "/stage", "read": "/stage-read"},
        },
        "route": {"policy": "auto", "allow_cli": True, "cli_timeout_seconds": 90},
        "budget": {"max_steps": 5, "max_wall_seconds": 60},
    },
    "eval": {
        "repo_root": "/dev-repo",
        "deploy_root": "/dev-deploy",
        "shared_env": "/shared/env.sh",
        "mounts": [{"source": "gpfs://gpfs2/share", "target": "/mnt/share"}],
        "rjob": {"charged_group": "evobox_proxy", "private_machine": True, "cpu": 4,
                 "memory": 16384, "gpu": 0, "image": "reg.example/outer:1"},
        "inner_image": "reg.example/inner:1",
        "benchmarks": {
            "osworld1": {"root": "/shared/osw1", "vm": "/shared/vm1.qcow2"},
            "osworld2": {"root": "/shared/osw2", "vm": "/shared/vm2.qcow2",
                         "asset_root": "/shared/assets"},
            "osworld21": {
                "root": "/shared/osw21/runtime", "vm": "/shared/osw21/vm.qcow2",
                "asset_root": "/shared/osw21/assets", "shared_env": "/shared/osw21/env.sh",
                "inner_image": "registry.example/osw21@sha256:deadbeef",
                "proxy": "http://proxy.example:3128", "volume_size": 64,
            },
        },
        "registry": {"auths": {"registry.h.pjlab.org.cn": {"auth": "xxx"}}},
    },
    "log": {"results_root": "/dev-results", "record": {"a11y_full": False}},
}


def with_paths(config: dict, *, deploy_root: str | None = None,
               results_root: str | None = None) -> dict:
    """深拷贝配置并替换 eval.deploy_root / log.results_root（避免共享嵌套 dict）。"""
    merged = copy.deepcopy(config)
    if deploy_root is not None:
        merged["eval"]["deploy_root"] = deploy_root
    if results_root is not None:
        merged["log"]["results_root"] = results_root
    return merged
