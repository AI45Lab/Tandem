"""Host-owned task memory. Plans request work; stage verification commits progress."""

import json
from copy import deepcopy

LEVELS = {"none": 0, "implemented": 1, "saved": 2, "verified": 3}


class TaskMemory:
    def __init__(self, instruction, requirements):
        self.instruction = instruction
        self.requirements = deepcopy(requirements)
        self.facts = {}
        self.materials = {}
        self.work_items = {}
        self.artifacts = {}
        self.failures = []
        self.execution_constraints = []
        self.active_stage = None
        self.stage_count = 0
        self.revision = 0
        self.known_evidence = set()
        self.last_rejections = []
        sources = {f["key"]: f for r in self.requirements for f in r["facts_needed"]}
        self.source_keys = set(sources)
        self.stats = {"stages": 0, "verified_stages": 0, "gui_actions": 0,
                      "cli_actions": 0, "new_facts": 0, "delivery_advances": 0,
                      "source_parts": 0, "stages_without_progress": 0}
        for req in self.requirements:
            req.update(status="unknown", evidence_refs=[])
            if req.get("kind") == "constraint":
                continue
            needed = [sources[key] for key in dict.fromkeys(
                key for keys in req["unit_fact_keys"] for key in keys)]
            preparation = f"{req['id']}:prepare"
            if needed:
                self._add(preparation, req, "prepare",
                          "Acquire missing source facts for a ready unit", [], needed)
            for index, unit in enumerate(req["units"], 1):
                keys = req["unit_fact_keys"][index - 1]
                self._add(f"{req['id']}:unit:{index}", req, "deliver", unit, [],
                          [sources[key] for key in keys])

    def _add(self, key, req, kind, goal, dependencies, facts):
        self.work_items[key] = {
            "id": key, "requirement_ids": [req["id"]], "kind": kind, "goal": goal,
            "completion_criteria": goal, "depends_on": dependencies,
            "facts_needed": facts, "status": "pending",
            "delivery_state": "none", "remaining": [], "evidence_refs": [],
        }

    def _facts_ready(self, item):
        return all(self.facts.get(f["key"], {}).get("status") == "confirmed"
                   and self.facts[f["key"]]["scope"] == "task"
                   and self.facts[f["key"]].get("complete", True) for f in item["facts_needed"])

    def preparation_target(self, item):
        units = [item] if item["kind"] == "deliver" else [
                 w for w in self.work_items.values() if w["kind"] == "deliver"
                 and w["status"] != "done" and w["requirement_ids"] == item["requirement_ids"]]
        choices = [(unit, [f for f in unit["facts_needed"]
                           if not self._facts_ready({"facts_needed": [f]})]) for unit in units]
        choices = [(unit, missing) for unit, missing in choices if missing]
        return min(choices, key=lambda pair: len(pair[1])) if choices else (item, [])

    def ready_items(self):
        for item in self.work_items.values():
            if item["kind"] == "prepare" and item["status"] != "done" and self._facts_ready(item):
                item.update(status="done", evidence_refs=[ref for f in item["facts_needed"]
                            for ref in self.facts[f["key"]]["evidence_refs"]])
        return sorted([i for i in self.work_items.values() if i["status"] != "done"
                       and all(self.work_items[d]["status"] == "done" for d in i["depends_on"])],
                      key=lambda i: (i["kind"] != "deliver", i.get("stalled_stages", 0),
                                     len(self.preparation_target(i)[1])))

    def start(self, plan, step):
        item = self.work_items[plan["work_item_id"]]
        if item not in self.ready_items():
            raise ValueError("Stage work item is not ready or has already completed")
        self.stage_count += 1
        self.active_stage = {**deepcopy(plan), "id": f"S{self.stage_count}",
                             "started_step": step, "actions": 0, "status": "running"}
        if plan["purpose"] == "prepare":
            unit, missing = self.preparation_target(item)
            self.active_stage.update(prepares_unit=unit["id"], fact_targets=deepcopy(missing))
        item["status"] = "active"
        self.stats["stages"] += 1
        return self.active_stage

    def record_action(self, record):
        self.active_stage["actions"] += 1
        self.stats["cli_actions" if record["kind"] == "cli" else "gui_actions"] += 1
        if record["returncode"] != 0:
            error = (record.get("stderr") or record.get("stdout") or "Execution failed")[-700:]
            self._failure(error, [record["evidence_ref"]])

    def _failure(self, error, refs):
        stage = self.active_stage
        matches = [f for f in self.failures if f["work_item_id"] == stage["work_item_id"]
                   and f["error"] == error]
        if matches:
            matches[-1]["count"] += 1
            matches[-1]["evidence_refs"] = refs
        else:
            self.failures.append({"stage_id": stage["id"], "work_item_id": stage["work_item_id"],
                                  "method": stage["method"], "error": error,
                                  "count": 1, "evidence_refs": refs})

    def apply(self, result, evidence):
        """Only the fixed active unit is writable; references must belong to real evidence."""
        stage = self.active_stage
        item = self.work_items[stage["work_item_id"]]
        current = set(evidence)
        self.known_evidence.update(current)
        allowed = self.known_evidence
        self.last_rejections = []
        advanced = False
        for fact in result["facts"]:
            fact = deepcopy(fact)
            refs = fact["evidence_refs"]
            if not refs or not set(refs) <= allowed:
                self.last_rejections.append({"key": fact["key"], "reason": "unregistered_evidence"})
                continue
            if fact["key"] in self.source_keys:
                fact["scope"] = "task"
            old = self.facts.get(fact["key"])
            entries = fact.get("entries", {})
            old_entries = old.get("entries", {}) if old else {}
            conflicts = any(key in old_entries and old_entries[key] != value
                            for key, value in entries.items())
            extending = bool(old_entries and entries and not conflicts)
            correction = bool(fact.get("correction_reason") and set(refs) & current)
            # Incomplete prose sources may arrive a section at a time without structured entries.
            # Append evidence, never replace the previously observed section or unlock a partial fact.
            if (old and old["status"] == fact["status"] == "confirmed"
                    and old["scope"] == fact["scope"] == "task" and not old.get("complete", True)
                    and not entries and not old_entries and set(refs) & current and not correction):
                sections = deepcopy(old.get("observations", [{k: old[k] for k in
                                    ("value", "source_ref", "evidence_refs")}]))
                if fact["value"] not in [section["value"] for section in sections]:
                    sections.append({k: fact[k] for k in ("value", "source_ref", "evidence_refs")})
                fact["observations"] = sections
                fact["value"] = "\n".join(section["value"] for section in sections)
                fact["evidence_refs"] = list(dict.fromkeys(old["evidence_refs"] + refs))
                extending = True
            if entries:
                fact["entries"] = {**old_entries, **entries}
                fact["value"] = json.dumps(fact["entries"], ensure_ascii=False)
                fact["evidence_refs"] = list(dict.fromkeys((old or {}).get("evidence_refs", []) + refs))
                fact["complete"] = bool(fact.get("complete", False) or (old or {}).get("complete", False))
            if (old and old["status"] == "confirmed" and old["scope"] == "task"
                    and (fact["status"] != "confirmed" or fact["scope"] != "task"
                         or old.get("complete", True) and not fact.get("complete", True)
                         or old["value"] != fact["value"] and not (correction or extending)
                         or conflicts and not correction)):
                self.last_rejections.append({"key": fact["key"], "reason": "confirmed_source_preserved"})
                continue
            if (fact["status"] == "confirmed" and fact["scope"] == "task"
                    and (old is None or old["value"] != fact["value"] or old["status"] != fact["status"]
                         or old.get("complete", True) != fact.get("complete", True))):
                advanced = advanced or fact["key"] in self.source_keys
                self.stats["new_facts"] += 1
            self.facts[fact["key"]] = {**fact, "requirement_ids": item["requirement_ids"],
                                      "observed_stage": stage["id"]}
        for material in result["materials"]:
            if material["evidence_refs"] and set(material["evidence_refs"]) <= allowed:
                old = self.materials.get(material["source_ref"], {})
                new_parts = set(material["covered_parts"]) - set(old.get("covered_parts", []))
                if new_parts:
                    self.stats["source_parts"] += len(new_parts)
                summary = old.get("summary", "")
                if material["summary"] not in summary:
                    summary = (summary + "\n" + material["summary"]).strip()
                self.materials[material["source_ref"]] = {
                    **material, "summary": summary,
                    "covered_parts": list(dict.fromkeys(old.get("covered_parts", [])
                                                         + material["covered_parts"])),
                    "evidence_refs": list(dict.fromkeys(old.get("evidence_refs", [])
                                                        + material["evidence_refs"]))}
        refs = result["evidence_refs"]
        grounded = bool(set(refs) & current) and set(refs) <= allowed
        level = result["delivery_state"]
        delivering = item["kind"] == "deliver" and stage["purpose"] != "prepare"
        if (grounded and delivering and LEVELS[level] > LEVELS[item["delivery_state"]]
                and (level != "verified" or result["stage_outcome"] == "met")):
            item["delivery_state"] = level
            advanced = True
            self.stats["delivery_advances"] += 1
        item.update(status="pending", remaining=result["remaining"], evidence_refs=refs if grounded else [])
        preparation_met = item["kind"] == "prepare" and self._facts_ready(item)
        if grounded and result["stage_outcome"] == "met":
            self.stats["verified_stages"] += 1
            if preparation_met or (delivering and result["unit_met"]
                                   and level == "verified"):
                item["status"] = "done"
                advanced = True
        for check in result["requirement_checks"]:
            if check["evidence_refs"] and set(check["evidence_refs"]) <= allowed:
                req = next((r for r in self.requirements if r["id"] == check["id"]), None)
                if req is not None:
                    req.update(status=check["status"], evidence_refs=check["evidence_refs"])
        for artifact in result["artifacts"]:
            if not artifact["evidence_refs"] or not set(artifact["evidence_refs"]) <= allowed:
                continue
            old = self.artifacts.get(artifact["target_path"], {})
            self.artifacts[artifact["target_path"]] = {**artifact, "revision": old.get("revision", 0) + 1}
        for key in result["invalidated_work_item_ids"]:
            if key in self.work_items and self.work_items[key]["kind"] == "deliver" and grounded:
                self.work_items[key].update(status="pending", delivery_state="none",
                                            remaining=["Contradictory evidence requires reinspection"])
        if result["stage_outcome"] != "met" and grounded:
            self._failure("; ".join(result["remaining"]) or result["summary"], refs)
        self.stats["stages_without_progress"] = 0 if advanced else self.stats["stages_without_progress"] + 1
        item["stalled_stages"] = 0 if advanced else item.get("stalled_stages", 0) + 1
        item["last_attempt"] = {k: stage[k] for k in ("route", "purpose", "method", "command")}
        self.revision += 1
        self.active_stage = None
        self.ready_items()
        return advanced

    def snapshot(self):
        return deepcopy({"schema_version": 2, "revision": self.revision, "instruction": self.instruction,
                         "requirements": self.requirements, "materials": list(self.materials.values()),
                         "facts": list(self.facts.values()), "work_items": list(self.work_items.values()),
                         "artifacts": list(self.artifacts.values()), "failures": self.failures,
                         "execution_constraints": self.execution_constraints,
                         "memory_update_rejections": self.last_rejections,
                         "active_stage": self.active_stage, "stats": self.stats,
                         "evidence_refs": sorted(self.known_evidence)})
