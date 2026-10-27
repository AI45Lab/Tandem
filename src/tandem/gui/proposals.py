"""planner 提案 → 聚焦候选空间；从旧仓库 gui/actions.py focused_candidates 按契约移植。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .candidates import DOUBLE_CLICK_ROLES, EDITABLE_ROLES, ActionCandidate
from .focus import KEY_ALIASES, MODIFIERS, SINGLE_KEYS, input_and_menu_context


def focused_candidates(
    space, targets, accessibility_tree, proposals, blocked_action, verified_focus=None
):
    cp = "https://accessibility.ubuntu.example.org/ns/component"
    regions = {}
    input_controls, menu_paths = input_and_menu_context(accessibility_tree)
    focused_inputs = [item for item in input_controls if item["focused"]]
    focused_inputs = [item for item in focused_inputs if item["role"] != "table"] or focused_inputs
    if verified_focus:
        focused_inputs = [verified_focus]

    def bounds(element):
        origin = element.attrib.get(f"{{{cp}}}screencoord", "")
        size = element.attrib.get(f"{{{cp}}}size", "")
        numbers = [int(value) for value in re.findall(r"-?\d+", origin + size)]
        return tuple(numbers) if len(numbers) == 4 else None

    def walk(element, region=None):
        own = bounds(element)
        if element.tag in {"tree", "table", "list", "scroll-pane"} and own:
            region = (element.tag, own)
        elif (
            element.tag == "filler"
            and own
            and any(
                child.tag == "filler" and bounds(child) and bounds(child)[3] > own[3] for child in element
            )
        ):
            region = ("scroll area", own)
        if own and element.attrib.get("name"):
            regions[(element.attrib["name"], *own)] = region
        for child in element:
            walk(child, region)

    walk(ET.fromstring(accessibility_tree))
    by_id = {target.id: target for target in targets}
    chosen = []
    for index, proposal in enumerate(proposals[:2]):
        operation = str(proposal.get("operation") or proposal.get("op") or "").lower()
        name = str(proposal.get("target_name") or "").strip()
        role = str(proposal.get("target_role") or "").replace("-", "_").lower()
        target = by_id.get(str(proposal.get("target_id") or ""))
        if target and (target.name.casefold() != name.casefold() or target.role != role):
            target = None
        if operation == "type_text":
            text = proposal.get("text")
            mode = proposal.get("input_mode", "replace" if target else "insert")
            if not isinstance(text, str) or mode not in {"insert", "replace"}:
                continue
            raw_input = next(
                (
                    item
                    for item in input_controls
                    if target
                    and item["bounds"] == [target.x, target.y, target.width, target.height]
                    and item["role"] == target.role
                ),
                None,
            )
            if target and (
                target.role in EDITABLE_ROLES
                or raw_input
                and target.role in {"combo_box", "table_cell", "grid_cell"}
            ):
                chosen.append(
                    ActionCandidate(
                        id=f"type_text:{target.id}:{index}",
                        operation="type_text",
                        target_id=target.id,
                        description=f"{'Replace text in' if mode == 'replace' else 'Insert text into'} "
                        f'the {target.role.replace("_", " ")} "{target.name}" with {text[:160]!r}.',
                        metadata={
                            "semantic_key": target.semantic_key,
                            "text": text,
                            "input_mode": mode,
                            **(
                                {"focused_input": raw_input}
                                if raw_input
                                and raw_input["focused"]
                                and target.role not in {"table_cell", "grid_cell"}
                                else {}
                            ),
                        },
                    )
                )
            elif not proposal.get("target_id") and len(focused_inputs) == 1:
                focus = focused_inputs[0]
                if focus["role"] == "terminal" and mode != "insert":
                    continue
                if mode == "replace" and focus["role"] not in EDITABLE_ROLES | {"combo_box", "paragraph"}:
                    continue
                chosen.append(
                    ActionCandidate(
                        id=f"TYPE_FOCUSED:{index}",
                        operation="type_text",
                        description=f"{'Replace the text' if mode == 'replace' else 'Insert text'} "
                        f'in the focused {focus["role"]} "{focus["name"]}": {text[:160]!r}.',
                        source="global",
                        metadata={"text": text, "input_mode": mode, "focused_input": focus},
                    )
                )
            continue
        if operation in {"click", "double_click", "set_slider"}:
            if target is None:
                matching = [
                    item
                    for item in menu_paths
                    if item["name"].casefold() == name.casefold()
                    and (
                        not proposal.get("menu_path")
                        or item["path"].casefold() == proposal["menu_path"].casefold()
                    )
                ]
                if operation == "click" and role in {"menu", "menu_item"} and len(matching) == 1:
                    menu = matching[0]
                    chosen.append(
                        ActionCandidate(
                            id=f"MENU_KEY:{menu['path']}",
                            operation="keypress",
                            description=f'Open the "{menu["path"]}" menu path using its keyboard shortcut.',
                            source="global",
                            metadata={"key_sequence": menu["key_sequence"]},
                        )
                    )
                continue
            if (operation, target.semantic_key) == blocked_action:
                continue
            if operation == "double_click" and target.role not in DOUBLE_CLICK_ROLES | {"page_tab"}:
                continue
            if operation == "set_slider":
                value = proposal.get("value")
                if target.role != "slider" or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    continue
                chosen.append(
                    ActionCandidate(
                        id=f"set_slider:{target.id}:{value}",
                        operation="set_slider",
                        target_id=target.id,
                        description=f'Set the "{target.name}" slider to {value:.0%}.',
                        metadata={"semantic_key": target.semantic_key, "fraction": value},
                    )
                )
                continue
            if target.role == "slider":
                continue
            region = regions.get((target.name, target.x, target.y, target.width, target.height))
            if region and target.role not in {"menu", "menu_item"}:
                x, y, width, height = region[1]
                center_x = target.x + target.width // 2
                center_y = target.y + target.height // 2
                if not (x <= center_x < x + width and y <= center_y < y + height):
                    if x <= center_x < x + width:
                        direction = "down" if center_y >= y + height else "up"
                        chosen.append(
                            ActionCandidate(
                                id=f"SCROLL_{direction.upper()}:{target.id}",
                                operation="scroll",
                                description=f'Scroll {direction} inside the {region[0]} to reveal "{target.name}".',
                                metadata={"scroll_x": x + width // 2, "scroll_y": y + height // 2},
                            )
                        )
                    continue
            verb = {"click": "Click", "double_click": "Double-click"}[operation]
            metadata = {"semantic_key": target.semantic_key}
            chosen.append(
                ActionCandidate(
                    id=f"{operation}:{target.id}:{index}",
                    operation=operation,
                    target_id=target.id,
                    description=f'{verb} the visible {target.role.replace("_", " ")} "{target.name}".',
                    metadata=metadata,
                )
            )
        elif operation in {"scroll_up", "scroll_down"}:
            region = (
                regions.get((target.name, target.x, target.y, target.width, target.height))
                if target
                else None
            )
            if region:
                kind, (x, y, width, height) = region
                direction = "up" if operation == "scroll_up" else "down"
                chosen.append(
                    ActionCandidate(
                        id=f"SCROLL_{direction.upper()}:{target.id}",
                        operation="scroll",
                        description=f'Scroll {direction} inside the {kind} containing "{target.name}".',
                        metadata={"scroll_x": x + width // 2, "scroll_y": y + height // 2},
                    )
                )
            elif target and target.role not in {"menu", "menu_item"}:
                direction = "up" if operation == "scroll_up" else "down"
                chosen.append(
                    ActionCandidate(
                        id=f"SCROLL_{direction.upper()}:{target.id}",
                        operation="scroll",
                        description=f'Scroll {direction} over the visible {target.role.replace("_", " ")} "{target.name}".',
                        metadata={
                            "scroll_x": target.x + target.width // 2,
                            "scroll_y": target.y + target.height // 2,
                        },
                    )
                )
        elif operation == "keypress":
            raw = proposal.get("key_sequence")
            if (
                isinstance(raw, list)
                and 1 <= len(raw) <= 8
                and all(isinstance(keys, list) and 1 <= len(keys) <= 4 for keys in raw)
            ):
                sequence = [
                    [KEY_ALIASES.get(str(key).lower(), str(key).lower()) for key in keys] for keys in raw
                ]
                sequence = [
                    keys[:-1] + (["shift", "="] if "shift" not in keys else ["="])
                    if len(keys) > 1 and keys[-1] == "plus"
                    else keys
                    for keys in sequence
                ]
                valid = all(
                    all(key in SINGLE_KEYS | MODIFIERS for key in keys)
                    and (
                        len(keys) == 1
                        and keys[0] not in MODIFIERS - {"winleft"}
                        or len(keys) > 1
                        and all(key in MODIFIERS for key in keys[:-1])
                        and keys[-1] in SINGLE_KEYS
                    )
                    for keys in sequence
                )
                if any(
                    len(keys) == 1 and keys[0] in set("abcdefghijklmnopqrstuvwxyz0123456789")
                    for keys in sequence
                ) and any(item.focused and item.role in EDITABLE_ROLES for item in targets):
                    valid = False
                if any(keys == ["delete"] for keys in sequence) and not (
                    target and (target.focused or target.selected)
                ):
                    valid = False
                if not valid:
                    continue
                chosen.append(
                    ActionCandidate(
                        id="KEY_SEQUENCE:" + ":".join("+".join(keys) for keys in sequence),
                        operation="keypress",
                        description="Press " + " then ".join("+".join(keys) for keys in sequence) + ".",
                        source="global",
                        metadata={"key_sequence": sequence},
                    )
                )
        elif operation == "wait":
            chosen.append(space.controls["wait"])
    proposed_operations = {candidate.operation for candidate in chosen}
    for operation in ("click", "double_click", "keypress"):
        if operation not in proposed_operations:
            continue
        offered_targets = {
            candidate.target_id
            for candidate in chosen
            if candidate.operation == operation and candidate.target_id
        }
        for candidate in space.target_heads.get(operation, [])[:8]:
            if candidate.target_id and candidate.target_id in offered_targets:
                continue
            chosen.append(candidate)
    distinct = list({candidate.id: candidate for candidate in chosen}.values())[:18]
    space.target_heads = {"focused": distinct}
    space.controls = {
        key: value for key, value in space.controls.items() if key in {"visual_fallback", "return_to_planner"}
    }
    return space
