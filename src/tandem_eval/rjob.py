"""rjob 生命周期客户端（开发机侧编排；worker 侧见 entry.py）。

覆盖：sync_repo（rsync 干净源码到部署副本）→ build_job_spec（写入部署副本）→ submit
（--mount 挂载共享存储）→ watch（轮询 rjob get 至终态，超时 watchdog）→ fetch（平台日志
+ 结果目录归档到开发机）→ cleanup（rjob stop 收尾，可选 delete）。

双视角路径（与旧仓库 infra/envs 同构）：dev 档案是开发机挂载视角（rsync/取结果用），
rjob 档案是 worker 容器视角（submit 命令行与 job spec 内路径用），同一存储两个挂载点。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

TERMINAL_STATES = {"succeeded", "failed", "deleted"}
# job_specs/ 必须排除：--delete 会把"目标多出而源没有"的文件删掉，而每个 run 的 spec
# 写在部署副本里 —— 不排除的话，后一个 run 的同步会删掉前一个还在排队/运行的 spec
RSYNC_EXCLUDES = [".git/", ".venv/", "__pycache__/", ".pytest_cache/", ".ruff_cache/",
                  "rjob_logs/", "job_specs/"]


class RjobError(RuntimeError):
    pass


class RjobClient:
    """rjob CLI 薄封装；command_runner 可注入（测试），默认 subprocess。"""

    def __init__(self, command_runner=None):
        self._run = command_runner or _subprocess_run

    def _rjob(self, *args: str) -> str:
        code, stdout = self._run(["rjob", *args])
        if code != 0:
            raise RjobError(f"rjob {' '.join(args)} 退出码 {code}:\n{stdout[-2000:]}")
        return stdout

    def submit(self, build_args: list[str]) -> str:
        return self._rjob("submit", *build_args)

    def get(self, name: str) -> str:
        return self._rjob("get", name)

    def logs(self, name: str, *, tail_lines: int = 500) -> str:
        return self._rjob("logs", "job", name, "-n", str(tail_lines))

    def stop(self, name: str) -> str:
        return self._rjob("stop", name)

    def delete(self, name: str) -> str:
        return self._rjob("delete", name)


def _subprocess_run(argv: list[str]) -> tuple[int, str]:
    import os

    env = {key: value for key, value in os.environ.items() if key != "KUBEBRAIN_QUOTA_GROUP"}
    result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=600)
    return result.returncode, (result.stdout + result.stderr)


_STATUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("deleted", re.compile(r"(?i)\bdeleted\b|已删除")),
    ("succeeded", re.compile(r"(?i)\b(succeeded|succeed)\b|成功")),
    ("failed", re.compile(r"(?i)\b(failed|error)\b|失败")),
    (
        "running",
        re.compile(r"(?i)\b(running|terminating|pending|creating|waiting|starting|inqueue)\b|运行中|等待"),
    ),
]
# rjob get 的任务计数字典（{'active': 0, 'failed': 0, ...}）含状态词字样，须先剔除再关键词匹配
_COUNT_DICT_RE = re.compile(r"['\"]\w+['\"]\s*:\s*\d+")
# 首选：状态行本体，如 "rjob tandem-x: Succeeded" / "replica tandem-x-abc: SUCCEED"
_STATUS_LINE_RE = re.compile(r"(?i)\b(?:rjob|replica)\s+\S+:\s*([a-z_]+)")


def parse_status(get_output: str) -> str:
    """解析 rjob get 输出；优先取状态行，剔除计数字典后做关键词兜底；不识别返回 unknown。"""
    line = _STATUS_LINE_RE.search(get_output)
    if line:
        word = line.group(1).lower()
        for status, pattern in _STATUS_PATTERNS:
            if pattern.search(word):
                return status
        return "unknown"
    cleaned = _COUNT_DICT_RE.sub(" ", get_output)
    for status, pattern in _STATUS_PATTERNS:
        if pattern.search(cleaned):
            return status
    return "unknown"


REQUIRED_CONFIG_KEYS = (
    "repo_root", "deploy_root", "results_root", "mounts", "rjob", "inner_image",
    "osw1_root", "osw1_vm", "osw2_root", "osw2_vm", "asset_root",
    "kimi", "jev_endpoint", "registry",
)


def load_config(path: str | Path) -> dict:
    """加载唯一配置文件（infra/config.json）：全绝对路径，开发机与 worker 内一致。"""
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing:
        raise RjobError(f"配置缺少必填键: {missing}（见 infra/config.json）")
    if not config["rjob"].get("image"):
        raise RjobError("配置 rjob.image 不能为空")
    return config


def sync_repo(repo_root: Path, deploy_root_dev: Path) -> None:
    deploy_root_dev.mkdir(parents=True, exist_ok=True)
    argv = ["rsync", "-a", "--delete"]
    for exclude in RSYNC_EXCLUDES:
        argv += ["--exclude", exclude]
    argv += [str(repo_root) + "/", str(deploy_root_dev) + "/"]
    code, stdout = _subprocess_run(argv)
    if code != 0:
        raise RjobError(f"rsync 失败:\n{stdout[-2000:]}")


def job_name(run_id: str) -> str:
    return f"tandem-{run_id}"


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


def _git_describe(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "describe", "--always", "--dirty"], cwd=repo_root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


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


def watch(client: RjobClient, name: str, *, poll_seconds: float = 60,
          timeout_seconds: float | None = None, sleep=time.sleep) -> str:
    """轮询至终态；超时抛 TimeoutError（调用方决定是否 stop 收尾）。"""
    started = time.monotonic()
    while True:
        status = parse_status(client.get(name))
        if status in TERMINAL_STATES:
            return status
        if timeout_seconds is not None and time.monotonic() - started >= timeout_seconds:
            raise TimeoutError(f"rjob {name} 超过 {timeout_seconds}s 仍未终态（当前 {status}）")
        sleep(poll_seconds)


def fetch_artifacts(client: RjobClient, name: str, run_root: Path,
                    *, tail_lines: int = 500) -> Path:
    """把平台状态/日志写进 run 目录本身（唯一落盘位置 = rjob_logs/<run_id>）。

    平台命令失败不致命（rjob logs 在日志未聚合时 CLI 自身会崩，见 DEVIATIONS #19）：
    错误文本写入对应文件后继续。
    """
    run_root.mkdir(parents=True, exist_ok=True)
    try:
        (run_root / "platform.status.txt").write_text(client.get(name), encoding="utf-8")
    except RjobError as error:
        (run_root / "platform.status.txt").write_text(f"[rjob get 失败]\n{error}", encoding="utf-8")
    try:
        (run_root / "platform.tail.log").write_text(
            client.logs(name, tail_lines=tail_lines), encoding="utf-8"
        )
    except RjobError as error:
        (run_root / "platform.tail.log").write_text(f"[rjob logs 失败，日志可能未聚合]\n{error}",
                                                    encoding="utf-8")
    return run_root


def cleanup(client: RjobClient, name: str, *, delete: bool = False) -> None:
    """任务结束后收尾：stop 释放资源（幂等）；delete 永久清理（高危，默认关）。"""
    try:
        client.stop(name)
    except RjobError:
        pass  # 已终态时 stop 可能报错，忽略
    if delete:
        try:
            client.delete(name)
        except RjobError:
            pass


def run_job(*, config: dict, repo_root: Path, run_id: str,
            spec_overrides: dict | None = None, client: RjobClient | None = None,
            poll_seconds: float = 60, timeout_seconds: float | None = None,
            keep: bool = False, delete: bool = False, sleep=time.sleep, sync: bool = True) -> dict:
    """一站式：sync → spec → submit → watch → fetch → cleanup。

    唯一落盘位置 = results_root/<run_id>（= tandem/rjob_logs/<run_id>）：
    worker 直接写 run 目录（adpc 挂载），平台日志由 fetch 补写进同一目录。
    """
    spec_overrides = spec_overrides or {}
    client = client or RjobClient()
    if sync:
        sync_repo(repo_root, Path(config["deploy_root"]))
    build_job_spec(config=config, run_id=run_id,
                   repo_root=repo_root, spec_overrides=spec_overrides)
    name = job_name(run_id)
    try:
        client.delete(name)  # 防御性清理同名残留（旧脚本同款；不存在时忽略）
    except RjobError:
        pass
    client.submit(build_submit_args(config=config, run_id=run_id))
    result = {"job": name, "run_id": run_id}
    try:
        result["status"] = watch(client, name, poll_seconds=poll_seconds,
                                 timeout_seconds=timeout_seconds, sleep=sleep)
    except TimeoutError as error:
        result["status"], result["error"] = "timeout", str(error)
    finally:
        # fetch 失败不得阻断 cleanup（否则资源泄漏）；错误记入 result 继续
        run_root = Path(config["results_root"]) / run_id
        result["run_root"] = str(run_root)
        try:
            fetch_artifacts(client, name, run_root)
        except Exception as error:  # 平台日志补写尽力而为：run 数据正本已在该目录
            result["fetch_error"] = f"{type(error).__name__}: {error}"
        if not keep:
            cleanup(client, name, delete=delete)
    return result
