"""Shared semantic element table for the slow planner and fast selector."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import replace

from .targets import UITarget

_LABEL_ROLES = {"label", "static", "text"}
_MEMORY_USAGE = re.compile(r"\s+-\s+Memory usage\s+-\s+[\d.]+\s+[KMG]B\b", re.I)


def _norm(value: str) -> str:
    return " ".join(_MEMORY_USAGE.sub("", value or "").lower().split())


def _key(target: UITarget) -> str:
    return "|".join((target.role, _norm(target.name), *(_norm(p) for p in target.parent_context)))


def _bounds(element: ET.Element) -> tuple[int, int, int, int] | None:
    attrs = {key.rsplit("}", 1)[-1]: value for key, value in element.attrib.items()}
    values = [int(v) for v in re.findall(r"-?\d+", attrs.get("screencoord", "") + attrs.get("size", ""))]
    return tuple(values) if len(values) == 4 else None


def _a11y_context(root: ET.Element | None) -> tuple[list[dict], bool]:
    if root is None:
        return [], True
    labels = []
    chrome_active = False

    def active(element: ET.Element) -> bool:
        return any(
            key.rsplit("}", 1)[-1] == "active" and value == "true"
            for key, value in element.attrib.items()
        )

    for app in root:
        app_active = active(app) or any(active(child) for child in app)
        chrome_active = chrome_active or (
            app_active and "chrome" in app.attrib.get("name", "").lower()
        )
    for element in root.iter():
        role = element.tag.rsplit("}", 1)[-1].replace("-", "_")
        if role not in _LABEL_ROLES:
            continue
        box = _bounds(element)
        text = " ".join((element.attrib.get("name") or element.text or "").split())
        if box and text and len(text) <= 120:
            x, y, width, height = box
            labels.append({"text": text, "box": box, "cx": x + width / 2, "cy": y + height / 2})
    return labels, chrome_active


def _nearest_label(target: UITarget, labels: list[dict]) -> str:
    if None in (target.x, target.y, target.width, target.height):
        return ""
    cx, cy = target.x + target.width / 2, target.y + target.height / 2
    best, best_score = "", float("inf")
    for item in labels:
        x, y, width, height = item["box"]
        left = x + width <= target.x + 4 and abs(item["cy"] - cy) <= max(14, target.height)
        above = y + height <= target.y + 4 and x + width >= target.x and x <= target.x + target.width
        if not left and not above:
            continue
        score = (
            target.x - x - width + abs(item["cy"] - cy)
            if left
            else 1000 + target.y - y - height + abs(item["cx"] - cx) / 4
        )
        if score < best_score:
            best, best_score = item["text"], score
    return best


def _content_y(targets: list[UITarget], snapshot: dict | None) -> float:
    if snapshot and snapshot.get("viewport", {}).get("screen_y") is not None:
        return float(snapshot["viewport"]["screen_y"])
    address = next((item for item in targets if item.name == "Address and search bar"), None)
    if address and address.y is not None and address.height is not None:
        return address.y + address.height + 8
    return 110.0


def _scope(target: UITarget, content_y: float) -> str:
    if target.role in {"menu", "menu_item"}:
        return "menu"
    parents = " ".join(target.parent_context).lower()
    if any(word in parents for word in ("dialog", "file chooser", "restore pages")):
        return "dialog"
    application = target.application.lower()
    if "chrome" not in application and "chromium" not in application:
        return "native"
    if target.y is not None and target.height is not None and target.y + target.height / 2 >= content_y:
        return "web_content"
    return "browser_chrome"


def _overlap(a: UITarget, b: UITarget) -> float:
    wide = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    tall = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    smaller = min(a.width * a.height, b.width * b.height)
    return wide * tall / smaller if wide > 0 and tall > 0 and smaller > 0 else 0.0


def _roles_compatible(a: str, b: str) -> bool:
    groups = (
        {"button", "push_button", "toggle_button"},
        {"text", "textbox", "entry", "searchbox", "password_text"},
        {"tab", "page_tab"},
        {"checkbox", "check_box"},
        {"table_cell", "grid_cell"},
    )
    return a == b or any(a in group and b in group for group in groups)


def _dom_target(item: dict, snapshot_id: str) -> UITarget | None:
    try:
        x, y = round(float(item["x"])), round(float(item["y"]))
        width, height = round(float(item["width"])), round(float(item["height"]))
        name = str(item["name"]).strip()
    except (KeyError, TypeError, ValueError):
        return None
    if not name or width < 2 or height < 2:
        return None
    target = UITarget(
        id=f"dom:{snapshot_id}:{item.get('index', 0)}",
        snapshot_id=snapshot_id,
        role=str(item.get("role") or "unknown"),
        name=name,
        value=str(item.get("value") or ""),
        enabled=True,
        visible=True,
        showing=True,
        selected=item.get("selected"),
        checked=item.get("checked"),
        focused=None,
        x=x,
        y=y,
        width=width,
        height=height,
        semantic_key="",
        parent_context=(),
        source="dom",
        application="Google Chrome",
        description=str(item.get("description") or ""),
        nearby_text=str(item.get("nearby_text") or ""),
        scope="web_content",
        label_source=str(item.get("label_source") or "dom"),
        operations=tuple(item.get("operations") or ("click",)),
    )
    return replace(target, semantic_key=_key(target))


def _merge(base: UITarget, dom: UITarget) -> UITarget:
    use_dom_name = (
        dom.label_source != "dom"
        or base.label_source == "unresolved"
        or len(dom.name) >= len(base.name)
    )
    merged = replace(
        base,
        name=dom.name if use_dom_name else base.name,
        value=dom.value or base.value,
        checked=dom.checked if dom.checked is not None else base.checked,
        selected=dom.selected if dom.selected is not None else base.selected,
        source="a11y+dom",
        description=dom.description or base.description,
        nearby_text=dom.nearby_text or base.nearby_text,
        scope="web_content",
        label_source=dom.label_source,
        operations=dom.operations,
    )
    return replace(merged, semantic_key=_key(merged))


def enrich_targets(
    targets: list[UITarget],
    accessibility_tree: str | None,
    screen_size: tuple[int, int],
    browser_snapshot: dict | None = None,
) -> list[UITarget]:
    """Recover labels, classify scope, and merge DOM semantics without adding screen OCR."""
    try:
        root = ET.fromstring(accessibility_tree) if accessibility_tree else None
    except ET.ParseError:
        root = None
    labels, chrome_active = _a11y_context(root)
    content_y = _content_y(targets, browser_snapshot)
    enriched = []
    for target in targets:
        name, source = target.name, target.label_source
        if target.role == "page_tab":
            name = _MEMORY_USAGE.sub("", name)
        nearby = target.nearby_text or _nearest_label(target, labels)
        if not name and nearby:
            name, source = nearby, "a11y_nearby"
        if not name and target.focused:
            name, source = f"Focused {target.role.replace('_', ' ')}", "synthetic"
        if not name:
            continue
        item = replace(
            target,
            name=name,
            nearby_text=nearby,
            scope=_scope(target, content_y),
            label_source=source,
        )
        enriched.append(replace(item, semantic_key=_key(item)))
    if browser_snapshot and chrome_active:
        snapshot_id = targets[0].snapshot_id if targets else "dom"
        for raw in browser_snapshot.get("elements", []):
            dom = _dom_target(raw, snapshot_id)
            if dom is None:
                continue
            compatible = [
                (index, _overlap(base, dom))
                for index, base in enumerate(enriched)
                if _roles_compatible(base.role, dom.role)
            ]
            best = max(compatible, key=lambda pair: pair[1], default=(None, 0.0))
            if best[0] is not None and best[1] >= 0.5:
                enriched[best[0]] = _merge(enriched[best[0]], dom)
            else:
                enriched.append(dom)
    unique = {}
    for target in enriched:
        center_x = target.x + target.width / 2
        center_y = target.y + target.height / 2
        if not (0 <= center_x < screen_size[0] and 0 <= center_y < screen_size[1]):
            continue
        key = (
            target.role, _norm(target.name), round(target.x), round(target.y),
            round(target.width), round(target.height),
        )
        current = unique.get(key)
        if current is None or current.source == "a11y" and target.source != "a11y":
            unique[key] = target
    return list(unique.values())
