"""Development fixtures, not benchmark evidence: real session/candidate/compiler paths."""

from __future__ import annotations

from copy import deepcopy

import pytest

from tandem.config import SessionConfig
from tandem.protocol.models import CliAction, FailAction, FinishAction, GuiAction
from tandem.session import TandemSession
from tandem.stage_planner import valid_stage

from .conftest import (
    FixedSelector,
    ScriptedPlanner,
    ScriptedVerifier,
    cli_receipt,
    gui_receipt,
    make_components,
    make_observation,
    valid_verifier_response,
)


def tree(*buttons, checked=False):
    return ('<application name="app" active="true">'
            + ''.join(f'<push_button name="{name}" screencoord="({x},100)" size="(80,24)"/>'
                      for name, x in buttons)
            + f'<check_box name="Enabled" checked="{str(checked).lower()}" '
              'screencoord="(10,200)" size="(80,24)"/></application>')


def milestone(name, result):
    return {"route": "gui", "current_goal": f"Open {name}", "expected_observation": result,
            "action_proposals": [{"operation": "click", "target_name": name,
                                  "target_role": "push_button"}],
            "checks": [{"target": {"name": result, "role": "push_button"},
                        "property": "visible", "expected": True}]}


def stage(*milestones):
    return {"done": False, "stage_goal": "Configure and save", "milestones": list(milestones)}


DONE = {"done": True, "task_status": "completed", "current_goal": "Original task complete"}


def session_for(plans, responses=(), **config):
    planner = ScriptedPlanner(list(plans))
    verifier, selector = ScriptedVerifier(list(responses)), FixedSelector()
    session = TandemSession(make_components(planner, verifier, selector),
                            config=SessionConfig(execution_mode="stage", **config))
    session.begin("Configure and save", [])
    return session, planner, verifier, selector


def test_two_actions_use_one_plan_and_fresh_target_ids_then_independent_terminal_check(tmp_path):
    session, planner, verifier, selector = session_for(
        [stage(milestone("Open", "Save"), milestone("Save", "Saved")), DONE],
        [valid_verifier_response(task_status="completed")],
    )
    first = session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    assert isinstance(first, GuiAction) and first.target_id == "a11y:t0:0"
    second = session.act(make_observation(tmp_path, 1, receipt=gui_receipt(),
                                          tree_xml=tree(("Save", 500))))
    assert isinstance(second, GuiAction) and second.target_id == "a11y:t1:0"
    assert second.parameters["x"] == 540  # Never reuse the old target or coordinates.
    assert len(planner.calls) == 1 and verifier.calls == [] and len(selector.calls) == 2
    terminal = session.act(make_observation(tmp_path, 2, receipt=gui_receipt(),
                                            tree_xml=tree(("Saved", 50))))
    assert isinstance(terminal, FinishAction)
    assert len(verifier.calls) == 1 and verifier.calls[0]["terminal_claim"] == DONE
    verified = [e["verification"] for e in session.events if e["route"] == "gui_verified"]
    assert [v["source"] for v in verified] == ["rule_a11y", "rule_a11y"]
    assert all(v["task_status"] == "incomplete" for v in verified)
    assert len([e for e in session.events if e["route"] == "planner"]) == 2


def test_unbound_target_replans_without_executing_a_near_match(tmp_path):
    session, planner, _, selector = session_for([
        stage(milestone("Missing", "Saved")), stage(milestone("Actual", "Saved")),
    ])
    action = session.act(make_observation(tmp_path, 0, tree_xml=tree(("Actual", 10))))
    assert isinstance(action, GuiAction)
    assert len(planner.calls) == 2 and len(selector.calls) == 1
    assert any(e.get("reason") == "target_unbound_or_ambiguous" for e in session.events)


def test_duplicate_names_require_parent_disambiguation(tmp_path):
    session, _, _, selector = session_for([stage(milestone("Open", "Saved"))] * 3)
    result = session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10), ("Open", 200))))
    assert isinstance(result, FailAction) and result.reason == "no_action_limit"
    assert selector.calls == []


