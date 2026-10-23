"""Stage-mode knobs reach the same worker session through config, spec and CLI."""

from __future__ import annotations

import pytest

from tandem.config import SessionConfig
from tandem_eval.__main__ import main
from tandem_eval.config_schema import validate
from tandem_eval.entry import build_session
from tandem_eval.rjob_spec import build_job_spec

from .rjob_fakes import CONFIG, with_paths


def test_stage_config_reaches_worker(tmp_path):
    config = with_paths(CONFIG, deploy_root=str(tmp_path / "deploy"), results_root=str(tmp_path))
    config["harness"]["execution"] = {"mode": "stage", "stage_max_actions": 12}
    assert validate(config) == []
    spec = build_job_spec(config=config, run_id="stage", repo_root=tmp_path,
                          spec_overrides={"benchmark": "mock"})
    assert spec["harness"]["mode"] == "stage"
    session = build_session(spec)
    assert session.config.execution_mode == "stage" and session.stage.max_actions == 12


def test_old_config_keeps_single_step_default(tmp_path):
    config = with_paths(CONFIG, deploy_root=str(tmp_path / "deploy"), results_root=str(tmp_path))
    spec = build_job_spec(config=config, run_id="step", repo_root=tmp_path, spec_overrides={})
    assert build_session(spec).stage is None


@pytest.mark.parametrize("execution", [{"mode": "invalid"}, {"stage_max_actions": False},
                                        {"stage_max_actions": 0}, {"stage_max_actions": 1.5}])
def test_invalid_execution_config_is_reported(execution):
    config = with_paths(CONFIG)
    config["harness"]["execution"] = execution
    assert any("harness.execution" in problem for problem in validate(config))


def test_session_rejects_invalid_execution_knobs():
    with pytest.raises(ValueError, match="execution_mode"):
        SessionConfig(execution_mode="unknown")
    with pytest.raises(ValueError, match="stage_max_actions"):
        SessionConfig(stage_max_actions=False)


def test_cli_execution_flags_reach_overrides(monkeypatch):
    from pathlib import Path

    captured = {}
    monkeypatch.setattr("tandem_eval.rjob.run_job", lambda **kwargs: (
        captured.update(kwargs) or {"status": "succeeded"}
    ))
    config_path = Path(__file__).resolve().parents[2] / "infra/config.example.json"
    assert main(["rjob", "run", "--run-id", "stage", "--config", str(config_path),
                 "--execution-mode", "stage", "--stage-max-actions", "12"]) == 0
    assert captured["spec_overrides"]["harness_config"] == {
        "execution_mode": "stage", "stage_max_actions": 12,
    }
