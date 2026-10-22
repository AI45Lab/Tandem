"""job spec 与 submit 参数组装（开发机侧）。

把唯一配置文件 `infra/config.json` + 本次 run 的 overrides，翻译成两样东西：

- **job spec**：写进部署副本 `job_specs/<run_id>.json`，worker 侧 `entry` 按它启动
  （环境段 / 凭据段 / 快模型中转段 / harness 段 / 预算 / 镜像与 git describe）；
- **submit 参数**：`rjob submit` 的命令行（含 --mount 挂载共享存储）。

角色与厂商解耦：配置里 `harness.slow_model.apis` / `harness.fast_model.apis` 是
**命名 API 登记表**，本模块按名字挑出本次 run 用的大脑与小脑（命令行可覆盖），
再把"凭据 + 地址"拆进 secrets 段、"行为旋钮"拆进 harness_config 段。

路径两侧一致、不做视角换算：spec 里的路径都是 worker 容器内可见的挂载点。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config_schema import select_api


def job_name(run_id: str) -> str:
    return f"tandem-{run_id}"


def _git_describe(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "describe", "--always", "--dirty"], cwd=repo_root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _env_section(benchmark: str, config: dict) -> dict:
    benchmarks = config["eval"]["benchmarks"]
    shared_env = config["eval"]["shared_env"]
    if benchmark == "osworld1":
        section = benchmarks["osworld1"]
        return {"root": section["root"], "vm": section["vm"], "shared_env": shared_env,
                "setup_cache_root": str(Path(section["root"]) / "cache"),
                "startup_wait_seconds": 30}
    if benchmark == "osworld2":
        section = benchmarks["osworld2"]
        return {"root": section["root"], "vm": section["vm"], "shared_env": shared_env,
                "asset_root": section["asset_root"], "startup_wait_seconds": 30}
    if benchmark == "osworld21":
        # OSW2.1 自带独立 runtime/VM/资产/env.sh，不与旧环境混用
        section = benchmarks["osworld21"]
        return {"root": section["root"], "vm": section["vm"],
                "asset_root": section["asset_root"], "shared_env": section["shared_env"],
                "proxy": section.get("proxy", ""), "volume_size": section.get("volume_size"),
                "startup_wait_seconds": 30}
    return {}


def _secrets_section(benchmark: str, config: dict, slow_api: dict, fast_api: dict) -> dict:
    """凭据段：慢模型三件套 + 快模型地址 + registry auth（落盘时整体脱敏）。"""
    if benchmark not in {"osworld1", "osworld2"}:
        return {}
    return {
        "slow_model": {key: slow_api[key] for key in ("base_url", "api_key", "model")},
        # 快模型部署在闲时 GPU，ip/端口随重新部署变化：endpoint 为空时由 worker
        # 从 endpoint_file（部署后写入的 {"base_url": ...}）自动发现
        "fast_model": {
            "endpoint": fast_api.get("endpoint", ""),
            "endpoint_file": fast_api.get("endpoint_file", ""),
        },
        "registry": config["eval"].get("registry"),
    }


def _harness_config_section(config: dict, slow_api: dict, fast_api: dict) -> dict:
    """行为旋钮段：SessionConfig 的字段（与 harness 侧 dataclass 一一对应）。"""
    route = config["harness"]["route"]
    return {
        "route_policy": route.get("policy", "auto"),
        "allow_cli": bool(route.get("allow_cli", True)),
        "cli_timeout_seconds": int(route.get("cli_timeout_seconds", 90)),
        "slow_max_tokens": int(slow_api.get("max_tokens", 16384)),
        "slow_timeout_seconds": float(slow_api.get("timeout_seconds", 120)),
        "slow_reasoning_effort": slow_api.get("reasoning_effort", "low"),
        "slow_direct_api": bool(slow_api.get("direct_api", False)),
        "fast_backend": fast_api.get("backend", "jev"),
        "fast_timeout_seconds": float(fast_api.get("timeout_seconds", 300)),
    }


def _budget_section(config: dict) -> dict:
    budget = config["harness"]["budget"]
    return {
        "max_steps": int(budget["max_steps"]),
        "max_wall_seconds": float(budget["max_wall_seconds"]),
    }


def _record_section(config: dict) -> dict:
    return {"a11y_full": bool(config["log"]["record"].get("a11y_full", False))}


def _image_stage_section(config: dict) -> dict:
    """截图中转目录（服务端要求 image_path 在其宿主机可读；截图本体在 adpc，
    排序前由 harness 暂存到 evobox 并传规范路径）。"""
    stage = config["harness"]["fast_model"].get("image_stage") or {}
    write_root = stage.get("write")
    read_root = stage.get("read")
    if write_root and read_root:
        return {"write": write_root, "read": read_root}
    return {}


def build_job_spec(*, config: dict, run_id: str, repo_root: Path,
                   spec_overrides: dict) -> dict:
    """组装 job spec 并写入部署副本 job_specs/<run_id>.json（路径两侧一致，无视角换算）。

    本次用哪套大脑/小脑由 overrides["models"] 决定（缺省取配置里的 default）；
    选中的 API 名字会记进 harness.models，run 目录里据此还原"谁在跑"。
    """
    benchmark = spec_overrides.get("benchmark", "mock")
    overrides = dict(spec_overrides)
    requested = dict(overrides.pop("models", {}) or {})
    slow_name, slow_api = select_api(config, "slow_model", requested.get("slow"))
    fast_name, fast_api = select_api(config, "fast_model", requested.get("fast"))

    inner_image = config["eval"]["inner_image"]
    if benchmark == "osworld21":
        # OSW2.1 用发布清单固定的运行镜像（digest），不覆盖 latest，也不复用 OSW2 的镜像
        inner_image = config["eval"]["benchmarks"]["osworld21"].get("inner_image", "")
        if not inner_image:
            raise ValueError(
                "eval.benchmarks.osworld21.inner_image 必须填发布清单固定的运行镜像"
                "（<repo>@sha256:…；见 osworld21/runtime/benchmark_releases/osworld-v2.1.json）"
            )

    harness_config = _harness_config_section(config, slow_api, fast_api)
    harness_config.update(overrides.pop("harness_config", {}) or {})
    budget = _budget_section(config)
    budget.update(overrides.pop("budget", {}) or {})

    spec = {
        "run_id": run_id,
        "repo_root": config["eval"]["deploy_root"],
        "output_root": str(Path(config["log"]["results_root"]) / run_id),
        "benchmark": benchmark,
        "env": _env_section(benchmark, config),
        "secrets": _secrets_section(benchmark, config, slow_api, fast_api),
        "image_stage": _image_stage_section(config),
        "harness": {
            "name": "tandem",
            "mode": "planner_led",
            "models": {"slow": slow_name, "fast": fast_name},
        },
        "harness_config": harness_config,
        "budget": budget,
        "record": _record_section(config),
        "code": {
            "git_describe": _git_describe(repo_root),
            "images": {
                "outer": config["eval"]["rjob"]["image"],
                "inner": inner_image,
            },
        },
        **overrides,
    }
    spec_dir = Path(config["eval"]["deploy_root"]) / "job_specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{run_id}.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return spec


def build_submit_args(*, config: dict, run_id: str) -> list[str]:
    rjob_conf = config["eval"]["rjob"]
    args = [
        f"--name={job_name(run_id)}",
        f"--charged-group={rjob_conf.get('charged_group', 'evobox_proxy')}",
    ]
    if rjob_conf.get("private_machine", True):
        args.append("--private-machine=group")
    args += [
        f"--cpu={rjob_conf.get('cpu', 4)}",
        f"--memory={rjob_conf.get('memory', 16384)}",
        f"--gpu={rjob_conf.get('gpu', 0)}",
        f"--image={rjob_conf['image']}",
        "-r", "never",
        "--auto-restart", "false",
        "--privileged", "true",
    ]
    for mount in config["eval"].get("mounts", []):
        args.append(f"--mount={mount['source']}:{mount['target']}")
    deploy = config["eval"]["deploy_root"]
    args += ["--", "bash", f"{deploy}/infra/worker.sh",
             f"{deploy}/job_specs/{run_id}.json"]
    return args
