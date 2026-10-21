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
    # endpoint 允许为空（= 从 *_endpoint_file 发现文件自动解析）
    assert isinstance(config["jev_endpoint"], str)
    assert config["jev_endpoint_file"].endswith("services/qwen_jev.json")
    assert config["kev_endpoint_file"].endswith("services/kev.json")
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


def test_endpoint_discovery_prefers_explicit_then_file(tmp_path, monkeypatch):
    from tandem_eval.entry import read_endpoint_file, resolve_selector_endpoint

    f = tmp_path / "endpoint.json"
    f.write_text(json.dumps({"base_url": "http://10.9.9.9:8891/"}), encoding="utf-8")
    assert read_endpoint_file(str(f)) == "http://10.9.9.9:8891"
    # 显式值优先于文件
    assert resolve_selector_endpoint(
        {"jev_endpoint": "http://1.2.3.4:1", "jev_endpoint_file": str(f)}, "jev") == "http://1.2.3.4:1"
    # 为空 → 文件发现
    assert resolve_selector_endpoint({"jev_endpoint": "", "jev_endpoint_file": str(f)}, "jev") \
        == "http://10.9.9.9:8891"
    # 两者皆无 → 明确报错
    import pytest as _pytest
    with _pytest.raises(ValueError, match="为空且未配置"):
        resolve_selector_endpoint({"jev_endpoint": ""}, "jev")


def test_endpoint_file_symlink_view_fallback(tmp_path, monkeypatch):
    """给定路径不可读时，自动尝试另一挂载视角的等价路径（前缀翻译）。"""
    from tandem_eval import entry as entry_mod

    user_dir = tmp_path / "user-view"
    canonical_dir = tmp_path / "canonical-view"
    real = user_dir / "endpoint.json"
    real.parent.mkdir(parents=True)
    real.write_text(json.dumps({"base_url": "http://5.5.5.5:8891"}), encoding="utf-8")

    monkeypatch.setattr(entry_mod, "_EVOBOX_USER", str(user_dir))
    monkeypatch.setattr(entry_mod, "_EVOBOX_CANONICAL", str(canonical_dir))
    # 传入的规范视角路径不存在（符号链接断裂场景）→ 翻译到 user 视角命中
    assert entry_mod.read_endpoint_file(str(canonical_dir / "endpoint.json")) == "http://5.5.5.5:8891"


def test_kev_endpoint_discovery_via_shared_services_file(tmp_path):
    """KEV endpoint 为空时同样从 services 目录的发现文件读取。"""
    from tandem_eval.entry import resolve_selector_endpoint

    f = tmp_path / "kev_endpoint.json"
    f.write_text(json.dumps({"base_url": "http://10.8.8.8:8008/"}), encoding="utf-8")
    assert resolve_selector_endpoint(
        {"kev_endpoint": "", "kev_endpoint_file": str(f)}, "kev") == "http://10.8.8.8:8008"


def test_endpoint_file_respects_readiness_flag(tmp_path):
    """发现文件标记未就绪时快速失败，不调用半启动的服务。"""
    import pytest as _pytest

    from tandem_eval.entry import read_endpoint_file

    f = tmp_path / "svc.json"
    f.write_text(json.dumps({"status": "starting", "ready": False,
                             "base_url": "http://1.1.1.1:1"}), encoding="utf-8")
    with _pytest.raises(ValueError, match="未就绪"):
        read_endpoint_file(str(f))
    f.write_text(json.dumps({"status": "ready", "ready": True,
                             "base_url": "http://2.2.2.2:2"}), encoding="utf-8")
    assert read_endpoint_file(str(f)) == "http://2.2.2.2:2"
