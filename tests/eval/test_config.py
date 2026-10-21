"""infra/config.json：唯一配置文件（无占位符、绝对路径、必填键齐全）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tandem_eval.rjob import load_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "infra" / "config.example.json"


def test_repo_config_loads_and_is_absolute():
    config = load_config(CONFIG_PATH)
    PATH_KEYS = ("repo_root", "deploy_root", "results_root", "osw1_root", "osw1_vm",
                 "osw2_root", "osw2_vm", "asset_root")
    for key in PATH_KEYS:
        assert config[key].startswith("/"), f"{key} 必须是绝对路径: {config[key]}"
    assert config["inner_image"].startswith("registry.")
    # 凭据内联形态：kimi 为 dict、endpoint 为 URL、registry 为 docker config 对象
    assert set(config["kimi"]) >= {"base_url", "api_key", "model"}
    assert config["jev_endpoint"].startswith("http")
    assert "auths" in config["registry"]
    assert config["results_root"].endswith("tandem/rjob_logs")
    assert config["repo_root"].endswith("/tandem")


def test_mounts_cover_both_volumes_with_user_style_targets():
    config = load_config(CONFIG_PATH)
    targets = {m["target"] for m in config["mounts"]}
    assert "/mnt/shared-storage-user/evobox-share-gpfs2" in targets
    assert "/mnt/shared-storage-user/adpc-share" in targets
    # evobox 卷两侧一致（user 风格），共享资源路径随之 user 风格
    assert config["osw1_root"].startswith("/mnt/shared-storage-user/evobox-share-gpfs2/")
    assert config["osw1_vm"].startswith("/mnt/shared-storage-user/evobox-share-gpfs2/")


def test_load_config_rejects_missing_keys(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"repo_root": "/x"}), encoding="utf-8")
    with pytest.raises(Exception, match="必填键"):
        load_config(bad)


def test_load_config_rejects_empty_image(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["rjob"]["image"] = ""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(Exception, match="image"):
        load_config(bad)


def test_real_config_is_gitignored_with_example_committed():
    repo = Path(__file__).resolve().parents[2]
    ignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "infra/config.json" in ignore, "含密钥的真实配置必须 gitignore"