def test_failed_cli_receipt_skips_model_verify_and_repairs_remaining_stage(tmp_path):
    cli = {"route": "cli", "command": "false", "current_goal": "Read public file",
           "expected_observation": "Actual file contents", "checks": []}
    session, planner, verifier, _ = session_for([stage(cli), stage(milestone("Open", "Saved"))])
    assert isinstance(session.act(make_observation(tmp_path, 0)), CliAction)
    result = session.act(make_observation(tmp_path, 1, receipt=cli_receipt(returncode=1),
                                        tree_xml=tree(("Open", 10))))
    assert isinstance(result, GuiAction) and len(planner.calls) == 2
    assert verifier.calls == []
    assert next(e for e in session.events if e["route"] == "cli_verified")["verification"]["source"] == (
        "rule_receipt"
    )


def test_exit_zero_and_printed_success_are_not_rule_proof(tmp_path):
    cli = {"route": "cli", "command": "echo success", "current_goal": "Inspect file",
           "expected_observation": "Contents satisfy the task", "checks": []}
    session, _, verifier, _ = session_for([stage(cli), DONE], [
        valid_verifier_response(), valid_verifier_response(task_status="completed"),
    ])
    session.act(make_observation(tmp_path, 0))
    session.act(make_observation(tmp_path, 1, receipt=cli_receipt(stdout="success")))
    assert verifier.calls[0]["execution_result"]["stdout"] == "success"
    assert len(verifier.calls) == 2  # Action + independent terminal verification.


def test_unknown_a11y_uses_model_not_automatic_success(tmp_path):
    session, _, verifier, _ = session_for([stage(milestone("Open", "Saved")), DONE], [
        valid_verifier_response(), valid_verifier_response(task_status="completed"),
    ])
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    session.act(make_observation(tmp_path, 1, receipt=gui_receipt(), tree_xml=None))
    assert len(verifier.calls) == 2
    verification = next(e for e in session.events if e["route"] == "gui_verified")["verification"]
    assert verification["source"] == "model"


def test_preexisting_condition_does_not_prove_action_succeeded(tmp_path):
    value = tree(("Open", 10), ("Saved", 100))
    session, _, verifier, _ = session_for([stage(milestone("Open", "Saved")), DONE], [
        valid_verifier_response(), valid_verifier_response(task_status="completed"),
    ])
    session.act(make_observation(tmp_path, 0, tree_xml=value))
    session.act(make_observation(tmp_path, 1, receipt=gui_receipt(), tree_xml=value))
    assert len(verifier.calls) == 2


def test_stage_action_limit_requests_replan_before_next_action(tmp_path):
    session, planner, _, _ = session_for([
        stage(milestone("Open", "Save"), milestone("Save", "Saved")),
        stage(milestone("Save", "Saved")),
    ], stage_max_actions=1)
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    session.act(make_observation(tmp_path, 1, receipt=gui_receipt(), tree_xml=tree(("Save", 200))))
    assert len(planner.calls) == 2
    assert any(e.get("reason") == "stage_action_limit" for e in session.events)
    assert planner.calls[1]["recent_tail"][0]["verified_milestones"] == ["Open Open"]


def test_begin_discards_prior_stage(tmp_path):
    session, planner, _, _ = session_for([stage(milestone("Open", "Save"))] * 2)
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    session.begin("New task", [])
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    assert len(planner.calls) == 2 and session.stage.actions == 0


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(done=0),
    lambda p: p.update(milestones=[]),
    lambda p: p["milestones"][0].update(route="shell"),
    lambda p: p["milestones"][0]["action_proposals"][0].update(operation="invented"),
    lambda p: p["milestones"][0]["checks"][0].update(expected=1),
])
def test_invalid_stage_response_is_rejected(mutate):
    value = deepcopy(stage(milestone("Open", "Save")))
    assert valid_stage(value)
    mutate(value)
    assert not valid_stage(value)


