"""recorder：结果目录契约执行 + 脱敏 + run 级汇总。"""

from __future__ import annotations

import json

from tandem_eval.recorder import (
    EpisodeRecorder,
    write_code_version,
    write_heartbeat,
    write_summary,
)


def test_episode_recorder_writes_contract_files(tmp_path):
    recorder = EpisodeRecorder(tmp_path / "ep" / "chrome-t1",
                               {"id": "t1", "instruction": "做", "domain": "chrome"})
    recorder.record_llm_call(
        role="plan_step",
        request={"messages": [{"role": "system", "content": "x"}]},
        response={"choices": [{"message": {"content": "Bearer sk-SECRET"}}]},
    )
    recorder.event({"route": "planner", "plan": {"done": False}})
    recorder.screenshot(0, b"png")
    recorder.a11y(0, "<a><b/></a>")
    episode = recorder.finalize(
        stop_reason="done", outputs=[{"vm_path": "/home/user/o.xlsx", "exported": True}],
        raw_score={"score": 1}, score=1.0, status="scored", steps=3,
    )
    base = tmp_path / "ep" / "chrome-t1"
    for name in ("task.json", "traj.jsonl", "events.jsonl", "llm_calls.jsonl",
                 "artifacts.json", "evaluation.json", "result.txt", "episode.json",
                 "timing.json", "a11y_digests.jsonl"):
        assert (base / name).is_file(), f"缺少 {name}"
    assert (base / "screenshots" / "step_00.png").read_bytes() == b"png"
    assert (base / "result.txt").read_text().strip() == "1.0"
    assert episode["status"] == "scored" and episode["steps"] == 3


def test_llm_calls_redacts_bearer_secrets(tmp_path):
    recorder = EpisodeRecorder(tmp_path / "ep", {"id": "t1"})
    recorder.record_llm_call(
        role="verify", request={"payload": {"model": "kimi"}},
        response={"content": "Authorization: Bearer sk-abc123 done"},
    )
    line = json.loads((tmp_path / "ep" / "llm_calls.jsonl").read_text().splitlines()[0])
    assert "sk-abc123" not in json.dumps(line)
    assert "Bearer [REDACTED]" in line["response"]["content"]


def test_failed_unscored_writes_no_score_files(tmp_path):
    recorder = EpisodeRecorder(tmp_path / "ep", {"id": "t1"})
    recorder.finalize(stop_reason="exception", outputs=[], raw_score=None, score=None,
                      status="failed_unscored", exception=RuntimeError("vm down"))
    assert not (tmp_path / "ep" / "result.txt").exists()
    episode = json.loads((tmp_path / "ep" / "episode.json").read_text())
    assert episode["status"] == "failed_unscored"
    assert episode["exception_type"] == "RuntimeError"


def test_summary_aggregates_and_excludes_unscored(tmp_path):
    write_summary(tmp_path, [
        {"task_id": "a", "score": 1.0, "status": "scored"},
        {"task_id": "b", "score": 0.0, "status": "scored"},
        {"task_id": "c", "score": None, "status": "failed_unscored"},
    ], {"run_id": "r1", "benchmark": "mock", "harness": {"name": "tandem"}})
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["total"] == 3 and summary["scored"] == 2
    assert summary["failed_unscored"] == 1
    assert summary["average_score"] == 0.5


def test_heartbeat_and_code_version(tmp_path):
    write_heartbeat(tmp_path, done=1, total=3, current="task-2")
    assert json.loads((tmp_path / "heartbeat.json").read_text())["current_task"] == "task-2"
    write_code_version(tmp_path, {"git_describe": "abc123", "resources": {"schema_version": "v1"}})
    info = json.loads((tmp_path / "code_version.json").read_text())
    assert info["git_describe"] == "abc123" and info["protocol_version"] == "0.1"
