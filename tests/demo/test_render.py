"""用 node 跑一遍站点视图代码（最小 DOM stub）。

**为什么要有这个**：站点是纯前端，改视图名、改结构都可能让首页直接白屏
（踩过：「view is not a function」——路由默认视图名没跟着改名）。
本机没有浏览器，但可以用 node + 最小 DOM stub 把 `TD.views.*` 真跑一遍，
把"渲染期崩不崩"这类问题挡在测试里。

stub 在 `render_stub.js`（JS 文件，单独放免得被 ruff 按行长检查）。
node 不在的环境自动跳过（CI 可能没有 node）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB = REPO_ROOT / "demo" / "web"
STUB = REPO_ROOT / "tests" / "demo" / "render_stub.js"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node 不在 PATH，跳过渲染冒烟")


@pytest.mark.skipif(NODE is None, reason="node 不在 PATH")
def test_views_render_without_error():
    """把首页/结果/轨迹浏览三个视图与真实路由真跑一遍，不许抛异常。"""
    site = REPO_ROOT / "demo" / "site"
    overview_path = site / "assets" / "data" / "overview.json"
    compare_path = site / "assets" / "data" / "compare.json"
    if not overview_path.is_file():
        pytest.skip("站点还没构建（demo/site/assets/data/overview.json 不存在）")
    episode_path = next((site / "assets" / "data" / "episode").rglob("*.json"), None)
    if episode_path is None:
        pytest.skip("站点里没有逐题数据，跳过渲染冒烟")

    result = subprocess.run(
        [NODE, str(STUB), str(overview_path), str(compare_path), str(episode_path), str(WEB)],
        capture_output=True, text=True, check=False, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok home" in result.stdout
    assert "ok browser" in result.stdout
    assert "ok route (#/)" in result.stdout
    assert "ok route (#/browser)" in result.stdout
