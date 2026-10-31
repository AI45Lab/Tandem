"""Current-observation action space for a whole GUI subgoal; no planner click whitelist."""

import json
import re
import xml.etree.ElementTree as ET

from .candidates import ActionCandidate
from .focus import input_and_menu_context
from .targets import _attribute, _local, _pair, _state


def matches_field(hint, label):
    """Match an intended field to its observed label, not an arbitrary focused control."""
    def words(value):
        return set(re.findall(r"\w+", value.casefold())) - {"the", "a", "field", "required"}

    observed = words(label)
    return bool(observed) and observed <= words(hint) and not label.startswith(("Unnamed ", "Focused "))


def scroll_point(tree, viewport):
    """Anchor wheel events inside the observed foreground window, not the desktop center."""
    windows = []
    for element in ET.fromstring(tree or "<empty/>").iter():
        if _local(element.tag) not in {"frame", "dialog"} or _state(element, "active") is not True:
            continue
        position = _pair(_attribute(element, "screencoord"))
        size = _pair(_attribute(element, "size"))
        if position and size and size[0] > 0 and size[1] > 0:
            windows.append((*position, *size))
    x, y, width, height = windows[-1] if windows else (0, 0, *viewport)
    return (max(0, min(viewport[0] - 1, x + width * 3 // 5)),
            max(0, min(viewport[1] - 1, y + height // 2)))


def foreground_tree(raw_tree):
    """GNOME's visible app menu disambiguates stale ACTIVE flags on background windows."""
    root = ET.fromstring(raw_tree)
    apps = list(root)
    shell = next((a for a in apps if a.get("name") == "gnome-shell"), None)
    if shell is None:
        return raw_tree
    overview = [e for e in shell.iter() if e.get("name") == "Overview"]
    search_visible = any(
        _state(e, "editable") is True and _state(e, "showing") is True
        and _pair(_attribute(e, "screencoord")) and _pair(_attribute(e, "size"))
        for panel in overview for e in panel.iter())
    if search_visible:
        # X11 still names the old window while GNOME's full-screen overview owns input.
        for app in apps:
            if app is not shell:
                root.remove(app)
        shell.set("active", "true")
        root.set("foreground_title", "GNOME Overview")
        root.set("foreground_class", '["gnome-shell"]')
        return ET.tostring(root, encoding="unicode")
    if root.get("foreground_class"):
        def normalize(value):
            return re.sub(r"[^a-z0-9]", "", value.casefold())

        def active(element, value):
            key = next((k for k in element.attrib if _local(k) == "active"), "active")
            element.set(key, "true" if value else "false")

        classes = [normalize(v) for v in json.loads(root.get("foreground_class")) if v]
        title = root.get("foreground_title", "")
        for app in apps:
            matching = (any(normalize(app.get("name", "")).endswith(c) for c in classes)
                        or bool(title) and any(e.get("name") == title for e in app.iter()
                                              if _local(e.tag) in {"frame", "dialog"}))
            if app is not shell and not matching:
                root.remove(app)
            elif app is not shell:
                windows = [e for e in app.iter() if _local(e.tag) in {"frame", "dialog"}]
                named = [e for e in windows if title and e.get("name") == title]
                if named:
                    active(app, False)
                    for window in windows:
                        active(window, window in named)
        return ET.tostring(root, encoding="unicode")
    names = []
    for element in shell.iter():
        attrs = {k.rsplit("}", 1)[-1]: v for k, v in element.attrib.items()}
        position = re.findall(r"-?\d+", attrs.get("screencoord", ""))
        if (element.tag.rsplit("}", 1)[-1] == "menu" and attrs.get("name")
                and attrs.get("showing") == "true" and len(position) == 2
                and 0 <= int(position[1]) < 32):
            names.append(attrs["name"].casefold())
    matches = [app for app in apps if app is not shell and any(
        name in e.get("name", "").casefold() for e in app.iter()
        if e.tag.rsplit("}", 1)[-1] in {"frame", "dialog"} for name in names)]
    if len(matches) != 1:
        return raw_tree
    for app in apps:
        if app is not shell and app is not matches[0]:
            root.remove(app)
    return ET.tostring(root, encoding="unicode")


def goal_candidates(space, targets, tree, inputs, viewport=(1920, 1080)):
    _, menus = input_and_menu_context(tree or "<empty/>")
    fields = [t for t in targets if t.role in {"text", "textbox", "entry", "searchbox", "spin_button"}]
    typed = []
    for index, value in enumerate(inputs):
        hint = value.get("target_hint", value["label"])
        matching = [t for t in fields if matches_field(hint, t.name)]
        if len(matching) != 1:
            continue  # Ambiguous/unlabelled fields need an observed click or visual grounding first.
        target = matching[0]
        if (target.value == value["text"] or value["input_mode"] == "insert"
                and value["text"] in target.value):
            continue
        typed.append(ActionCandidate(
            id=f"GOAL_TEXT:{index}", operation="type_text", source="goal_input", target_id=target.id,
            description=f"{value['input_mode']} the observed field {target.name!r} with the "
                        f"supplied {value['label']}: {value['text']!r}",
            metadata={"text": value["text"], "input_mode": value["input_mode"],
                      "target_hint": hint, "field_label": target.name,
                      "semantic_key": target.semantic_key},
        ))
    space.target_heads["type_text"] = typed
    unnamed_entries = [t for t in targets if t.name.startswith(("Unnamed ", "Focused "))
                       and t.role in {"text", "textbox", "entry", "searchbox"}][:2]
    present = {c.target_id for c in space.target_heads["click"]}
    space.target_heads["click"] = [ActionCandidate(
        id="FOCUS:" + t.id, operation="click", target_id=t.id, source="a11y",
        description=f"Focus the observed {t.name!r} in {' / '.join(t.parent_context)} before typing.",
        metadata={"semantic_key": t.semantic_key}) for t in unnamed_entries if t.id not in present
    ] + space.target_heads["click"]
    native_files = [t for t in targets if t.role in {"canvas", "label"}
                    and "nautilus" in (t.application + " ".join(t.parent_context)).lower()][:4]
    space.target_heads["double_click"].extend(ActionCandidate(
        id="OPEN:" + t.id, operation="double_click", target_id=t.id, source=t.source,
        description=f"Open the observed file-manager item {t.name!r}.",
        metadata={"semantic_key": t.semantic_key}) for t in native_files)
    sliders = [t for t in targets if t.role == "slider"][:2]
    space.target_heads["set_slider"] = [ActionCandidate(
        id=f"SLIDER:{t.id}:{fraction}", operation="set_slider", target_id=t.id,
        description=f"Set {t.name!r} to {fraction:.0%} of its range"
                    + (f" (value {t.range_min + fraction * (t.range_max - t.range_min):.2f})"
                       if t.range_min is not None and t.range_max is not None else "")
                    + f"; current observed value: {t.value or 'unknown'}.",
        metadata={"fraction": fraction, "semantic_key": t.semantic_key})
        for t in sliders for fraction in (0.1, 0.25, 0.5, 0.75, 0.9)
        if (not t.value or t.range_min is None or t.range_max is None
            or abs(float(t.value) - (t.range_min + fraction * (t.range_max - t.range_min)))
            > max(1e-6, (t.range_max - t.range_min) * 0.02))]
    # A slider's default center click is ambiguous and was repeatedly seeking to the same midpoint.
    slider_ids = {t.id for t in sliders}
    space.target_heads["click"] = [c for c in space.target_heads["click"] if c.target_id not in slider_ids]
    space.target_heads["right_click"] = [ActionCandidate(
        id="RIGHT:" + c.target_id, operation="right_click", source=c.source, target_id=c.target_id,
        description="Open the context menu for " + c.description,
        metadata=dict(c.metadata)) for c in space.target_heads["click"][:8]]
    sx, sy = scroll_point(tree, viewport)
    for candidate in space.target_heads["scroll"]:
        candidate.metadata.update(scroll_x=sx, scroll_y=sy)
    for menu in menus[:16]:
        space.target_heads["keypress"].append(ActionCandidate(
            id="MENU_KEY:" + menu["path"], operation="keypress", source="a11y_menu",
            description="Open the observed menu path " + menu["path"],
            metadata={"key_sequence": menu["key_sequence"]}))
    space.target_heads["keypress"].extend(ActionCandidate(
        id="GOAL_KEY:" + "+".join(keys), operation="keypress", source="global",
        description=description, metadata={"key_sequence": [keys]}) for keys, description in [
            (["ctrl", "s"], "Save the current document."),
            (["ctrl", "o"], "Open the application's file chooser for an existing document."),
            (["alt", "tab"], "Switch away from the foreground window to another open application."),
            (["shift", "f10"], "Open the focused object's context menu."),
            (["ctrl", "l"], "Focus the browser or native file-dialog location field."),
            (["ctrl", "f"], "Open the current application's Find field."),
            (["shift", "tab"], "Move focus to the previous field."),
            (["down"], "Move down in the current selection or menu."),
            (["up"], "Move up in the current selection or menu."),
            (["right"], "Move right in the current selection, calendar or menu."),
            (["left"], "Move left in the current selection, calendar or menu."),
        ])
    space.controls = {k: v for k, v in space.controls.items()
                      if k in {"wait", "done", "visual_fallback", "return_to_planner"}}
    space.controls["done"] = ActionCandidate(
        id="STAGE_DONE", operation="done", source="stage_control",
        description="The current subtask's completion criteria are satisfied. Request ONE independent "
                    "stage verification; this does not finish the original task.")
    space.controls["return_to_planner"].description = (
        "The current subtask needs unavailable information, new reasoning or an unsupported operation. "
        "Return control with existing progress preserved; do not repeat an ineffective action.")
    return space
