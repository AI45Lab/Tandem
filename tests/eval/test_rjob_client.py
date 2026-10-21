"""rjob 客户端：submit 参数构造 / 状态解析 / watch / 一站式 run_job 生命周期。"""

from __future__ import annotations

import json

import pytest

from tandem_eval.rjob import (
    RjobClient,
    RjobError,
    build_job_spec,
    build_submit_args,
    cleanup,
    fetch_artifacts,
    job_name,
    parse_status,
    run_job,
    watch,
)


class FakeRunner:
    """假命令执行器：rjob 按子命令路由到脚本化输出（列表逐个弹出，最后一个常驻）。
    fail_on 中的子命令返回退出码 1（模拟 rjob CLI 自身崩溃）。"""

    def __init__(self, script: dict | None = None, fail_on: set[str] | None = None):
        self.script = script or {}
        self.fail_on = fail_on or set()
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:1] == ["rjob"]:
            if argv[1] in self.fail_on:
                return 1, "TypeError: 'NoneType' object is not iterable"
            outputs = self.script.get(argv[1], [""])
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


CONFIG = {
    "deploy_root": "/dev-deploy",
    "results_root": "/dev-results",
    "rjob": {"charged_group": "evobox_proxy", "private_machine": True, "cpu": 4,
             "memory": 16384, "gpu": 0, "image": "reg.example/outer:1"},
    "mounts": [{"source": "gpfs://gpfs2/share", "target": "/mnt/share"}],
    "osw1_root": "/shared/osw1", "osw1_vm": "/shared/vm1.qcow2",
    "osw2_root": "/shared/osw2", "osw2_vm": "/shared/vm2.qcow2",
    "asset_root": "/shared/assets", "jev_endpoint": "http://10.1.1.1:8891",
    "kimi": {"base_url": "https://k.example/v1", "api_key": "sk-x", "model": "kimi-k3"},
    "registry": {"auths": {"registry.h.pjlab.org.cn": {"auth": "xxx"}}},
    "inner_image": "reg.example/inner:1",
}


def test_parse_status_variants():
    assert parse_status("Name: x\nStatus: Succeeded") == "succeeded"
    assert parse_status("状态: 成功") == "succeeded"
    assert parse_status("phase: Running") == "running"
    assert parse_status("waiting for scheduling") == "running"
    assert parse_status("Status: Failed") == "failed"
    assert parse_status("Deleted") == "deleted"
    assert parse_status("totally opaque") == "unknown"


def test_parse_status_real_captured_outputs():
    # 真机 Succeeded 输出：状态行优先命中，不被计数字典里的 'failed': 0 干扰
    assert parse_status(REAL_SUCCEEDED) == "succeeded"
    # 运行中任务同样带 'failed': 0 计数，必须解析为 running 而非 failed
    assert parse_status(REAL_RUNNING) == "running"
    # 只有计数字典、无状态行：剔除后无关键词 → unknown（继续轮询）
    assert parse_status("task t: {'active': 1, 'failed': 0, 'pending': 0}") == "unknown"


def test_submit_args_include_mount_and_worker_entrypoint():
    args = build_submit_args(config=CONFIG, run_id="r1")
    joined = " ".join(args)
    assert "--name=tandem-r1" in joined
    assert "--charged-group=evobox_proxy" in joined
    assert "--private-machine=group" in joined
    assert "--mount=gpfs://gpfs2/share:/mnt/share" in joined
    assert "--image=reg.example/outer:1" in joined
    assert joined.endswith("/dev-deploy/infra/worker.sh /dev-deploy/job_specs/r1.json")


def test_build_job_spec_uses_config_paths(tmp_path):
    config = dict(CONFIG, deploy_root=str(tmp_path / "deploy"),
                  results_root=str(tmp_path / "results"))
    spec = build_job_spec(config=config, run_id="r1",
                          repo_root=tmp_path, spec_overrides={"benchmark": "osworld1"})
    assert spec["output_root"] == str(tmp_path / "results" / "r1")
    assert spec["repo_root"] == str(tmp_path / "deploy")
    assert spec["benchmark"] == "osworld1"
    assert spec["env"]["root"] == CONFIG["osw1_root"]
    assert spec["secrets"]["jev_endpoint"] == CONFIG["jev_endpoint"]
    assert spec["secrets"]["kimi"]["api_key"] == "sk-x"
    assert spec["secrets"]["registry"]["auths"]
    written = json.loads((tmp_path / "deploy" / "job_specs" / "r1.json").read_text())
    assert written == spec


def test_watch_until_terminal_and_timeout():
    runner = FakeRunner({"get": ["running", "succeeded"]})
    client = RjobClient(runner)
    assert watch(client, "j", poll_seconds=0, sleep=lambda _: None) == "succeeded"
    always_running = FakeRunner({"get": ["running"]})
    with pytest.raises(TimeoutError):
        watch(RjobClient(always_running), "j", poll_seconds=0, timeout_seconds=0,
              sleep=lambda _: None)


