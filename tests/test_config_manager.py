import json
import os
import tempfile
import multiprocessing
import time

import pytest

from unittest.mock import patch

from websync.config.exceptions import ConfigLoadError, ConfigSaveError
from websync.config.manager import ConfigManager


def _update_config_in_process(path: str, key: str, start_event) -> None:
    start_event.wait(timeout=10)

    def mutate(config):
        config[key] = "changed"
        time.sleep(0.3)

    ConfigManager(path).update_config(mutate)


def test_deep_merge_adds_nested_keys():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"x3_ip": "192.168.1.1", "sites": [{"name": "A", "type": "rss", "url": "http://x"}]}, f)

        cm = ConfigManager(path)
        cfg = cm.load_config()

        assert "ai_summary" in cfg
        assert cfg["ai_summary"]["enabled"] is False
        assert cfg["sites"][0].get("include_images") is False
        assert "api_token" in cfg.get("web_dashboard", {})
        assert "calibre_library_path" in cfg


def test_atomic_save_writes_valid_json():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        cm = ConfigManager(path)
        cfg = cm.load_config()
        cfg["x3_ip"] = "10.0.0.5"
        cm.save_config(cfg)
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["x3_ip"] == "10.0.0.5"
        assert os.path.exists(f"{path}.bak")


def test_corrupt_json_raises_and_preserves():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        cm = ConfigManager(path)
        with pytest.raises(ConfigLoadError) as exc:
            cm.load_config()
        assert exc.value.corrupt_path and os.path.exists(exc.value.corrupt_path)


def test_save_config_raises_on_failure():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        cm = ConfigManager(path)
        cfg = cm.load_config()
        with patch("builtins.open", side_effect=OSError("disk full")):
            with pytest.raises(ConfigSaveError):
                cm.save_config(cfg)


def test_config_revision_cas_conflict():
    from websync.config.exceptions import ConfigConflictError

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        cm = ConfigManager(path)
        cfg = cm.load_config()
        rev0 = int(cfg.get("_config_revision") or 0)

        # A 저장
        cfg["x3_ip"] = "10.0.0.1"
        cm.save_config(cfg, expected_revision=rev0)
        cfg_a = cm.load_config()
        rev_a = int(cfg_a["_config_revision"])

        # 오래된 revision 으로 저장 → 충돌
        stale = dict(cfg)
        stale["x3_ip"] = "10.0.0.99"
        stale["_config_revision"] = rev0
        with pytest.raises(ConfigConflictError) as exc:
            cm.save_config(stale, expected_revision=rev0)
        assert exc.value.disk_config is not None

        # 최신 revision 으로는 성공
        cfg_a["x3_ip"] = "10.0.0.2"
        cm.save_config(cfg_a, expected_revision=rev_a)
        assert cm.load_config()["x3_ip"] == "10.0.0.2"


def test_update_config_rmw():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        cm = ConfigManager(path)
        cm.load_config()

        def mut(cfg):
            cfg["x3_ip"] = "192.168.9.9"
            cfg.setdefault("sites", []).append(
                {"name": "X", "type": "rss", "url": "https://x.test/feed", "limit": 1}
            )

        saved = cm.update_config(mut)
        assert saved["x3_ip"] == "192.168.9.9"
        loaded = cm.load_config()
        assert loaded["x3_ip"] == "192.168.9.9"
        assert any(s.get("url") == "https://x.test/feed" for s in loaded["sites"])


def test_update_config_is_atomic_across_processes():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        ConfigManager(path).load_config()
        ctx = multiprocessing.get_context("spawn")
        start_event = ctx.Event()
        processes = [
            ctx.Process(target=_update_config_in_process, args=(path, key, start_event))
            for key in ("process_a", "process_b")
        ]
        for process in processes:
            process.start()
        start_event.set()
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0

        loaded = ConfigManager(path).load_config()
        assert loaded["process_a"] == "changed"
        assert loaded["process_b"] == "changed"


def test_import_sites_rmw_preserves_other_fields():
    """import_sites 가 전체 config 덮어쓰기 없이 sites 만 합집합 추가."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        cm = ConfigManager(path)
        cfg = cm.load_config()
        cfg["x3_ip"] = "10.1.2.3"
        cm.save_config(cfg)

        export_path = os.path.join(tmp, "sites_export.json")
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "export_version": 1,
                    "sites": [
                        {
                            "name": "Imported",
                            "type": "rss",
                            "url": "https://import.example/feed",
                            "limit": 3,
                        }
                    ],
                },
                f,
            )

        # 다른 스레드/경로가 갱신한 것처럼 IP를 update_config 로 변경
        cm.update_config(lambda c: c.__setitem__("x3_ip", "10.9.9.9"))

        added = cm.import_sites(export_path)
        assert len(added) == 1
        loaded = cm.load_config()
        assert loaded["x3_ip"] == "10.9.9.9"
        assert any(s.get("url") == "https://import.example/feed" for s in loaded["sites"])

        # 중복 임포트 시 추가 없음
        added2 = cm.import_sites(export_path)
        assert added2 == []
