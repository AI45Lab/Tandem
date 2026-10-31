"""One requirement-bound semantic verification per ended goal stage, never per GUI action."""

import base64
import json
from pathlib import Path

PROMPT = """Independently verify the ENDED desktop subtask against its fixed work unit and ORIGINAL
requirements. Do not judge each intermediate action, demand later pages earlier, or trust the actor's
printed success. Return only JSON:
{stage_outcome:"met|not_met|uncertain",unit_met:false,delivery_state:"none|implemented|saved|verified",
summary:"specific observed result",remaining:["concrete missing part"],evidence_refs:["supplied id"],
facts:[{key:"registered or concrete reusable key",value:"exact content including numbers/units",
status:"confirmed|uncertain",scope:"task|stage",source_ref:"actual file/page/location",
evidence_refs:["supplied id"],complete:true}],
materials:[{source_ref:"actual file/url",covered_parts:["page/section"],
summary:"reusable source content",evidence_refs:["supplied id"]}],
requirement_checks:[{id:"R1",status:"met|not_met|uncertain",evidence_refs:["supplied id"]}],
artifacts:[{target_path:"actual final path",working_path:"actual working path",save_state:"modified|saved",
evidence_refs:["supplied id"]}],invalidated_work_item_ids:[]}.
Use [] when no update is established. Reference only the supplied evidence IDs. Preserve original
requirements and source facts. Extract essential facts NOW from real observed material/CLI output so
later stages do not reread it; unobserved contents remain unknown. Preparation uses delivery_state=none.
Use the exact facts_needed key when observed information answers that key. Keep partial source coverage
in materials even if not all required facts have been acquired. Opening a reference image, a contact
sheet, an audit or a script
that reports failure is not delivery progress. A finished stage need not satisfy a whole requirement.
unit_met=true ONLY when the full fixed work unit is satisfied; for delivery it requires verified level
and concrete evidence. Saved requires actual persistence to the target, not a working copy or title.
File existence/compilation does not prove content or function. Do not invent a demand to repeat every
successful intermediate action. Mark unmet/uncertain criteria explicitly and preserve actual progress.
Later contradictions invalidate affected units; do not invalidate old work from an uncertain screenshot
alone. Do not read evaluators, hidden grading rules, answers or rewards. Be concise and evidence-based."""

PROMPT += '''
scope=task means reusable SOURCE CONTENT, not whole-task completion. scope=stage is only transient UI
state. A confirmed paragraph or data field is task-scope even while the rest of its source is unread.
Not seeing a source again does not contradict its recorded facts. Retain confirmed source values;
change one only with actual contradictory evidence and a nonempty correction_reason on that fact.
Use the precise registered source key when it is fully answered; store partial sections as separate
reusable facts/materials. Do not mark an entire packet confirmed when required fields are missing.
remaining must describe THIS stage's unmet exit conditions, not a list of every later task obligation.
Only mark unit_met when the original full unit is satisfied. Historical registered evidence may support
source facts; stage completion must also cite at least one CURRENT evidence ID.
All top-level keys are mandatory, including invalidated_work_item_ids:[] when nothing is invalidated.
Empty-update shape: {"stage_outcome":"uncertain","unit_met":false,"delivery_state":"none",
"summary":"Explain the observed state","remaining":[],"evidence_refs":[],"facts":[],"materials":[],
"requirement_checks":[],"artifacts":[],"invalidated_work_item_ids":[]}.
Use actual observed evidence and updates, not this example's empty values. A stage purpose=prepare is
source acquisition only even when attached to a delivery unit; it cannot finish that delivery unit.
For lists/tables/options, include entries:{"stable item/row/position":"observed value"} and complete:false
until the requested coverage is actually observed. New entries extend the old collection; conflicting
entries or scalar changes require current evidence and correction_reason. Never label a partial list
as a complete registered dependency. Temporary UI state is not required source content.
This request contains selected evidence, not the whole execution log. output_omitted_chars marks an
explicit excerpt: do not claim to have checked omitted contents or a complete source packet. Extract
only supported fields; ask for the missing section rather than another full-document audit.
For prepare, answer fact_targets using their EXACT registered keys and record partial coverage;
unit_met=false, delivery_state=none, and do not assess unrelated delivery requirements.
For produce/save/verify, check only the current stage exit condition and its fixed delivery unit.
Record partial implementation/saving without demanding all future task units. Return only memory deltas,
not a rewrite of existing facts/materials, and no new optional research or inspection requirements.
Missing source fields do not invalidate an independently useful, correctly implemented partial stage.
If that bounded exit condition is met, report stage_outcome=met with unit_met=false and the observed
implemented/saved level. Keep the full unit incomplete and preserve its missing values for later work.
Incomplete prose facts may be appended across stages: complete:false preserves earlier sections without
claiming a complete source. Mark complete:true only when the exact registered field/section is fully answered.
Never replace a known inventory with the contents of a different document under the same scalar key;
prefer document/field-specific facts and preserve source_ref. Do not guess identity or ownership.
'''


