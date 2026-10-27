#!/usr/bin/env python3
"""把流程图 SVG 栅格化成 PNG，并按**真实字体度量**判定「字出框 / 标签压字」。

背景：本机没有浏览器，截图 smoke 做不了。但用户指出的「框中字体超出了、
摆放位置不对」是能被机器判定的——只要拿真实字体（Noto Sans CJK）量一遍文字
宽度，再和 SVG 里框/胶囊的实际宽度比。

输入是 `tests/demo/flow_svg_dump.js` 导出的 JSON（首页真实渲染出来的 SVG）。

用法：
    node tests/demo/flow_svg_dump.js <overview> <compare> <episode> <site> /tmp/flow.json
    python3 demo/render_svg.py /tmp/flow.json --out /tmp/flow.png
    python3 demo/render_svg.py /tmp/flow.json --check-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - 没 Pillow 就只能做几何检查
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

from demo.svg_geom import (  # noqa: E402
    ACCENT,
    BG,
    LABEL_TEXT_SIZE,
    LINE,
    LINE_SOFT,
    NODE_TEXT_SIZE,
    SCALE,
    SUB_TEXT_SIZE,
    SURFACE_1,
    SURFACE_2,
    TEXT_1,
    TEXT_2,
    TEXT_3,
    collect,
    draw_text,
    load_font,
    measure,
    parse_path,
)


# ---------------------------------------------------------------- 度量检查
def text_width(font: Any, text: str) -> float:
    if font is None or not text:
        return 0.0
    return font.getlength(text) / SCALE


def check_overflow(parts: dict[str, list[dict[str, Any]]]) -> list[str]:
    problems: list[str] = []
    sans = load_font(NODE_TEXT_SIZE)
    sans_bold = load_font(NODE_TEXT_SIZE, bold=True)
    mono = load_font(SUB_TEXT_SIZE, mono=True)
    label_font = load_font(LABEL_TEXT_SIZE)

    for item in parts["node_text"]:
        if item["sub"]:
            width = measure(item["text"], mono, sans)
        else:
            width = text_width(sans_bold, item["text"])
        # 逐个节点匹配：按 y 落在哪个框的垂直区间里
        for box in parts["boxes"]:
            attrs = box["attrs"]
            top = float(attrs.get("y", 0))
            height = float(attrs.get("height", 0))
            if not (top <= item["y"] <= top + height):
                continue
            limit = float(attrs.get("width", 0)) - 22
            if width > limit + 0.5:
                problems.append(
                    f"节点文字「{item['text']}」宽 {width:.1f} > "
                    f"框宽 {float(attrs.get('width', 0)):.1f}（余量 {limit:.1f}）")
            break

    for index, item in enumerate(parts["label_text"]):
        width = text_width(label_font, item["text"])
        if index >= len(parts["label_rect"]):
            continue
        rect = parts["label_rect"][index]["attrs"]
        limit = float(rect.get("width", 0))
        if width + 18 > limit + 0.5:
            problems.append(
                f"连线标签「{item['text']}」宽 {width:.1f} + 18 > 胶囊宽 {limit:.1f}")
    return problems


def check_overlap(parts: dict[str, list[dict[str, Any]]]) -> list[str]:
    problems: list[str] = []
    boxes = []
    for box in parts["boxes"]:
        attrs = box["attrs"]
        boxes.append((
            float(attrs.get("x", 0)), float(attrs.get("y", 0)),
            float(attrs.get("width", 0)), float(attrs.get("height", 0)),
        ))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            ax, ay, aw, ah = boxes[i]
            bx, by, bw, bh = boxes[j]
            if ax < bx + bw - 0.5 and bx < ax + aw - 0.5 and ay < by + bh - 0.5 and by < ay + ah - 0.5:
                problems.append(f"节点框 #{i} 与 #{j} 重叠")
    labels = []
    for rect in parts["label_rect"]:
        attrs = rect["attrs"]
        labels.append((
            float(attrs.get("x", 0)), float(attrs.get("y", 0)),
            float(attrs.get("width", 0)), float(attrs.get("height", 0)),
        ))
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            ax, ay, aw, ah = labels[i]
            bx, by, bw, bh = labels[j]
            if ax < bx + bw - 0.5 and bx < ax + aw - 0.5 and ay < by + bh - 0.5 and by < ay + ah - 0.5:
                problems.append(f"连线标签 #{i} 与 #{j} 互相压字")
    return problems


# ---------------------------------------------------------------- 绘制
def render(parts: dict[str, list[dict[str, Any]]], view_w: int, view_h: int) -> Any:
    image = Image.new("RGB", (int(view_w * SCALE), int(view_h * SCALE)), BG)
    draw = ImageDraw.Draw(image)

    def s(value: float) -> float:
        return value * SCALE

    for line in parts["grid"]:
        draw.line([s(float(line.get("x1", 0))), s(float(line.get("y1", 0))),
                   s(float(line.get("x2", 0))), s(float(line.get("y2", 0)))],
                  fill=LINE_SOFT, width=1)

    for edge in parts["edges"]:
        color = edge["tone"] or LINE
        for segment in parse_path(edge["d"]):
            points = [(s(x), s(y)) for x, y in segment]
            if len(points) > 1:
                draw.line(points, fill=color, width=2)

    for flow in parts["flows"]:
        color = flow["tone"] or ACCENT
        for segment in parse_path(flow["d"]):
            points = [(s(x), s(y)) for x, y in segment]
            if len(points) > 1:
                draw.line(points, fill=color, width=3, joint="curve")

    for box in parts["boxes"]:
        attrs = box["attrs"]
        x = s(float(attrs.get("x", 0)))
        y = s(float(attrs.get("y", 0)))
        w = s(float(attrs.get("width", 0)))
        h = s(float(attrs.get("height", 0)))
        radius = s(float(attrs.get("rx", 10)))
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                               fill=SURFACE_1, outline=box["tone"] or LINE, width=2)

    for rect in parts["label_rect"]:
        attrs = rect["attrs"]
        x = s(float(attrs.get("x", 0)))
        y = s(float(attrs.get("y", 0)))
        w = s(float(attrs.get("width", 0)))
        h = s(float(attrs.get("height", 0)))
        draw.rounded_rectangle([x, y, x + w, y + h], radius=s(h / 2),
                               fill=SURFACE_2, outline=rect["tone"] or LINE, width=2)

    label_font = load_font(LABEL_TEXT_SIZE)
    for item in parts["label_text"]:
        font = label_font
        anchor = "ms" if item["anchor"] == "middle" else "ls"
        draw.text((s(item["x"]), s(item["y"])), item["text"], font=font,
                  fill=item["tone"] or TEXT_2, anchor=anchor)

    bold = load_font(NODE_TEXT_SIZE, bold=True)
    mono = load_font(SUB_TEXT_SIZE, mono=True)
    plain = load_font(NODE_TEXT_SIZE)
    for item in parts["node_text"]:
        anchor = "ms" if item["anchor"] == "middle" else "ls"
        if item["sub"]:
            draw_text(draw, (s(item["x"]), s(item["y"])), item["text"],
                      mono, plain, TEXT_3, anchor)
        else:
            draw.text((s(item["x"]), s(item["y"])), item["text"], font=bold,
                      fill=TEXT_1, anchor=anchor)
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="流程图 SVG 栅格化 + 出框检查")
    parser.add_argument("svg_json", type=Path, help="flow_svg_dump.js 导出的 JSON")
    parser.add_argument("--out", type=Path, default=None, help="PNG 输出路径")
    parser.add_argument("--check-only", action="store_true", help="只检查不出图")
    args = parser.parse_args(argv)

    tree = json.loads(args.svg_json.read_text(encoding="utf-8"))
    parts = collect(tree)

    problems = check_overflow(parts) + check_overlap(parts)
    if problems:
        print(f"[svg] 发现 {len(problems)} 处版式问题：")
        for item in problems:
            print(f"  - {item}")
    else:
        print("[svg] 版式检查通过：无出框、无重叠。")

    if not args.check_only:
        if Image is None:
            print("[svg] 没有 Pillow，跳过出图（只做了几何检查）")
            return 0 if not problems else 1
        attrs = tree.get("attrs") or {}
        view_w = int(float(attrs.get("viewBox", "0 0 1360 400").split()[2]))
        view_h = int(float(attrs.get("viewBox", "0 0 1360 400").split()[3]))
        image = render(parts, view_w, view_h)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.out)
        print(f"[svg] 已出图 {args.out}（{image.width}x{image.height}）")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
