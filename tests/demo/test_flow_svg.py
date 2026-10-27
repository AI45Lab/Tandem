"""流程图的**视觉 smoke**：用真实字体度量判定「字出框 / 标签压字」。

**为什么要有这个**：本机没有浏览器，截图 smoke 做不了。但「框里字超出」「摆放
位置不对」是能被机器判定的——拿真实字体（Noto Sans CJK + 等宽）量一遍文字宽度，
再和 SVG 里框与胶囊的实际宽度比。

链路：
    tests/demo/flow_svg_dump.js  首页真实渲染出的流程图 → JSON
    demo/render_svg.py            JSON → PNG + 版式问题清单

node 或 Pillow 缺失就跳过（CI 可能两者都没有）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DUMP = REPO_ROOT / "tests" / "demo" / "flow_svg_dump.js"
RENDER = REPO_ROOT / "demo" / "render_svg.py"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node 不在 PATH，跳过流程图视觉 smoke")


def _has_pillow(python: str) -> bool:
    return subprocess.run(
        [python, "-c", "import PIL"],
        capture_output=True, check=False,
    ).returncode == 0


def _python_with_pillow() -> str | None:
    """找一个装了 Pillow 的解释器。

    Pillow 是仓库白名单里唯一的依赖，但**构建机上的 venv 可能没装**——
    那就退到系统 python3（本机 /usr/bin/python3 有 Pillow 9.x）。
    """
    candidates = [sys.executable, shutil.which("python3"), "/usr/bin/python3"]
    for candidate in candidates:
        if candidate and Path(candidate).exists() and _has_pillow(candidate):
            return candidate
    return None


PILLOW_PYTHON = _python_with_pillow()


def _build_site(tmp_path: Path) -> Path:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "demo"))
    from helpers import make_contract_episode, make_contract_run  # noqa: E402

    runs_root = tmp_path / "rjob_logs"
    run_dir = make_contract_run(runs_root)
    make_contract_episode(run_dir, task_dir="004", score=0.6556)
    site = tmp_path / "site"
    build = subprocess.run(
        [sys.executable, str(REPO_ROOT / "demo" / "build_site.py"),
         "--runs-root", str(runs_root), "--out", str(site),
         "--data-dir", str(REPO_ROOT / "demo" / "data")],
        capture_output=True, text=True, check=False, timeout=300,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return site


def _dump(site: Path, out_json: Path) -> None:
    overview = site / "assets" / "data" / "overview.json"
    compare = site / "assets" / "data" / "compare.json"
    episode = next((site / "assets" / "data" / "episode").rglob("*.json"), None)
    assert episode is not None, "站点里没有逐题数据"
    result = subprocess.run(
        [NODE, str(DUMP), str(overview), str(compare), str(episode), str(site), str(out_json)],
        capture_output=True, text=True, check=False, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_flow_svg_dumps(tmp_path):
    """首页渲染出来的流程图能被完整导出（节点、连线、标签都在）。"""
    site = _build_site(tmp_path)
    out_json = tmp_path / "flow.json"
    _dump(site, out_json)
    payload = out_json.read_text(encoding="utf-8")
    assert "fnode-box" in payload, "流程图里没有节点框"
    assert "fedge-line" in payload, "流程图里没有连线"
    assert "fedge-label" in payload, "流程图里没有连线标签"


@pytest.mark.skipif(PILLOW_PYTHON is None, reason="没有装了 Pillow 的解释器，跳过字体度量检查")
def test_flow_text_fits_its_box(tmp_path):
    """框里和胶囊里的文字都不能超出边界（真实字体度量）。"""
    site = _build_site(tmp_path)
    out_json = tmp_path / "flow.json"
    out_png = tmp_path / "flow.png"
    _dump(site, out_json)
    result = subprocess.run(
        [str(PILLOW_PYTHON), str(RENDER), str(out_json), "--out", str(out_png)],
        capture_output=True, text=True, check=False, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "版式检查通过" in result.stdout, result.stdout
    assert out_png.is_file() and out_png.stat().st_size > 0, "没出图"
