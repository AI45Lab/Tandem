"""manifest：索引加载与 job spec manifest 解析。"""

from __future__ import annotations

import json

from tandem_eval.manifest import TaskRef, load_index, resolve_manifest, write_resolved


def test_load_index_domain_dict_format():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "idx.json"
        path.write_text(json.dumps({"chrome": ["a", "b"], "os": ["c"]}), encoding="utf-8")
        refs = load_index(path)
    assert refs == [TaskRef("a", "chrome"), TaskRef("b", "chrome"), TaskRef("c", "os")]


def test_load_index_flat_list_formats():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "idx.json"
        path.write_text(json.dumps(["x", {"id": "y", "domain": "os"}]), encoding="utf-8")
        refs = load_index(path)
    assert refs == [TaskRef("x", ""), TaskRef("y", "os")]


def test_resolve_manifest_explicit_tasks_and_limit():
    spec = {"benchmark": "osworld1", "manifest": {"tasks": ["t1", "t2"]}}
    assert [r.task_id for r in resolve_manifest(spec)] == ["t1", "t2"]
    spec = {"benchmark": "mock", "manifest": {"tasks": ["t1", "t2", "t3"], "limit": 2}}
    assert [r.task_id for r in resolve_manifest(spec)] == ["t1", "t2"]


def test_resolve_manifest_mock_default():
    refs = resolve_manifest({"benchmark": "mock"})
    assert len(refs) == 1 and refs[0].task_id == "mock-000"


def test_resolve_manifest_from_index_root():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        examples = root / "osworld1" / "evaluation_examples"
        examples.mkdir(parents=True)
        (examples / "test_nogdrive.json").write_text(
            json.dumps({"chrome": ["id-1", "id-2"]}), encoding="utf-8"
        )
        spec = {"benchmark": "osworld1", "index_root": str(root), "manifest": {}}
        refs = resolve_manifest(spec)
    assert [r.task_id for r in refs] == ["id-1", "id-2"]


def test_write_resolved(tmp_path):
    write_resolved(tmp_path, [TaskRef("a", "chrome"), TaskRef("b", "")],
                   {"run_id": "r1", "benchmark": "mock"})
    data = json.loads((tmp_path / "episodes" / "manifest.resolved.json").read_text())
    assert data["count"] == 2
    assert data["tasks"][0]["episode_dir"] == "chrome-a"
    assert data["tasks"][1]["episode_dir"] == "b"


def test_shard_interleaves_after_limit():
    spec = {"benchmark": "mock", "manifest": {
        "tasks": [f"t{i}" for i in range(20)], "limit": 10,
        "shard": {"index": 1, "total": 5}}}
    refs = resolve_manifest(spec)
    assert [r.task_id for r in refs] == ["t0", "t5"]  # 10 题 → 交错 5 片各 2 题
    spec["manifest"]["shard"] = {"index": 5, "total": 5}
    assert [r.task_id for r in resolve_manifest(spec)] == ["t4", "t9"]
    spec["manifest"]["shard"] = {"index": 6, "total": 5}
    import pytest as _pytest
    with _pytest.raises(ValueError, match="1..5"):
        resolve_manifest(spec)


def test_index_root_derived_from_env_section(tmp_path):
    """spec 未带 index_root 时从 env.root 推导（--limit 索引路径在真实基准上的默认来源）。"""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        examples = root / "evaluation_examples"
        examples.mkdir()
        (examples / "test_v2.json").write_text(
            json.dumps({"tasks": ["001", "002", "003"]}), encoding="utf-8")
        spec = {"benchmark": "osworld2", "env": {"root": str(root)}, "manifest": {}}
        refs = resolve_manifest(spec)
    assert [r.task_id for r in refs] == ["001", "002", "003"]