def test_cli_policy_is_enforced_in_plan_validation():
    value = stage({"route": "cli", "command": "ls", "current_goal": "Inspect",
                   "expected_observation": "Files", "checks": []})
    assert valid_stage(value)
    assert not valid_stage(value, allow_cli=False)
    assert not valid_stage(value, route_policy="gui")
    assert not valid_stage(stage(milestone("Open", "Save")), route_policy="cli")


def test_component_factory_calls_stage_model_with_task_image_and_constraints(tmp_path):
    import json

    from tandem.components import build_default

    class Client:
        def json_request(self, messages, validator, *, role):
            assert role == "plan_stage"
            content = messages[1]["content"]
            context = json.loads(content[0]["text"])
            assert context["task"] == "Configure and save" and context["allow_cli"] is False
            assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
            value = stage(milestone("Open", "Save"))
            invalid = deepcopy(value)
            invalid["milestones"] *= 9
            assert not validator(invalid)
            assert "Invalid stage schema" in messages[-1]["content"]
            assert validator(value)
            return value

    config = SessionConfig(execution_mode="stage", allow_cli=False)
    components = build_default(client=Client(), endpoint="http://unused", config=config)
    observation = make_observation(tmp_path, 0)
    from pathlib import Path

    assert components.planner("Configure and save", Path(observation.screenshot.path), [], [],
                              "<empty/>", None, [], 10)["stage_goal"] == "Configure and save"


def test_known_wrong_state_replans_without_model_verify(tmp_path):
    change = milestone("Open", "Save")
    change["checks"] = [{"target": {"name": "Enabled", "role": "check_box"},
                         "property": "checked", "expected": True}]
    session, planner, verifier, _ = session_for([
        stage(change), stage(milestone("Other", "Saved")),
    ])
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    session.act(make_observation(tmp_path, 1, receipt=gui_receipt(),
                                 tree_xml=tree(("Other", 100))))
    assert verifier.calls == [] and len(planner.calls) == 2
    verified = next(e for e in session.events if e["route"] == "gui_verified")["verification"]
    assert verified["outcome"] == "not_achieved" and verified["source"] == "rule_a11y"


def test_scroll_can_continue_but_never_claims_milestone_done_from_movement(tmp_path):
    scroll = milestone("Open", "Save")
    scroll["action_proposals"][0]["operation"] = "scroll_down"
    scroll["checks"] = [{"target": {"name": "Enabled", "role": "check_box"},
                         "property": "checked", "expected": True}]
    session, planner, verifier, _ = session_for([stage(scroll)])
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    result = session.act(make_observation(tmp_path, 1, receipt=gui_receipt(),
                                          tree_xml=tree(("Open", 10), ("New row", 100))))
    assert isinstance(result, GuiAction) and result.action_type == "scroll"
    assert len(planner.calls) == 1 and verifier.calls == [] and session.stage.index == 0
    verified = next(e for e in session.events if e["route"] == "gui_verified")["verification"]
    assert verified["outcome"] == "uncertain" and verified["continue_local"] is True


def test_terminal_rejection_does_not_accept_finished_stage_as_task_success(tmp_path):
    session, planner, verifier, _ = session_for([
        stage(milestone("Open", "Save")), DONE, stage(milestone("Save", "Saved")),
    ], [valid_verifier_response(task_status="incomplete")])
    session.act(make_observation(tmp_path, 0, tree_xml=tree(("Open", 10))))
    result = session.act(make_observation(tmp_path, 1, receipt=gui_receipt(), tree_xml=tree(("Save", 100))))
    assert isinstance(result, GuiAction) and len(planner.calls) == 3
    assert len(verifier.calls) == 1
    assert any(item["operation"] == "completion_rejected" for item in session.recent)


def test_disappearance_is_valid_but_missing_control_needs_independent_evidence(tmp_path):
    from tandem.stage_rules import rule_verification

    item = milestone("Open", "Google (Default)")
    item["checks"][0]["expected"] = False
    assert valid_stage(stage(item))
    pending = {"kind": "cli", "plan": item, "before_tree": tree(("Google (Default)", 10))}
    # A different active screen must not prove that a persistent setting was removed.
    assert rule_verification(pending, cli_receipt(), tree(("Other screen", 100))) is None