def result_error(value):
    """Precise contract failures; never invent evidence or coerce unsupported results."""
    for key, choices in {"stage_outcome": {"met", "not_met", "uncertain"},
                         "delivery_state": {"none", "implemented", "saved", "verified"}}.items():
        if value.get(key) not in tuple(choices):
            return key + " must be one of " + str(sorted(choices))
    for key, kind in {"unit_met": bool, "summary": str}.items():
        if type(value.get(key)) is not kind:
            return key + " must be " + kind.__name__
    lists = ("remaining", "evidence_refs", "facts", "materials", "requirement_checks", "artifacts",
             "invalidated_work_item_ids")
    for key in lists:
        if not isinstance(value.get(key), list):
            return key + " must be an array (use [] for no updates)"
    for key in ("remaining", "evidence_refs", "invalidated_work_item_ids"):
        if any(not isinstance(x, str) for x in value[key]):
            return key + " must contain only strings"
    fields = {"facts": ("key", "value", "source_ref"), "materials": ("source_ref", "summary"),
              "requirement_checks": ("id",), "artifacts": ("target_path", "working_path")}
    enums = {"facts": {"status": {"confirmed", "uncertain"}, "scope": {"task", "stage"}},
             "requirement_checks": {"status": {"met", "not_met", "uncertain"}},
             "artifacts": {"save_state": {"modified", "saved"}}}
    for collection, strings in fields.items():
        for index, record in enumerate(value[collection]):
            path = f"{collection}[{index}]"
            if not isinstance(record, dict):
                return path + " must be an object"
            for key in strings:
                if not isinstance(record.get(key), str):
                    return path + "." + key + " must be a string"
            arrays = ("evidence_refs", "covered_parts") if collection == "materials" else ("evidence_refs",)
            for key in arrays:
                if not isinstance(record.get(key), list) or any(not isinstance(x, str) for x in record[key]):
                    return path + "." + key + " must be an array of strings"
            for key, choices in enums.get(collection, {}).items():
                if record.get(key) not in tuple(choices):
                    return path + "." + key + " must be one of " + str(sorted(choices))
            if collection == "facts":
                if "complete" in record and type(record["complete"]) is not bool:
                    return path + ".complete must be a boolean"
                if "entries" in record and (not isinstance(record["entries"], dict) or any(
                        not isinstance(k, str) or not isinstance(v, str)
                        for k, v in record["entries"].items())):
                    return path + ".entries must map strings to strings"
    return ""


def valid_result(value):
    return not result_error(value)


