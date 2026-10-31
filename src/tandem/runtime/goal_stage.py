"""Goal-stage loop: receipts/observations each step, one semantic verifier at stage end."""

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageChops, ImageStat

from ..gui.goal_candidates import foreground_tree, goal_candidates
from ..memory.context import execution_context
from ..models.ranking import ranking_dict
from ..protocol.models import CliAction, FailAction
from .episode import handle_done, resolve_done_probe


class ObservationRequired(Exception):
    """Refresh without executing/replaying an action or consuming an action budget."""


def _state_key(targets):
    return tuple(sorted((t.role, t.name, t.x, t.y, t.value, bool(t.focused), str(t.checked), str(t.selected))
                        for t in targets))


def _visual_changed(before, after):
    frames = []
    for path in (before, after):
        with Image.open(path) as image:
            frames.append(image.crop((0, min(32, image.height // 4), image.width, image.height))
                          .convert("L").resize((160, 90)))
    return ImageStat.Stat(ImageChops.difference(*frames)).mean[0] > 1.0


def _loop_state(targets, tree):
    root = ET.fromstring(tree or "<empty/>")
    return (root.get("foreground_title", ""), root.get("foreground_class", ""),
            tuple(sorted((t.role, _control_name(t), t.x, t.y, "" if t.role == "slider" else t.value,
                          str(t.checked)) for t in targets)))


def _control_name(target):
    if target.role != "page_tab":
        return target.name
    name = re.sub(r"\s+- Memory usage - .+$", "", target.name)
    return re.sub(r"\s*[–-]\s*(?:Audio playing|Video playing in picture-in-picture mode)$", "", name)


def _cycle_actions(recent, state):
    for period in (2, 3, 4):
        if len(recent) < period * 2:
            continue
        first, second = recent[-period * 2:-period], recent[-period:]
        if first == second and any(a != first[0] for a in first):
            return {a["key"] for a in second if a["state"] == state}
    return set()


def _action_key(candidate, targets=()):
    target = next((t for t in targets if t.id == candidate.target_id), None)
    name = (f"{target.role}|{_control_name(target)}|{target.x}|{target.y}" if target else
            candidate.metadata.get("semantic_key") or candidate.description)
    if candidate.operation == "keypress":
        name += repr([(t.role, t.name, t.x, t.y) for t in targets if t.focused])
    parameters = {k: candidate.metadata[k]
                  for k in ("text", "input_mode", "fraction", "key_sequence", "visual_point")
                  if k in candidate.metadata}
    return (candidate.operation, name, json.dumps(parameters, sort_keys=True, ensure_ascii=False))


def _target_effect(old, targets):
    """Local effect evidence, not semantic stage acceptance. Unknown never means success."""
    if old["operation"] == "type_text":
        focus = [t for t in targets if t.focused and t.role != "password_text"]
        if len(focus) == 1 and focus[0].value:
            if old.get("field_label") and focus[0].name.casefold() != old["field_label"].casefold():
                return "not_met"
            matches = (focus[0].value == old["expected_text"] if old["input_mode"] == "replace"
                       else old["expected_text"] in focus[0].value)
            return "met" if matches else "not_met"
    if old["operation"] == "set_slider":
        target = next((t for t in targets if t.semantic_key == old["target_semantic"]), None)
        if (target and target.value and target.range_min is not None and target.range_max is not None
                and target.range_max > target.range_min):
            fraction = (float(target.value) - target.range_min) / (target.range_max - target.range_min)
            return "met" if abs(fraction - old["fraction"]) <= 0.04 else "not_met"
    return "unknown"


def _document_mismatch(document, tree, targets):
    """Reject observed contradictions, not a website's human title or a generic app title."""
    title = ET.fromstring(tree or "<empty/>").get("foreground_title", "")
    filename = Path(document).name.casefold()
    if Path(document).stem.casefold() in title.casefold():
        return False
    addresses = [t.value for t in targets if "address" in t.name.casefold()
                 and "://" in t.value]
    if Path(document).suffix.casefold() in {".html", ".htm"} and addresses:
        return all(Path(unquote(urlsplit(value).path)).name.casefold() != filename for value in addresses)
    return bool(re.search(r"\buntitled\b|\S+\.(?:pptx?|docx?|xlsx?|od[ptsg]|pdf)\b", title, re.I))


def _navigation_key(candidate, target, work, state):
    if candidate.operation == "scroll":
        return (work, *state[:2], "scroll", "up" if "UP" in candidate.id.upper() else "down")
    if target and re.search(r"\b(?:zoom|pan)\b", target.name, re.I):
        return (work, *state[:2], candidate.operation, target.name.casefold())
    return None


class GoalExecution:
    def __init__(self, memory, max_actions):
        self.memory = memory
        self.max_actions = max_actions
        self.pending = None
        self.history = []
        self.end_reason = None
        self.visual = []
        self.visual_step = None
        self.attempts = []
        self.failed_actions = {}
        self.navigation_failures = {}
        self.grounded_states = set()
        self.no_effect = 0
        self.empty_stages = 0

    def _emit_state(self, session, step):
        session.events.append({"route": "task_memory", "step": step,
                               "state": self.memory.snapshot()})

    def _receive(self, session, observation, targets, tree):
        if self.pending is None:
            return
        receipt = observation.last_receipt
        if receipt is None or not receipt.acknowledged:
            raise RuntimeError("Missing execution receipt; action is not replayed")
        old = self.pending
        self.pending = None
        signature = _state_key(targets)
        changed = old["kind"] == "cli" or signature != old["state"] or _visual_changed(
            old["before_screenshot"], observation.screenshot.path)
        effect = _target_effect(old, targets)
        relevant_change = (old["kind"] == "cli" or effect == "met"
                           or effect != "not_met" and old["loop_state"] != _loop_state(targets, tree))
        if effect == "unknown" and (not targets or old.get("visual_action")):
            relevant_change = changed
        if old["kind"] != "cli":
            key = (self.memory.active_stage["work_item_id"], old["loop_state"], old["candidate_key"])
            if not relevant_change:
                self.failed_actions[key] = self.failed_actions.get(key, 0) + 1
            self.attempts.append({"work": key[0], "state": old["loop_state"], "key": old["candidate_key"]})
            self.attempts = self.attempts[-16:]
        self.no_effect = 0 if relevant_change else self.no_effect + 1
        record = {"step": observation.step_idx, "evidence_ref": f"A{observation.step_idx}",
                  "kind": old["kind"], "operation": old["operation"], "target": old["target"],
                  "action": old["action"], "returncode": receipt.returncode,
                  "stdout": receipt.stdout, "stderr": receipt.stderr,
                  "full_output_ref": receipt.full_output_ref, "screenshot": observation.screenshot.path,
                  "observed_controls": [t.compact() for t in targets][:40],
                  "source_frame": self.memory.active_stage["purpose"] == "prepare",
                  "signature": signature, "observed_change": changed,
                  "relevant_change": relevant_change, "target_effect": effect,
                  "navigation_key": old.get("navigation_key")}
        self.history.append(record)
        self.memory.record_action(record)
        session.recent.append({"operation": old["operation"], "target": old["target"],
                               "goal": self.memory.active_stage["goal"],
                               "outcome": "changed" if relevant_change else "no_effect",
                               "returncode": receipt.returncode,
                               "evidence_ref": record["evidence_ref"]})
        session.events.append({"route": "goal_action", "step": observation.step_idx,
                               "record": record, "effect_verified": False})
        if receipt.returncode != 0:
            self.end_reason = "execution_error"
        elif old["kind"] == "cli":
            self.end_reason = "cli_returned"
        elif self.memory.active_stage["actions"] >= self.memory.active_stage["max_actions"]:
            self.end_reason = "stage_action_limit"
        elif (record["navigation_key"] and len(self.history) >= 4
              and all(h.get("navigation_key") == record["navigation_key"] for h in self.history[-4:])):
            self.end_reason = "repeated_navigation_checkpoint"
        elif self.no_effect >= 3 and (session.components.grounder is None
                or (self.memory.active_stage["work_item_id"], _loop_state(targets, tree))
                in self.grounded_states):
            self.end_reason = "repeated_action_without_observable_progress"

    def _finish(self, session, observation):
        reference = f"{self.memory.active_stage['id']}:O{observation.step_idx}"
        evidence = {h["evidence_ref"]: h for h in self.history}
        evidence[reference] = {"screenshot": observation.screenshot.path}
        started = time.perf_counter()
        result = session.components.stage_verifier(
            session.instruction, Path(observation.screenshot.path), memory=self.memory,
            history=[{k: v for k, v in h.items() if k != "signature"} for h in self.history],
            end_reason=self.end_reason, evidence=evidence)
        stage_id = self.memory.active_stage["id"]
        work = self.memory.active_stage["work_item_id"]
        source_progress = (self.memory.stats["new_facts"], self.memory.stats["source_parts"])
        advanced = self.memory.apply(result, evidence)
        acquired = source_progress != (self.memory.stats["new_facts"], self.memory.stats["source_parts"])
        if advanced or acquired:
            self.navigation_failures = {k: v for k, v in self.navigation_failures.items() if k[0] != work}
            self.memory.execution_constraints = [c for c in self.memory.execution_constraints
                                                 if not (c["work_item_id"] == work
                                                         and "navigation_key" in c)]
        elif self.end_reason == "repeated_navigation_checkpoint":
            key = self.history[-1]["navigation_key"]
            self.navigation_failures[key] = self.navigation_failures.get(key, 0) + 1
        self.empty_stages = self.empty_stages + 1 if not self.history and not advanced and not acquired else 0
        if self.memory.work_items[work]["status"] == "done":
            self.failed_actions = {k: v for k, v in self.failed_actions.items() if k[0] != work}
            self.attempts = [a for a in self.attempts if a["work"] != work]
            self.memory.execution_constraints = [c for c in self.memory.execution_constraints
                                                 if c["work_item_id"] != work]
        for rejected in self.memory.last_rejections:
            session.events.append({"route": "memory_update_rejected", "stage_id": stage_id, **rejected})
        session.events.append({"route": "stage_verified", "step": observation.step_idx,
                               "stage_id": stage_id, "end_reason": self.end_reason,
                               "evidence": {k: {"screenshot": v["screenshot"],
                                                "full_output_ref": v.get("full_output_ref")}
                                            for k, v in evidence.items()},
                               "verification": result, "memory_advanced": advanced,
                               "seconds": time.perf_counter() - started})
        session.recent.append({"operation": "stage_verified", "stage_id": stage_id,
                               "outcome": result["stage_outcome"], "evidence": result["summary"],
                               "remaining": result["remaining"]})
        self.history, self.end_reason, self.visual = [], None, []
        self.visual_step = None
        self.no_effect = 0
        self._emit_state(session, observation.step_idx)
        if self.empty_stages >= 3:
            session.events.append({"route": "goal_stalled", "step": observation.step_idx,
                                   "reason": "three_consecutive_stages_without_an_action"})
            return FailAction(reason="three_consecutive_stages_without_an_action")
        raise ObservationRequired("stage_verification_returned")

    def act(self, session, observation):
        tree = session._read_tree(observation)
        if tree:
            tree = foreground_tree(tree)
        screenshot = Path(observation.screenshot.path)
        targets = session.components.target_builder.build(
            tree, f"t{observation.step_idx}", 128, infer_button_labels=True, include_sliders=True,
            context=" ".join(str(v) for k, v in (self.memory.active_stage or {}).items()
                             if k in {"goal", "completion_criteria", "method", "guidance"}
                             ) or session.instruction, filter_occluded=True,
        ) if tree else []
        targets = session.components.semantic_enricher(
            targets, tree, (observation.screenshot.width, observation.screenshot.height),
            session._read_browser_snapshot(observation))
        self._receive(session, observation, targets, tree)
        if self.end_reason:
            return self._finish(session, observation)
        if session.done_probe is not None:
            result = resolve_done_probe(session, observation, tree)
            if result is not None:
                return result
            raise ObservationRequired("terminal_rejected")
        if self.memory.active_stage is None:
            started = time.perf_counter()
            plan = session.components.planner(
                session.instruction, screenshot, targets, session.recent, tree or "<empty/>",
                requirements=session.requirements, remaining_steps=observation.budget.steps_remaining,
                memory=self.memory)
            session.events.append({"route": "planner", "step": observation.step_idx,
                                   "mode": "goal", "plan": plan,
                                   "seconds": time.perf_counter() - started})
            if plan["done"]:
                result = handle_done(session, plan, observation, tree)
                if result is not None:
                    return result
                raise ObservationRequired("terminal_rejected")
            plan["max_actions"] = min(plan["max_actions"], self.max_actions)
            self.memory.start(plan, observation.step_idx)
            self._emit_state(session, observation.step_idx)
            raise ObservationRequired("planner_returned")
        stage = self.memory.active_stage
        document = stage.get("target_document")
        if (stage["route"] == "gui" and stage["purpose"] in {"produce", "save"}
                and stage["actions"] == 0 and document and _document_mismatch(document, tree, targets)):
            self.end_reason = f"target_document_mismatch: expected {document!r} in the observed foreground"
            return self._finish(session, observation)
        if stage["route"] == "cli":
            action = CliAction(command=stage["command"], timeout_s=session.config.cli_timeout_seconds,
                               want_observation="screenshot")
            self.pending = {"kind": "cli", "operation": "cli", "target": stage["method"],
                            "action": action.to_dict(), "state": _state_key(targets),
                            "before_screenshot": observation.screenshot.path}
            session.events.append({"route": "cli", "step": observation.step_idx,
                                   "stage_id": stage["id"], "action": action.to_dict()})
            return action
        return self._gui(session, observation, targets, tree, screenshot)

    def _gui(self, session, observation, targets, tree, screenshot):
        context = execution_context(self.memory)
        stage = self.memory.active_stage
        state = _loop_state(targets, tree)
        work = stage["work_item_id"]
        blocked_navigation = {k for k, count in self.navigation_failures.items()
                              if k[:3] == (work, *state[:2]) and count >= 2}
        for key in blocked_navigation:
            constraint = {"work_item_id": work, "window": list(state[:2]), "navigation_key": list(key),
                          "reason": "Repeated navigation changed pixels but two checkpoints acquired no "
                                    "source content or delivery progress. Use another interaction/source."}
            if constraint not in self.memory.execution_constraints:
                self.memory.execution_constraints.append(constraint)
        context["avoid_navigation"] = [list(k) for k in blocked_navigation]
        recent = [a for a in self.attempts if a["work"] == work][-8:]
        cycle_keys = _cycle_actions(recent, state)
        cycle = bool(cycle_keys)
        blocked = {key[2] for key, count in self.failed_actions.items()
                   if key[:2] == (work, state) and count >= 2}
        if cycle:
            blocked.update(cycle_keys)
            for key in blocked:
                failure_key = (work, state, key)
                self.failed_actions[failure_key] = max(2, self.failed_actions.get(failure_key, 0))
        for key in blocked:
            constraint = {"work_item_id": work, "window": list(state[:2]), "action_key": list(key),
                          "reason": "Repeated action/cycle in the same observed controls. Try a different "
                                    "interaction; unrelated animation or new facts do not clear it."}
            if constraint not in self.memory.execution_constraints:
                self.memory.execution_constraints.append(constraint)
        context["avoid_actions"] = [list(key) for key in blocked]
        semantic_missing = not any("gnome-shell" not in t.parent_context for t in targets)
        need_grounding = ((semantic_missing or self.no_effect >= 2 or cycle)
                          and (work, state) not in self.grounded_states)
        if need_grounding and session.components.grounder is not None:
            self.grounded_states.add((work, state))
            self._ground(session, observation, screenshot, context)
            if self.visual:
                raise ObservationRequired("local_visual_recovery_returned")
            # No visual target does not remove valid keyboard recovery such as Escape or Alt+Tab.
        space = session.components.candidate_builder.build(
            targets, 96, action_inputs=[], context=" ".join(
                context[k] for k in ("goal", "completion_criteria", "method", "guidance")))
        space = goal_candidates(space, targets, tree, context["inputs"],
                                (observation.screenshot.width, observation.screenshot.height))
        if self.visual_step == observation.step_idx and self.visual:
            space.target_heads["visual"] = self.visual
        if (work, state) in self.grounded_states:
            space.controls.pop("visual_fallback", None)
        for operation in space.target_heads:
            space.target_heads[operation] = [c for c in space.target_heads[operation]
                if _action_key(c, targets) not in blocked and _navigation_key(
                    c, next((t for t in targets if t.id == c.target_id), None), work, state)
                not in blocked_navigation]
        space.controls = {k: c for k, c in space.controls.items() if _action_key(c, targets) not in blocked}
        ranking = session.components.selector.rank(
            stage_goal=context["goal"], intent=json.dumps(context, ensure_ascii=False),
            active_window=ET.fromstring(tree).get("foreground_title", "") if tree else "",
            targets=targets, action_space=space,
            recent_actions=session.recent[-8:], screenshot=screenshot)
        winner = ranking.winner
        operation = winner.operation if winner else "return_to_planner"
        target = next((t for t in targets if winner and t.id == winner.target_id), None)
        action = session.components.compile_gui(winner, target) if winner else None
        session.events.append({"route": "gui", "step": observation.step_idx, "mode": "goal",
                               "stage_id": self.memory.active_stage["id"],
                               "plan": {"stage_goal": context["goal"], "current_goal": context["goal"]},
                               "candidates": [c.compact() for c in space.candidates()],
                               "winner": winner.compact() if winner else None,
                               "avoid_actions": context["avoid_actions"],
                               "ranking": ranking_dict(ranking),
                               "action": action.to_dict() if action else None})
        if operation == "visual_fallback" and session.components.grounder is not None:
            if (work, state) not in self.grounded_states:
                self.grounded_states.add((work, state))
                self._ground(session, observation, screenshot, context)
                if self.visual:
                    raise ObservationRequired("visual_grounder_returned")
        if action is None:
            self.end_reason = "stage_done_requested" if operation == "done" else "returned_to_planner"
            return self._finish(session, observation)
        self.pending = {"kind": action.kind, "operation": operation,
                        "target": winner.description, "action": action.to_dict(),
                        "state": _state_key(targets), "loop_state": state,
                        "candidate_key": _action_key(winner, targets),
                        "before_screenshot": observation.screenshot.path,
                        "expected_text": winner.metadata.get("text"),
                        "input_mode": winner.metadata.get("input_mode"),
                        "target_semantic": target.semantic_key if target else None,
                        "field_label": winner.metadata.get("field_label"),
                        "navigation_key": _navigation_key(winner, target, work, state),
                        "visual_action": operation == "scroll" or winner.source == "visual_grounder"
                                         or target is not None and target.role == "canvas",
                        "fraction": winner.metadata.get("fraction")}
        self.visual, self.visual_step = [], None
        return action

    def _ground(self, session, observation, screenshot, context):
        plan = {**context, "current_goal": context["goal"], "stage_goal": context["goal"],
                "action_proposals": [{"operation": "type_text", **v} for v in context["inputs"]]}
        self.visual = session.components.grounder(session.instruction, plan, screenshot)
        self.visual_step = observation.step_idx
        session.events.append({"route": "recovery", "step": observation.step_idx,
                               "stage_id": self.memory.active_stage["id"],
                               "method": "visual_grounding", "candidate_count": len(self.visual),
                               "avoid_actions": context.get("avoid_actions", [])})
