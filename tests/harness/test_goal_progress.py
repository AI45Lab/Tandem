"""Synthetic regressions for partial delivery, field binding and semantic navigation stalls."""

from unittest.mock import Mock

import pytest
from PIL import Image

from tandem.gui.compile import gui_action
from tandem.gui.grounding import ground_visual
from tandem.memory.context import planning_context
from tandem.memory.state import TaskMemory
from tandem.models.ranking import Ranking
from tandem.runtime.goal_stage import ObservationRequired, _document_mismatch, _target_effect

from .conftest import gui_receipt, make_observation
from .test_goal_execution import _space
from .test_goal_memory import fact, prepare, session, source_memory
from .test_goal_stage import plan, requirements, result


def test_partial_sources_allow_delivery_without_claiming_source_or_unit_complete():
    memory = source_memory()
    prepare(memory, fact(value="Known first section", complete=False))
    item = planning_context(memory)["ready_work_items"][0]
    assert item["id"] == "R1:unit:1" and item["can_start_partial"]
    assert item["next_acquisition"]["missing_facts"][0]["key"] == "quota"
    memory.start({**plan(), "completion_criteria": "Known first section saved"}, 1)
    memory.apply(result(unit_met=False, delivery_state="saved", remaining=["Read remaining section"]),
                 {"A2": {}})
    assert memory.work_items[item["id"]]["delivery_state"] == "saved"
    assert memory.work_items[item["id"]]["status"] == "pending"
    assert memory.work_items["R1:prepare"]["status"] != "done"
    assert not memory.facts["quota"]["complete"]
    memory.start({**plan(), "purpose": "prepare"}, 2)
    assert memory.active_stage["fact_targets"][0]["key"] == "quota"


def test_explicit_dependencies_still_apply_and_preparation_stays_with_selected_unit():
    req = requirements()[0]
    req.update(units=["First section", "Second section"], unit_fact_keys=[["first"], ["second"]],
               facts_needed=[{"key": key, "description": key} for key in ("first", "second")])
    memory = TaskMemory("Edit", [req])
    second = memory.work_items["R1:unit:2"]
    second["depends_on"] = ["R1:unit:1"]
    assert second not in memory.ready_items()
    second["depends_on"] = []
    memory.start({**plan(), "work_item_id": second["id"], "purpose": "prepare"}, 0)
    assert memory.active_stage["prepares_unit"] == second["id"]
    assert memory.active_stage["fact_targets"][0]["key"] == "second"


FORM = '''<desktop-frame foreground_title="Research Portal - Google Chrome">
  <application active="true"><entry name="Address and search bar" editable="true"
    screencoord="(80,10)" size="(700,30)">file:///home/user/research-form.html?type=paper</entry>
    <section><label>Title *</label><entry editable="true" focused="false"
      screencoord="(200,100)" size="(200,30)"/>
      <label>Issue number</label><entry editable="true" focused="true"
      screencoord="(200,200)" size="(200,30)"/>
      <label>Title of series</label><entry editable="true"
      screencoord="(200,300)" size="(200,30)"/>
    </section></application></desktop-frame>'''


def test_text_binds_to_observed_label_instead_of_unrelated_focus():
    targets, space = _space(FORM, [{"label": "Article title", "target_hint": "Title",
                                   "text": "Observed source title", "input_mode": "replace"}])
    choices = space.target_heads["type_text"]
    assert len(choices) == 1
    target = next(t for t in targets if t.id == choices[0].target_id)
    assert target.name == "Title *" and not target.focused
    action = gui_action(choices[0], target)
    assert action.parameters["click"] == [300, 115]
    pending = {"operation": "type_text", "field_label": "Title *", "input_mode": "replace",
               "expected_text": "Observed source title"}
    wrong = FORM.replace('size="(200,30)"/>\n      <label>Title of series',
                         'size="(200,30)">Observed source title</entry>\n      <label>Title of series')
    assert _target_effect(pending, _space(wrong)[0]) == "not_met"


