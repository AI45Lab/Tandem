"""截图帧处理（构建期）。

Pillow 是仓库白名单内唯一运行时依赖，且这里只用于**构建期**缩放；
Pillow 缺失或单帧不可解码时退化为原样拷贝，不中断整站构建。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

try:  # pragma: no cover - 构建机无 Pillow 时走退化分支
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

FRAME_WIDTH = 1280
FRAME_QUALITY = 72
THUMB_WIDTH = 320


def process_frames(episode_dir: Path, dest_dir: Path) -> dict[str, Any]:
    """把 episode 的截图缩放成网页可用帧。

    返回 {原文件名: 站点内文件名} 映射。帧不可解码时原样拷贝（保留 .png 后缀）。
    """
    shots = episode_dir / "screenshots"
    if not shots.is_dir():
        return {}
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, Any] = {}
    for shot in sorted(shots.glob("step_*.png")):
        target = dest_dir / f"{shot.stem}.jpg"
        if Image is not None:
            try:
                with Image.open(shot) as image:
                    if image.width > FRAME_WIDTH:
                        height = round(image.height * FRAME_WIDTH / image.width)
                        image = image.resize((FRAME_WIDTH, height), Image.LANCZOS)
                    image.convert("RGB").save(target, "JPEG", quality=FRAME_QUALITY, optimize=True)
                mapping[shot.name] = target.name
                continue
            except OSError:
                pass
        fallback = dest_dir / f"{shot.stem}.png"
        shutil.copyfile(shot, fallback)
        mapping[shot.name] = fallback.name
    return mapping


def make_thumbnail(frame_path: Path, target: Path) -> bool:
    """首帧缩略图（任务卡片用）；失败返回 False（不影响站点构建）。"""
    if Image is None:
        shutil.copyfile(frame_path, target)
        return True
    try:
        with Image.open(frame_path) as image:
            if image.width > THUMB_WIDTH:
                height = round(image.height * THUMB_WIDTH / image.width)
                image = image.resize((THUMB_WIDTH, height), Image.LANCZOS)
            image.convert("RGB").save(target, "JPEG", quality=70, optimize=True)
        return True
    except OSError:
        return False
