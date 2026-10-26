"""demo 站点构建的单测：结构、离线可开、口径不被折算。

发布闸门（诚实披露红线逐条自检）在 `demo/export_share.py` 及其对应测试里。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from helpers import make_contract_episode, make_contract_run  # noqa: E402


def build_site(tmp_path: Path, runs_root: Path, out_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "demo" / "build_site.py"),
         "--runs-root", str(runs_root), "--out", str(out_dir),
         "--data-dir", str(REPO_ROOT / "demo" / "data")],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
    )


def _fixture(tmp_path: Path) -> Path:
    runs_root = tmp_path / "rjob_logs"
    run_dir = make_contract_run(runs_root)
    make_contract_episode(run_dir, task_dir="004", score=0.6556)
    make_contract_episode(run_dir, task_dir="025", score=None, stop="exception", steps=0)
    return runs_root


def test_build_site_produces_single_page_app(tmp_path):
    runs_root = _fixture(tmp_path)
    out_dir = tmp_path / "site"
    result = build_site(tmp_path, runs_root, out_dir)
    assert result.returncode == 0, result.stderr
    assert (out_dir / "index.html").is_file()
    assert (out_dir / "assets" / "app.css").is_file()
    assert (out_dir / "assets" / "app.js").is_file()
    assert (out_dir / "assets" / "boot.js").is_file()
    assert (out_dir / "assets" / "views" / "overview.js").is_file()
    assert (out_dir / "assets" / "data" / "overview.json").is_file()
    assert (out_dir / "assets" / "data" / "compare.json").is_file()
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert '"attempted"' in html
    assert 'id="data-compare"' in html


def test_index_references_only_existing_scripts(tmp_path):
    """index.html 引用的每个脚本都必须在产物里存在（防止漏拷视图）。"""
    runs_root = _fixture(tmp_path)
    out_dir = tmp_path / "site"
    assert build_site(tmp_path, runs_root, out_dir).returncode == 0
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    sources = re.findall(r'<script src="([^"]+)"', html)
    assert sources
    for source in sources:
        assert (out_dir / source).is_file(), f"index.html 引用了不存在的脚本：{source}"


def test_built_site_has_no_external_resources(tmp_path):
    runs_root = _fixture(tmp_path)
    out_dir = tmp_path / "site"
    assert build_site(tmp_path, runs_root, out_dir).returncode == 0
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    for pattern in (r'src\s*=\s*["\']https?://', r'href\s*=\s*["\']https?://'):
        assert not re.search(pattern, html, re.IGNORECASE)


def test_built_site_keeps_unscored_as_null(tmp_path):
    """未出分的题在站点数据里必须是 null，不能折算 0（红线 1）。"""
    runs_root = _fixture(tmp_path)
    out_dir = tmp_path / "site"
    assert build_site(tmp_path, runs_root, out_dir).returncode == 0
    overview = json.loads((out_dir / "assets" / "data" / "overview.json").read_text(encoding="utf-8"))
    unscored = [row for row in overview["rows"] if row.get("status") != "scored"]
    assert unscored, "夹具里应当有一道未出分的题"
    assert all(row["score"] is None for row in unscored)


def test_overview_carries_disclaimer_notes(tmp_path):
    runs_root = _fixture(tmp_path)
    out_dir = tmp_path / "site"
    assert build_site(tmp_path, runs_root, out_dir).returncode == 0
    overview = json.loads((out_dir / "assets" / "data" / "overview.json").read_text(encoding="utf-8"))
    notes = " ".join(overview["disclaimer_notes"])
    assert "底座不同" in notes
    assert "未出分" in notes
    assert "墙钟" in notes


def test_demo_layer_does_not_import_harness():
    offenders = []
    for path in (REPO_ROOT / "demo").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*(from|import)\s+tandem(_eval)?\b", text, re.MULTILINE):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
