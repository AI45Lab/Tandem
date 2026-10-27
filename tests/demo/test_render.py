"""用 node 跑一遍站点视图代码（最小 DOM stub）。

**为什么要有这个**：站点是纯前端，改视图名、改结构都可能让首页直接白屏
（踩过：「view is not a function」——路由默认视图名没跟着改）。
本机没有浏览器，但可以用 node + 最小 DOM stub 把 `TD.views.*` 真跑一遍，
把「渲染期崩不崩」这类问题挡在测试里。

**不依赖任何预构建产物**：测试自己用合成夹具建一个站点，再渲染它——
这样站点数据与前端版本永远同步（之前依赖预构建站点，夹具数据是旧的，
字段不全，测出来的东西不作数）。

stub 在 `render_stub.js`（JS 文件，单独放免得被 ruff 按行长检查）。
node 不在的环境自动跳过（CI 可能没有 node）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB = REPO_ROOT / "tests" / "demo" / "render_stub.js"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node 不在 PATH，跳过渲染冒烟")


@pytest.mark.skipif(NODE is None, reason="node 不在 PATH")
def test_views_render_without_error(tmp_path):
    """把首页/结果/轨迹浏览三个视图与真实路由真跑一遍，不许抛异常。"""
    sys.path.insert(0, str(REPO_ROOT / "tests" / "demo"))
    from helpers import make_contract_episode, make_contract_run  # noqa: E402

    runs_root = tmp_path / "rjob_logs"
    run_dir = make_contract_run(runs_root)
    make_contract_episode(run_dir, task_dir="004", score=0.6556)
    make_contract_episode(run_dir, task_dir="025", score=None, stop="exception", steps=0)

    site = tmp_path / "site"
    build = subprocess.run(
        [sys.executable, str(REPO_ROOT / "demo" / "build_site.py"),
         "--runs-root", str(runs_root), "--out", str(site),
         "--data-dir", str(REPO_ROOT / "demo" / "data")],
        capture_output=True, text=True, check=False, timeout=300,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    overview = site / "assets" / "data" / "overview.json"
    compare = site / "assets" / "data" / "compare.json"
    episode = next((site / "assets" / "data" / "episode").rglob("*.json"), None)
    assert episode is not None, "站点里没有逐题数据"

    result = subprocess.run(
        [NODE, str(STUB), str(overview), str(compare), str(episode), str(site)],
        capture_output=True, text=True, check=False, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok home" in result.stdout
    assert "ok browser" in result.stdout
    assert "ok route (#/)" in result.stdout
    assert "ok route (#/browser)" in result.stdout
    assert "ok flow" in result.stdout
