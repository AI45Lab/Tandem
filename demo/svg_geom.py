#!/usr/bin/env python3
"""SVG 几何与字体度量（流程图栅格化用）。

两件事：
- 路径解析：把 'M … L … C …' 拆成折线，交给 Pillow 画线；
- 字体度量：**按浏览器的方式**量文字宽度——`font-family: monospace` 没有中文
  字形时会回退到 CJK 字体，所以把文字切成 ASCII 段 / 中文段分别量、分别画。
  不这么做，量出来的宽度跟页面上的实际宽度对不上，出框就判不出来。

配色取的是 demo/web/assets/app.css 的浅色主题 token（变量名一一对应）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from PIL import ImageFont
except ImportError:  # pragma: no cover - 没 Pillow 就没法量字
    ImageFont = None  # type: ignore[assignment]

# ---------------------------------------------------------------- 配色（浅色主题 token）
BG = "#f4f6f9"
SURFACE_1 = "#ffffff"
SURFACE_2 = "#f1f4f8"
LINE = "#dbe2ea"
LINE_SOFT = "#eaeff4"
TEXT_1 = "#101a24"
TEXT_2 = "#4d5f72"
TEXT_3 = "#7c8b9c"
ACCENT = "#0a6fbd"
GOOD = "#14914f"
WARN = "#9a6b00"
SLOW = "#6d3fd1"
FAST = "#c25a12"

SANS_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)
SANS_BOLD_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
)
MONO_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
)

SCALE = 1.5
NODE_TEXT_SIZE = 15
SUB_TEXT_SIZE = 12
LABEL_TEXT_SIZE = 12


def first_existing(paths: tuple[str, ...]) -> str | None:
    for path in paths:
        if Path(path).is_file():
            return path
    return None


def load_font(size: int, bold: bool = False, mono: bool = False) -> Any:
    if ImageFont is None:
        return None
    if mono:
        path = first_existing(MONO_CANDIDATES)
    elif bold:
        path = first_existing(SANS_BOLD_CANDIDATES)
    else:
        path = first_existing(SANS_CANDIDATES)
    if path is None:
        return None
    return ImageFont.truetype(path, int(round(size * SCALE)))


# ---------------------------------------------------------------- 混排文字
def split_runs(text: str) -> list[tuple[str, str]]:
    """切成 ASCII 段与中文段。

    浏览器里 `font-family: monospace` 没有中文字形，会**回退**到 CJK 字体——
    排版和宽度都按这个来算，才跟页面一致。"""
    runs: list[list[str]] = []
    for ch in text:
        kind = "ascii" if ord(ch) < 128 else "cjk"
        if runs and runs[-1][0] == kind:
            runs[-1][1] += ch
        else:
            runs.append([kind, ch])
    return [(kind, value) for kind, value in runs]


def measure(text: str, ascii_font: Any, cjk_font: Any) -> float:
    total = 0.0
    for kind, run in split_runs(text):
        font = ascii_font if kind == "ascii" else cjk_font
        if font is not None:
            total += font.getlength(run)
    return total / SCALE


def draw_text(draw: Any, xy: tuple[float, float], text: str, ascii_font: Any,
              cjk_font: Any, fill: str, anchor: str = "ms") -> None:
    """按 run 逐段绘制（等宽段 + 中文段），保证与浏览器的混排一致。"""
    width = measure(text, ascii_font, cjk_font) * SCALE
    x, y = xy
    if anchor == "ms":
        x -= width / 2
    for kind, run in split_runs(text):
        font = ascii_font if kind == "ascii" else cjk_font
        if font is None:
            continue
        draw.text((x, y), run, font=font, fill=fill, anchor="ls")
        x += font.getlength(run)


# ---------------------------------------------------------------- 路径解析
def parse_path(d: str) -> list[list[tuple[float, float]]]:
    """把 'M … L … C …' 拆成若干段折线（MOVETO/LINETO/CURVETO 足够用了）。"""
    tokens = re.findall(r"[MLC]|-?\d+(?:\.\d+)?", d or "")
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    index = 0
    cmd = ""
    point = (0.0, 0.0)
    while index < len(tokens):
        token = tokens[index]
        if token in ("M", "L", "C"):
            cmd = token
            index += 1
            continue
        if cmd == "C":
            if index + 5 >= len(tokens) + 1:
                break
            try:
                values = [float(v) for v in tokens[index:index + 6]]
            except ValueError:
                break
            c1 = (values[0], values[1])
            c2 = (values[2], values[3])
            end = (values[4], values[5])
            current.extend(flatten_bezier(point, c1, c2, end))
            point = end
            index += 6
            cmd = "C"
            continue
        try:
            x = float(token)
            y = float(tokens[index + 1])
        except (ValueError, IndexError):
            break
        point = (x, y)
        if cmd == "M":
            if current:
                segments.append(current)
            current = [point]
            cmd = "L"
        else:
            current.append(point)
        index += 2
    if current:
        segments.append(current)
    return segments


def flatten_bezier(p0, p1, p2, p3, steps: int = 24) -> list[tuple[float, float]]:
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u ** 2 * t * p1[0] + 3 * u * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u ** 2 * t * p1[1] + 3 * u * t ** 2 * p2[1] + t ** 3 * p3[1]
        points.append((x, y))
    return points


# ---------------------------------------------------------------- 遍历
def walk(node: dict[str, Any], parent_class: str = "") -> list[tuple[dict[str, Any], str]]:
    items = [(node, parent_class)]
    own = node.get("class") or parent_class
    for child in node.get("children") or []:
        items.extend(walk(child, own))
    return items


def tone_of(css_class: str) -> str | None:
    for name, color in (("slow", SLOW), ("fast", FAST), ("fix", WARN),
                        ("done", GOOD), ("warn", WARN), ("good", GOOD),
                        ("accent", ACCENT), ("loopback", GOOD)):
        if name in css_class.split():
            return color
    return None


def collect(tree: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """把 SVG 拆成「网格 / 连线 / 节点框 / 节点字 / 标签胶囊 / 标签字」六类。"""
    out: dict[str, list[dict[str, Any]]] = {
        "grid": [], "edges": [], "flows": [], "boxes": [], "node_text": [],
        "label_rect": [], "label_text": [],
    }
    for node, parent_class in walk(tree):
        tag = node.get("tag")
        css = node.get("class") or ""
        attrs = node.get("attrs") or {}
        if tag == "line" and "fgrid" in parent_class:
            out["grid"].append(attrs)
        elif tag == "path" and "fedge-line" in css:
            out["edges"].append({"d": attrs.get("d", ""), "tone": tone_of(parent_class)})
        elif tag == "path" and "fedge-flow" in css:
            out["flows"].append({"d": attrs.get("d", ""), "tone": tone_of(parent_class)})
        elif tag == "rect" and "fnode-box" in css:
            out["boxes"].append({"attrs": attrs, "tone": tone_of(parent_class)})
        elif tag == "rect" and "fedge-label" in parent_class:
            out["label_rect"].append({"attrs": attrs, "tone": tone_of(parent_class)})
        elif tag == "text" and "fnode" in parent_class:
            out["node_text"].append({
                "text": node.get("text", ""),
                "x": float(attrs.get("x", 0)), "y": float(attrs.get("y", 0)),
                "anchor": attrs.get("text-anchor", "start"),
                "sub": "fnode-sub" in css,
            })
        elif tag == "text" and "fedge-label" in parent_class:
            out["label_text"].append({
                "text": node.get("text", ""),
                "x": float(attrs.get("x", 0)), "y": float(attrs.get("y", 0)),
                "anchor": attrs.get("text-anchor", "start"),
                "tone": tone_of(parent_class),
            })
    return out
