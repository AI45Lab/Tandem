"""infra/envs 档案回归：双挂载与 adpc 落盘约束（防手改档案破坏 rjob 编排）。"""

from __future__ import annotations

import json
from pathlib import Path

from tandem_eval.rjob import load_profile

ENVS = Path(__file__).resolve().parents[2] / "infra" / "envs"


def _load(name: str) -> dict:
    return load_profile(ENVS / name)


def test_both_gpfs_mounts_present_in_dev_profile():
    profile = _load("dev.json")
    sources = {m["source"] for m in profile["mounts"]}
    assert sources == {
        "gpfs://gpfs2/evobox-share-gpfs2",
        "gpfs://gpfs2/adpc-share",
    }
    # 容器内挂载点与开发机路径一致（dev/rjob 视角统一的前提）
    for mount in profile["mounts"]:
        assert mount["target"].endswith(mount["source"].rsplit("/", 1)[-1])


def test_deploy_and_results_live_under_adpc_share():
    dev, rjob = _load("dev.json"), _load("rjob.json")
    for profile in (dev, rjob):
        assert profile["deploy_root"].startswith("/mnt/shared-storage-user/adpc-share/")
        assert profile["results_root"].startswith("/mnt/shared-storage-user/adpc-share/")
    # dev 与 worker 视角的部署/结果路径一致（双挂载点同路径）
    assert dev["deploy_root"] == rjob["deploy_root"]
    assert dev["results_root"] == rjob["results_root"]
    # 部署副本在 repo 外（rsync 源/目的不得互相嵌套）
    repo = dev["repo_root_hint"]
    assert dev["deploy_root"] != repo and not dev["deploy_root"].startswith(repo + "/")


def test_shared_resources_still_on_evobox_mount():
    profile = _load("rjob.json")
    assert profile["shared_resources"].startswith(
        "/mnt/shared-storage-user/evobox-share-gpfs2/"
    )
    assert profile["osw1_vm"].endswith("Ubuntu.qcow2")


def test_profiles_are_valid_json_with_expanded_paths():
    for name in ("dev.json", "rjob.json"):
        json.loads((ENVS / name).read_text(encoding="utf-8"))  # 合法 JSON
        for key, value in _load(name).items():
            if isinstance(value, str):
                assert "{" not in value, f"{name}:{key} 未展开: {value}"


def test_legacy_canonical_mount_point_present():
    """共享包内绝对符号链接（如 JEV endpoint）指向规范挂载点，worker 必须同时挂载它。"""
    profile = _load("dev.json")
    targets = {m["target"] for m in profile["mounts"]}
    assert "/mnt/shared-storage-gpfs2/evobox-share-gpfs2" in targets
