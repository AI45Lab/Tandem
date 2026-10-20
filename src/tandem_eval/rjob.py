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
import shutil
import subprocess
import time
from pathlib import Path

TERMINAL_STATES = {"succeeded", "failed", "deleted"}
RSYNC_EXCLUDES = [".git/", ".venv/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "rjob_logs/"]


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


def _expand_nested(node, snapshot: dict):
    if isinstance(node, str):
        out = node
        for name, ref in snapshot.items():
            out = out.replace("{" + name + "}", str(ref))
        return out
    if isinstance(node, dict):
        return {key: _expand_nested(value, snapshot) for key, value in node.items()}
    if isinstance(node, list):
        return [_expand_nested(value, snapshot) for value in node]
    return node


def expand_profile(raw: dict) -> dict:
    """迭代展开 {placeholder}：顶层标量构成命名空间，嵌套 dict/list 用同一命名空间展开。"""
    expanded = dict(raw)
    for _ in range(5):
        snapshot = {k: v for k, v in expanded.items() if isinstance(v, (str, int, float))}
        changed = False
        for key, value in list(expanded.items()):
            resolved = _expand_nested(value, snapshot)
            if resolved != value:
                expanded[key], changed = resolved, True
        if not changed:
            break
    return expanded


def load_profile(path: str | Path) -> dict:
    return expand_profile(json.loads(Path(path).read_text(encoding="utf-8")))


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


def _env_section(benchmark: str, profile_rjob: dict) -> dict:
    if benchmark == "osworld1":
        return {"root": profile_rjob["osw1_root"], "vm": profile_rjob["osw1_vm"],
                "startup_wait_seconds": 30}
    if benchmark == "osworld2":
        return {"root": profile_rjob["osw2_root"], "vm": profile_rjob["osw2_vm"],
                "asset_root": profile_rjob["asset_root"], "startup_wait_seconds": 30}
    return {}


def _secrets_section(benchmark: str, profile_rjob: dict) -> dict:
    if benchmark not in {"osworld1", "osworld2"}:
        return {}
    return {
        "kimi_config": profile_rjob["kimi_config"],
        "kimi_model": profile_rjob.get("kimi_model", "kimi-k3"),
        "jev_endpoint": profile_rjob["jev_endpoint"],
        "registry_secret": profile_rjob.get("registry_secret"),
    }


def build_job_spec(*, profile_dev: dict, profile_rjob: dict, run_id: str,
                   repo_root: Path, spec_overrides: dict) -> dict:
    """组装 job spec（worker 视角路径）并写入部署副本（dev 视角）job_specs/<run_id>.json。"""
    benchmark = spec_overrides.get("benchmark", "mock")
    spec = {
        "run_id": run_id,
        "repo_root": profile_rjob["deploy_root"],
        "output_root": str(Path(profile_rjob["results_root"]) / run_id),
        "benchmark": benchmark,
        "env": _env_section(benchmark, profile_rjob),
        "secrets": _secrets_section(benchmark, profile_rjob),
        "harness": {"name": "tandem", "mode": "planner_led"},
        "budget": {"max_steps": 15, "max_wall_seconds": 900},
        "record": {"a11y_full": False},
        "code": {
            "git_describe": _git_describe(repo_root),
            "images": {
                "outer": profile_dev.get("rjob", {}).get("image"),
                "inner": profile_rjob.get("inner_image"),
            },
        },
        **spec_overrides,
    }
    spec_dir = Path(profile_dev["deploy_root"]) / "job_specs"
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


def build_submit_args(*, profile_dev: dict, profile_rjob: dict, run_id: str) -> list[str]:
    rjob_conf = profile_dev.get("rjob", {})
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
    for mount in profile_dev.get("mounts", []):
        args.append(f"--mount={mount['source']}:{mount['target']}")
    deploy_rjob = profile_rjob["deploy_root"]
    args += ["--", "bash", f"{deploy_rjob}/infra/worker.sh",
             f"{deploy_rjob}/job_specs/{run_id}.json"]
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


def fetch_artifacts(client: RjobClient, name: str, run_root_dev: Path,
                    out_dir: Path, *, tail_lines: int = 500) -> Path:
    """平台状态/日志 + 结果目录（开发机视角）归档到 out_dir/<job>/。

    平台命令失败不致命（rjob logs 在日志未聚合时 CLI 自身会崩，见 DEVIATIONS #19）：
    错误文本写入对应归档文件后继续，结果目录镜像不受影响。
    """
    out = out_dir / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    try:
        (out / "platform.status.txt").write_text(client.get(name), encoding="utf-8")
    except RjobError as error:
        (out / "platform.status.txt").write_text(f"[rjob get 失败]\n{error}", encoding="utf-8")
    try:
        (out / "platform.tail.log").write_text(
            client.logs(name, tail_lines=tail_lines), encoding="utf-8"
        )
    except RjobError as error:
        (out / "platform.tail.log").write_text(f"[rjob logs 失败，日志可能未聚合]\n{error}",
                                               encoding="utf-8")
    if run_root_dev.is_dir():
        # 完整镜像 run 目录（结果/截图/worker 日志全部本地化，rjob_logs 即自包含副本）
        shutil.copytree(run_root_dev, out, dirs_exist_ok=True)
    return out


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


def run_job(*, profile_dev: dict, profile_rjob: dict, repo_root: Path, run_id: str,
            spec_overrides: dict | None = None, client: RjobClient | None = None,
            out_dir: Path, poll_seconds: float = 60, timeout_seconds: float | None = None,
            keep: bool = False, delete: bool = False, sleep=time.sleep, sync: bool = True) -> dict:
    """一站式：sync → spec → submit → watch → fetch → cleanup。"""
    spec_overrides = spec_overrides or {}
    client = client or RjobClient()
    if sync:
        sync_repo(repo_root, Path(profile_dev["deploy_root"]))
    build_job_spec(profile_dev=profile_dev, profile_rjob=profile_rjob, run_id=run_id,
                   repo_root=repo_root, spec_overrides=spec_overrides)
    name = job_name(run_id)
    client.submit(build_submit_args(profile_dev=profile_dev, profile_rjob=profile_rjob,
                                    run_id=run_id))
    result = {"job": name, "run_id": run_id}
    try:
        result["status"] = watch(client, name, poll_seconds=poll_seconds,
                                 timeout_seconds=timeout_seconds, sleep=sleep)
    except TimeoutError as error:
        result["status"], result["error"] = "timeout", str(error)
    finally:
        # fetch 失败不得阻断 cleanup（否则资源泄漏）；错误记入 result 继续
        run_root_dev = Path(profile_dev["results_root"]) / run_id
        try:
            result["archive"] = str(fetch_artifacts(client, name, run_root_dev, out_dir))
        except Exception as error:  # 归档尽力而为：结果正本仍在 results_root
            result["archive_error"] = f"{type(error).__name__}: {error}"
        if not keep:
            cleanup(client, name, delete=delete)
    return result
