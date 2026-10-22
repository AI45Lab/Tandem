"""job spec 与 submit 参数组装（开发机侧）。

把唯一配置文件 `infra/config.json` + 本次 run 的 overrides，翻译成两样东西：

- **job spec**：写进部署副本 `job_specs/<run_id>.json`，worker 侧 `entry` 按它启动
  （环境段 / 凭据段 / JEV 中转段 / harness 段 / 预算 / 镜像与 git describe）；
- **submit 参数**：`rjob submit` 的命令行（含 --mount 挂载共享存储）。

路径两侧一致、不做视角换算：spec 里的路径都是 worker 容器内可见的挂载点。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


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
    if benchmark == "osworld1":
        return {"root": config["osw1_root"], "vm": config["osw1_vm"],
                "setup_cache_root": str(Path(config["osw1_root"]) / "cache"),
                "startup_wait_seconds": 30}
    if benchmark == "osworld2":
        return {"root": config["osw2_root"], "vm": config["osw2_vm"],
                "asset_root": config["asset_root"], "startup_wait_seconds": 30}
    return {}


def _secrets_section(benchmark: str, config: dict) -> dict:
    if benchmark not in {"osworld1", "osworld2"}:
        return {}
    section = {
        "kimi": dict(config["kimi"]),
        # jev 部署在闲时 GPU，ip/端口随重新部署变化：endpoint 为空时由 worker
        # 从 jev_endpoint_file（部署后写入的 {"base_url": ...}）自动发现
        "jev_endpoint": config.get("jev_endpoint", ""),
        "registry": config.get("registry"),
    }
    if config.get("jev_endpoint_file"):
        section["jev_endpoint_file"] = config["jev_endpoint_file"]
    if config.get("kev_endpoint"):
        section["kev_endpoint"] = config["kev_endpoint"]
    if config.get("kev_endpoint_file"):
        section["kev_endpoint_file"] = config["kev_endpoint_file"]
    return section


def _jev_section(config: dict) -> dict:
    """JEV 截图中转目录（服务端要求 image_path 在其宿主机可读；截图本体在 adpc，
    排序前由 harness 暂存到 evobox 并传规范路径）。"""
    write_root = config.get("jev_image_stage_write")
    read_root = config.get("jev_image_stage_read")
    if write_root and read_root:
        return {"image_stage_write": write_root, "image_stage_read": read_root}
    return {}


def build_job_spec(*, config: dict, run_id: str, repo_root: Path,
                   spec_overrides: dict) -> dict:
    """组装 job spec 并写入部署副本 job_specs/<run_id>.json（路径两侧一致，无视角换算）。"""
    benchmark = spec_overrides.get("benchmark", "mock")
    spec = {
        "run_id": run_id,
        "repo_root": config["deploy_root"],
        "output_root": str(Path(config["results_root"]) / run_id),
        "benchmark": benchmark,
        "env": _env_section(benchmark, config),
        "secrets": _secrets_section(benchmark, config),
        "jev": _jev_section(config),
        "harness": {"name": "tandem", "mode": "planner_led"},
        "budget": {"max_steps": 15, "max_wall_seconds": 900},
        "record": {"a11y_full": False},
        "code": {
            "git_describe": _git_describe(repo_root),
            "images": {
                "outer": config["rjob"]["image"],
                "inner": config["inner_image"],
            },
        },
        **spec_overrides,
    }
    spec_dir = Path(config["deploy_root"]) / "job_specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{run_id}.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return spec


def build_submit_args(*, config: dict, run_id: str) -> list[str]:
    rjob_conf = config["rjob"]
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
    for mount in config.get("mounts", []):
        args.append(f"--mount={mount['source']}:{mount['target']}")
    deploy = config["deploy_root"]
    args += ["--", "bash", f"{deploy}/infra/worker.sh",
             f"{deploy}/job_specs/{run_id}.json"]
    return args