def _excerpt(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit // 2] + "\n[... omitted source content; not inspected ...]\n" + text[-limit // 2:]


def _actions(history, output_budget):
    """Keep receipts and semantic deltas, not repeated snapshot IDs/ancestry/whole trees."""
    actions = []
    previous = {}
    output_records = max(1, sum(bool(r.get("full_output_ref") or r.get("stdout") or r.get("stderr"))
                                for r in history))
    limit = max(1000, output_budget // output_records)
    for record in history:
        action = {k: record[k] for k in ("evidence_ref", "kind", "operation", "target", "returncode",
                                        "observed_change", "relevant_change", "target_effect",
                                        "full_output_ref") if k in record}
        if record.get("kind") != "cli" and record.get("action"):
            action["action"] = record["action"]
        output = dict(record)
        if record.get("full_output_ref"):
            output.update(json.loads(Path(record["full_output_ref"]).read_text(encoding="utf-8")))
        omitted = {}
        for key in ("stdout", "stderr"):
            text = output.get(key, "")
            if text:
                action[key] = _excerpt(text, limit)
                if len(text) > limit:
                    omitted[key] = len(text) - limit
        if omitted:
            action["output_omitted_chars"] = omitted
        changes, current = [], {}
        for control in record.get("observed_controls", []):
            key = (control.get("role"), control.get("name"), control.get("x"), control.get("y"))
            value = {k: control[k] for k in ("role", "name", "value", "focused", "checked", "selected")
                     if k in control}
            current[key] = value
            if value != previous.get(key):
                changes.append(value)
        previous = current
        if changes:
            action["control_changes"] = changes
        actions.append(action)
    return actions


def _failure_result(memory, history, end_reason, evidence):
    """No semantic success claim from a known error or an entirely ineffective local attempt."""
    pure_no_effect = (history and all(h.get("kind") == "gui"
                                     and not h.get("relevant_change", h.get("observed_change"))
                                     for h in history))
    skip = (end_reason == "execution_error" or not history and end_reason != "stage_done_requested"
            or pure_no_effect and memory.active_stage["purpose"] not in {"save", "verify"})
    if not skip:
        return None
    return {"stage_outcome": "uncertain", "unit_met": False, "delivery_state": "none",
            "summary": "No semantic acceptance: " + end_reason,
            "remaining": ["Inspect any partial effects before recovery; do not repeat the failed method."],
            "evidence_refs": list(evidence)[-1:], "facts": [], "materials": [],
            "requirement_checks": [], "artifacts": [], "invalidated_work_item_ids": [],
            "check_mode": "local_failure"}


def verify_goal(client, instruction, screenshot, *, memory, history, end_reason, evidence):
    local = _failure_result(memory, history, end_reason, evidence)
    if local is not None:
        return local
    stage = memory.active_stage
    work = memory.work_items[stage["work_item_id"]]
    targets = stage.get("fact_targets", work["facts_needed"])
    keys = set(stage["input_fact_keys"]) | {f["key"] for f in targets}
    budget = client.config.stage_verify_max_chars
    actions = _actions(history, budget // 2)
    context = {"task": instruction,
               "stage": {k: v for k, v in stage.items() if k != "command"},
               "command_excerpt": _excerpt(stage.get("command", ""), 3000),
               "fixed_work_item": {**work, "facts_needed": targets},
               "requirements": [{k: r[k] for k in ("id", "requirement", "kind")}
                                for r in memory.requirements if r["id"] in work["requirement_ids"]
                                or r["kind"] == "constraint"],
               "known_facts": [f for f in memory.facts.values() if f["key"] in keys],
               "end_reason": end_reason, "actual_actions": actions, "evidence_ids": list(evidence),
               "historical_evidence_ids": sorted(memory.known_evidence)}
    text = json.dumps(context, ensure_ascii=False)
    if len(text) > budget:
        # Receipt deltas stay intact. Explicitly excerpt source text, never silently claim full coverage.
        for index, original in enumerate(context["known_facts"]):
            fact = {k: v for k, v in original.items() if k != "entries"}
            fact["value"] = _excerpt(fact["value"], max(1000, budget // (2 * max(1, len(keys)))))
            if fact["value"] != original["value"]:
                fact["value_excerpt_only"] = True
            context["known_facts"][index] = fact
        text = json.dumps(context, ensure_ascii=False)
    content = [{"type": "text", "text": text}]
    source_frames = [h["screenshot"] for h in history if h.get("source_frame")]
    paths = source_frames[-5:] if stage["purpose"] == "prepare" else (
        [history[0]["screenshot"]] if history else [])
    frames = [Path(p) for p in dict.fromkeys(paths + [str(screenshot)])]
    for path in frames:
        content.extend([{"type": "text", "text": "Observed screenshot: " + str(path)},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                         + base64.b64encode(path.read_bytes()).decode("ascii")}}])
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": content}]

    def validate(value):
        error = result_error(value)
        if not error:
            allowed = set(evidence) | memory.known_evidence
            records = [value, *value["facts"], *value["materials"],
                       *value["artifacts"], *value["requirement_checks"]]
            unknown = sorted({ref for r in records for ref in r["evidence_refs"] if ref not in allowed})
            if unknown:
                error = "evidence_refs contain unregistered IDs: " + json.dumps(unknown)
            elif value["stage_outcome"] == "met" and not set(value["evidence_refs"]) & set(evidence):
                error = "a met stage must cite at least one CURRENT evidence ID"
        if error:
            messages.append({"role": "user", "content":
                "Invalid stage verification JSON: " + error + ". Return the COMPLETE corrected object "
                "with every mandatory key, without changing the observed facts or inventing evidence."})
        return not error

    result = client.json_request(messages, validate, role="verify_stage")
    result.update(check_mode="source" if stage["purpose"] == "prepare" else "delivery",
                  context_chars=len(text), image_count=len(frames))
    return result
