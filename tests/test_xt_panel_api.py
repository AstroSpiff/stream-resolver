import importlib
import os
import pathlib
import sys

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


def test_panel_api_same_as_player_api(monkeypatch, tmp_path):
    os_env = {
        "CONFIG_DIR": str(tmp_path),
        "APP_DIR": str(tmp_path),
    }
    for k, v in os_env.items():
        monkeypatch.setenv(k, v)

    import app.xtream_manager as xtm
    importlib.reload(xtm)

    live_item = xtm.M3UItem(
        title="Live One",
        url="http://example.com/live/abcdefabcdef",
        attrs={},
        group="Live",
        tvg_id="",
        tvg_logo="",
        raw="",
    )

    def fake_xtreams():
        return [
            {
                "id": "1",
                "username": "u",
                "password": "p",
                "live_list_ids": ["l"],
                "movie_list_ids": [],
                "series_list_ids": [],
                "mixed_list_ids": [],
            }
        ]

    def fake_read_playlist(pid):
        return {"l": [live_item]}.get(pid, [])

    monkeypatch.setattr(xtm, "_xtreams", fake_xtreams)
    monkeypatch.setattr(xtm, "_read_playlist", fake_read_playlist)

    req = make_request()

    resp_player = xtm.xt_player_api(
        req, "1", username="u", password="p", action="get_live_streams"
    )
    resp_panel = xtm.xt_panel_api(
        req, "1", username="u", password="p", action="get_live_streams"
    )
    assert resp_panel == resp_player

    resp_player = xtm.xt_player_api(req, "1", username="u", password="p")
    resp_panel = xtm.xt_panel_api(req, "1", username="u", password="p")
    assert resp_panel == resp_player

