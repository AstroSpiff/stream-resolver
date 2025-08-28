import importlib
import os
import pathlib
import sys

import pytest

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def setup_env(monkeypatch, tmp_path):
    os_env = {
        "CONFIG_DIR": str(tmp_path),
        "APP_DIR": str(tmp_path),
    }
    for k, v in os_env.items():
        monkeypatch.setenv(k, v)

    import app.xtream_manager as xtm
    importlib.reload(xtm)
    return xtm


def test_admin_xtreams_delete_removes_cache_file(monkeypatch, tmp_path):
    xtm = setup_env(monkeypatch, tmp_path)
    xt_id = "1"
    xt_conf = {
        "id": xt_id,
        "username": "u",
        "password": "p",
        "live_list_ids": [],
        "movie_list_ids": [],
        "series_list_ids": [],
        "mixed_list_ids": [],
        "every_hours": 12,
        "last_refresh": xtm.now_ts(),
    }

    xtm.save_json(xtm.XTREAMS_JSON, [xt_conf])

    cache_file = os.path.join(tmp_path, "xtream_cache", f"{xt_id}.json")
    xtm.save_json(cache_file, {"data": True})
    assert os.path.exists(cache_file)

    xtm.admin_xtreams_delete(xt_id)

    assert not os.path.exists(cache_file)