def test_run_job_full_lifecycle_submits_watches_fetches_cleans(tmp_path):
    run_root = tmp_path / "rjob_logs" / "r1"  # 唯一落盘位置
    config = dict(CONFIG, results_root=str(tmp_path / "rjob_logs"),
                       deploy_root=str(tmp_path / "deploy"))
    script = {
        "submit": ["submitted"],
        "get": ["running", "succeeded"],
        "logs": ["log-line"],
        "stop": ["stopped"],
    }
    runner = FakeRunner(script)
    result = run_job(config=config,
                     repo_root=tmp_path, run_id="r1", spec_overrides={},
                     client=RjobClient(runner),
                     poll_seconds=0, sleep=lambda _: None, sync=False)
    assert result["status"] == "succeeded"
    assert result["run_root"] == str(run_root)
    submit_index = next(i for i, c in enumerate(runner.calls) if c[:2] == ["rjob", "submit"])
    delete_index = next(
        (i for i, c in enumerate(runner.calls[:submit_index]) if c[:2] == ["rjob", "delete"]), None)
    assert delete_index is not None, "提交前应先防御性 delete 同名残留"
    submit_call = runner.calls[submit_index]
    assert any(a.startswith("--mount=") for a in submit_call)
    # 平台日志写进 run 目录本身（唯一落盘位置）
    assert (run_root / "platform.tail.log").read_text() == "log-line"
    assert (run_root / "platform.status.txt").is_file()
    assert any(c[:2] == ["rjob", "stop"] for c in runner.calls)


def test_run_job_timeout_still_fetches_and_cleans(tmp_path):
    config = dict(CONFIG, results_root=str(tmp_path / "rjob_logs"),
                       deploy_root=str(tmp_path / "deploy"))
    runner = FakeRunner({"get": ["running"], "stop": ["stopped"],
                         "submit": ["ok"], "logs": ["log"]})
    result = run_job(config=config,
                     repo_root=tmp_path, run_id="r2", spec_overrides={},
                     client=RjobClient(runner),
                     poll_seconds=0, timeout_seconds=0, sleep=lambda _: None, sync=False)
    assert result["status"] == "timeout"
    assert (tmp_path / "rjob_logs" / "r2" / "platform.tail.log").is_file()
    assert any(c[:2] == ["rjob", "stop"] for c in runner.calls)


def test_client_raises_on_nonzero_exit():
    client = RjobClient(lambda argv: (1, "boom"))
    with pytest.raises(RjobError, match="退出码 1"):
        client.get("j")


def test_cleanup_delete_flag(tmp_path):
    runner = FakeRunner({"stop": ["ok"], "delete": ["ok"]})
    cleanup(RjobClient(runner), "j", delete=True)
    assert any(c[:2] == ["rjob", "delete"] for c in runner.calls)


def test_fetch_artifacts_writes_platform_logs_into_run_root(tmp_path):
    run_root = tmp_path / "run"
    (run_root / "worker").mkdir(parents=True)
    (run_root / "worker" / "dockerd.log").write_text("d", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")
    runner = FakeRunner({"get": ["status"], "logs": ["logs"]})
    out = fetch_artifacts(RjobClient(runner), "j", run_root)
    assert out == run_root
    assert (run_root / "platform.status.txt").read_text() == "status"
    assert (run_root / "platform.tail.log").read_text() == "logs"
    assert (run_root / "worker" / "dockerd.log").is_file()  # run 数据原样保留
    assert job_name("r1") == "tandem-r1"


def test_fetch_artifacts_tolerates_cli_crash(tmp_path):
    """rjob logs CLI 在日志未聚合时会崩（真机 2026-10-20）：错误写文件，run 数据照常。"""
    run_root = tmp_path / "run"
    (run_root / "worker").mkdir(parents=True)
    (run_root / "worker" / "entry.log").write_text("ok", encoding="utf-8")
    runner = FakeRunner({"get": [REAL_SUCCEEDED]}, fail_on={"logs"})
    out = fetch_artifacts(RjobClient(runner), "j", run_root)
    tail = (out / "platform.tail.log").read_text(encoding="utf-8")
    assert "[rjob logs 失败" in tail and "NoneType" in tail
    assert (out / "worker" / "entry.log").is_file()  # 结果镜像不受影响


def test_run_job_fetch_failure_never_skips_cleanup(tmp_path, monkeypatch):
    """平台日志补写失败不得跳过 cleanup（资源泄漏）；错误记入 result。"""
    config = dict(CONFIG, results_root=str(tmp_path / "rjob_logs"),
                       deploy_root=str(tmp_path / "deploy"))
    runner = FakeRunner({"get": [REAL_SUCCEEDED], "submit": ["ok"],
                         "logs": ["log"], "stop": ["stopped"]})

    def exploding_fetch(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tandem_eval.rjob.fetch_artifacts", exploding_fetch)
    result = run_job(config=config,
                     repo_root=tmp_path, run_id="r3", spec_overrides={},
                     client=RjobClient(runner),
                     poll_seconds=0, sleep=lambda _: None, sync=False)
    assert result["status"] == "succeeded"
    assert "fetch_error" in result
    assert any(c[:2] == ["rjob", "stop"] for c in runner.calls)  # cleanup 仍然执行


def test_env_section_seeds_setup_cache_for_osw1():
    from tandem_eval.rjob import _env_section

    section = _env_section("osworld1", CONFIG)
    assert section["root"] == "/shared/osw1"
    assert section["setup_cache_root"] == "/shared/osw1/cache"
    assert "setup_cache_root" not in _env_section("osworld2", CONFIG)


def test_rsync_never_deletes_job_specs():
    """job_specs 在部署副本里而非源仓库，必须排除出 rsync --delete（并发 run 互踩根因）。"""
    from tandem_eval.rjob import RSYNC_EXCLUDES

    assert "job_specs/" in RSYNC_EXCLUDES
