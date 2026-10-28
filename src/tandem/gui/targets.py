"""a11y tree → UITarget 列表；从旧仓库 gui/ui_target.py + a11y_target_builder.py 按契约移植。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class UITarget:
    id: str
    snapshot_id: str
    role: str
    name: str
    value: str
    enabled: bool | None
    visible: bool | None
    showing: bool | None
    selected: bool | None
    checked: bool | None
    focused: bool | None
    x: int | None
    y: int | None
    width: int | None
    height: int | None
    semantic_key: str
    parent_context: tuple[str, ...]
    source: str = "a11y"

    def compact(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value not in (None, "", (), False)}

    def contains(self, x: int, y: int) -> bool:
        return (
            self.x is not None
            and self.y is not None
            and self.width is not None
            and self.height is not None
            and self.x <= x < self.x + self.width
            and self.y <= y < self.y + self.height
        )


SUPPORTED_ROLES = {
    "button",
    "push_button",
    "checkbox",
    "check_box",
    "radio_button",
    "textbox",
    "text",
    "entry",
    "searchbox",
    "password_text",
    "combo_box",
    "menu",
    "menu_item",
    "tab",
    "page_tab",
    "link",
    "toggle_button",
    "switch",
    "spin_button",
    "icon",
    "list_item",
    "tree_item",
    "table_cell",
    "grid_cell",
    "option",
}


def _local(value: str) -> str:
    return value.rsplit("}", 1)[-1].replace("-", "_").lower()


def _state(element: ET.Element, name: str) -> bool | None:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return str(value).lower() == "true"
    return None


def _pair(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)", value or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _attribute(element: ET.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return str(value)
    return ""


class A11yTargetBuilder:
    def build(
        self,
        raw_tree: str,
        snapshot_id: str,
        max_targets: int = 64,
        infer_button_labels: bool = False,
        include_sliders: bool = False,
    ) -> list[UITarget]:
        root = ET.fromstring(raw_tree)
        targets: list[UITarget] = []

        def visit(element: ET.Element, active: bool, parents: tuple[str, ...]) -> None:
            active = active or _state(element, "active") is True
            role = _local(element.tag)
            name = str(element.attrib.get("name") or "").strip()
            value = (
                str(element.text or "").strip()
                if role in {"text", "textbox", "entry", "searchbox", "password_text", "spin_button"}
                else ""
            )
            position = _pair(_attribute(element, "screencoord"))
            size = _pair(_attribute(element, "size"))
            if infer_button_labels and not name and role in {"button", "push_button"} and position and size:
                labels = {
                    str(child.attrib.get("name") or "").strip()
                    for child in element.iter()
                    if _local(child.tag) == "label" and child.attrib.get("name")
                }
                if len(labels) == 1:
                    name = labels.pop()
            enabled = _state(element, "enabled")
            visible = _state(element, "visible")
            showing = _state(element, "showing")
            if (
                not name
                and active
                and role in {"textbox", "text", "entry", "searchbox", "password_text", "spin_button"}
                and _state(element, "editable") is True
                and _state(element, "focused") is True
                and position
                and size
            ):
                name = f"Focused {role.replace('_', ' ')}" + (f" (current: {value})" if value else "")
            context = parents + ((name,) if name else ())
            interactive_text = role != "text" or (
                _state(element, "editable") is True or _state(element, "focusable") is True
            )
            system_target = "gnome-shell" in {item.lower() for item in parents}
            safe_label = (
                role == "label"
                and active
                and (
                    any("file chooser" in item.lower() or item.lower() == "places" for item in parents)
                    or bool(
                        re.search(
                            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", name, re.I
                        )
                    )
                )
            )
            if (
                (active or system_target)
                and (role in SUPPORTED_ROLES or safe_label or (include_sliders and role == "slider"))
                and name
                and interactive_text
                and enabled is not False
                and visible is not False
                and showing is not False
                and position
                and size
                and size[0] > 0
                and size[1] > 0
                and len(targets) < max_targets
            ):
                normalized_name = " ".join(name.lower().split())
                parent_context = tuple(item for item in parents[-3:] if item)
                targets.append(
                    UITarget(
                        id=f"a11y:{snapshot_id}:{len(targets)}",
                        snapshot_id=snapshot_id,
                        role=role,
                        name=name,
                        value=value,
                        enabled=enabled,
                        visible=visible,
                        showing=showing,
                        selected=_state(element, "selected"),
                        checked=_state(element, "checked"),
                        focused=_state(element, "focused"),
                        x=position[0],
                        y=position[1],
                        width=size[0],
                        height=size[1],
                        semantic_key="|".join((role, normalized_name, *[p.lower() for p in parent_context])),
                        parent_context=parent_context,
                    )
                )
            for child in element:
                visit(child, active, context[-4:])

        visit(root, False, ())
        return targets