def test_unlabelled_or_ambiguous_fields_do_not_receive_all_supplied_text():
    inputs = [{"label": "Abstract", "target_hint": "Abstract", "text": "Known abstract",
               "input_mode": "replace"}]
    assert not _space(FORM, inputs)[1].target_heads["type_text"]
    duplicated = FORM.replace("Issue number", "Title *")
    inputs[0].update(target_hint="Title", label="Title")
    assert not _space(duplicated, inputs)[1].target_heads["type_text"]


def test_website_identity_uses_observed_url_not_business_title():
    targets, _ = _space(FORM)
    assert not _document_mismatch("research-form.html", FORM, targets)
    assert _document_mismatch("other-form.html", FORM, targets)


@pytest.mark.parametrize("title,blocked", [
    ("Untitled - WPS Presentation", True), ("different.pptx - WPS Office", True),
    ("report.pptx - WPS Office", False), ("WPS Office", False),
])
def test_document_guard_distinguishes_positive_mismatch_from_unknown(title, blocked):
    tree = f'<desktop-frame foreground_title="{title}"/>'
    assert _document_mismatch("report.pptx", tree, []) is blocked


def test_visual_typing_cannot_bypass_field_binding(tmp_path):
    obs = make_observation(tmp_path, 0)
    proposed = [{"operation": "type_text", "target": name, "target_hint": "Title", "bounds": [1, 1, 20, 20],
                 "text": "Known title", "input_mode": "replace"} for name in ("Issue number", "Title")]
    client = Mock()
    client.json_request.return_value = {"candidates": proposed}
    candidates = ground_visual(client, "Edit", {"action_proposals": [
        {"operation": "type_text", "label": "Title", "target_hint": "Title", "text": "Known title",
         "input_mode": "replace"}]}, tmp_path / "step_00.png")
    assert len(candidates) == 1 and candidates[0].metadata["field_label"] == "Title"
    assert obs.step_idx == 0


@pytest.mark.parametrize("acquire", [False, True])
def test_repeated_navigation_checks_semantic_progress_before_continuing(tmp_path, acquire):
    s = session()
    s.begin("Read source then edit", requirements())
    s.components.stage_verifier = Mock(return_value=result(
        stage_outcome="not_met", unit_met=False, delivery_state="none", evidence_refs=["A4"],
        materials=[{"source_ref": "source.pdf", "covered_parts": ["page 2"], "summary": "New content",
                    "evidence_refs": ["A4"]}] if acquire else []))
    chosen = []

    def rank(**kwargs):
        candidates = kwargs["action_space"].candidates()
        scrolling = [c for c in candidates if c.operation == "scroll" and "DOWN" in c.id]
        winner = scrolling[0] if scrolling else kwargs["action_space"].controls["return_to_planner"]
        chosen.append(winner.operation)
        return Ranking(winner, [], [], 0, 0, 1, True)

    s.components.selector.rank = rank
    for attempt in range(2):
        s.goal.memory.start(plan(), attempt * 4)
        initial = make_observation(tmp_path, attempt * 4)
        Image.new("RGB", (64, 64), "black").save(initial.screenshot.path)
        s.act(initial)
        for offset in range(1, 5):
            observation = make_observation(tmp_path, attempt * 4 + offset, receipt=gui_receipt())
            Image.new("RGB", (64, 64), "white" if offset % 2 else "black").save(
                observation.screenshot.path)
            if offset == 4:
                with pytest.raises(ObservationRequired):
                    s.act(observation)
            else:
                s.act(observation)
        assert s.events[-2]["route"] == "stage_verified"
        assert s.events[-2]["end_reason"] == "repeated_navigation_checkpoint"
        assert s.components.stage_verifier.call_count == attempt + 1
    s.goal.memory.start(plan(), 8)
    if acquire:
        # Same covered page is not new acquisition on the second attempt, but the first reset the count.
        s.act(make_observation(tmp_path, 8))
        assert chosen[-1] == "scroll"
    else:
        with pytest.raises(ObservationRequired):
            s.act(make_observation(tmp_path, 8))
        assert chosen[-1] == "return_to_planner"
        assert s.goal.memory.execution_constraints[-1]["navigation_key"]
