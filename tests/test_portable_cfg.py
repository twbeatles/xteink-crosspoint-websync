"""portable_data / backup_sync 설정 호환 테스트."""
import json
import os
import tempfile

from websync.backup.portable_cfg import (
    HISTORY_MODE_GLOBAL_URL,
    apply_portable_cfg,
    get_portable_cfg,
)
from websync.config.manager import ConfigManager
from websync.gui.portable_wizard import should_show_portable_wizard


def test_legacy_backup_sync_still_configures():
    cfg = {
        "backup_sync": {
            "enabled": True,
            "folder": "C:/OneDrive/Xteink",
            "include_history": True,
            "auto_export": True,
            "auto_import_on_start": True,
        }
    }
    pd = get_portable_cfg(cfg)
    assert pd["enabled"] is True
    assert pd["folder"].replace("\\", "/").endswith("OneDrive/Xteink")


def test_apply_mirrors_to_backup_sync():
    cfg = {}
    apply_portable_cfg(
        cfg,
        enabled=True,
        folder="/shared",
        history_mode=HISTORY_MODE_GLOBAL_URL,
        wizard_completed=True,
    )
    assert cfg["portable_data"]["enabled"] is True
    assert cfg["portable_data"]["history_mode"] == HISTORY_MODE_GLOBAL_URL
    assert cfg["backup_sync"]["enabled"] is True
    assert cfg["backup_sync"]["folder"] == "/shared"


def test_config_manager_migrates_portable():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "x3_ip": "10.0.0.1",
                    "backup_sync": {
                        "enabled": True,
                        "folder": os.path.join(tmp, "cloud"),
                    },
                },
                f,
            )
        cm = ConfigManager(path)
        cfg = cm.load_config()
        assert "portable_data" in cfg
        assert cfg["portable_data"]["enabled"] is True
        assert cfg["portable_data"]["folder"]
        assert cfg.get("x3_primary_device_id")
        assert should_show_portable_wizard(cfg) is False  # enabled+folder


def test_wizard_shows_on_fresh_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        cm = ConfigManager(path)
        cfg = cm.load_config()
        # 신규 기본: wizard 미완료, 폴더 없음
        assert should_show_portable_wizard(cfg) is True
        apply_portable_cfg(cfg, wizard_completed=True)
        assert should_show_portable_wizard(cfg) is False
