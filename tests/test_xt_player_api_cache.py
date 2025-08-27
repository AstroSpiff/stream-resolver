import importlib
import os
import pathlib
import sys

import pytest
from starlette.requests import Request


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def make_request():
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("test", 80),
            "path": "/",
            "headers": [],
        }
    )


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


def test_xt_player_api_uses_cache(monkeypatch, tmp_path):
    xtm = setup_env(monkeypatch, tmp_path)

    live_item = xtm.M3UItem(
        title="Live One",
        url="http://example.com/live/abcdefabcdef",
        attrs={},
        group="Live",
        tvg_id="",
        tvg_logo="",
        raw="",
    )

    xt_conf = {
        "id": "1",
        "username": "u",
        "password": "p",
        "live_list_ids": ["l"],
        "movie_list_ids": [],
        "series_list_ids": [],
        "mixed_list_ids": [],
        "every_hours": 12,
        "last_refresh": xtm.now_ts(),
    }

    def fake_xtreams():
        return [xt_conf]

    def fake_read_playlist(pid):
        return {"l": [live_item]}.get(pid, [])

    monkeypatch.setattr(xtm, "_xtreams", fake_xtreams)
    monkeypatch.setattr(xtm, "_read_playlist", fake_read_playlist)

    req = make_request()

    # build initial cache
    xtm.build_xtream_cache(req, xt_conf)

    # ensure subsequent calls use cache and do not attempt to re-read playlists
    def fail_items(sel_ids):  # pragma: no cover - should not be called
        raise AssertionError("playlist should not be parsed when cache valid")

    monkeypatch.setattr(xtm, "items_for_xtream_selection", fail_items)

    resp = xtm.xt_player_api(
        req, "1", username="u", password="p", action="get_live_streams"
    )

    cache_data = xtm.load_json(
        os.path.join(tmp_path, "xtream", "1.json"), {}
    )
    assert resp == cache_data["live_streams"]

