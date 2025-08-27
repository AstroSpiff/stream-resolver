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


def test_panel_api_same_as_player_api(monkeypatch, tmp_path):
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


def test_default_response_contains_counts(monkeypatch, tmp_path):
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
    movie_item = xtm.M3UItem(
        title="Movie One",
        url="http://example.com/movie/abcdefabcdef",
        attrs={},
        group="Movie",
        tvg_id="",
        tvg_logo="",
        raw="",
    )
    series_item = xtm.M3UItem(
        title="Series One",
        url="http://example.com/series/abcdefabcdef",
        attrs={},
        group="Series",
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
                "movie_list_ids": ["m"],
                "series_list_ids": ["s"],
                "mixed_list_ids": [],
            }
        ]

    def fake_read_playlist(pid):
        return {"l": [live_item], "m": [movie_item], "s": [series_item]}.get(pid, [])

    monkeypatch.setattr(xtm, "_xtreams", fake_xtreams)
    monkeypatch.setattr(xtm, "_read_playlist", fake_read_playlist)

    req = make_request()
    resp = xtm.xt_player_api(req, "1", username="u", password="p")
    assert resp["available_channels"] == 1
    assert resp["available_movies"] == 1
    assert resp["available_series"] == 1

    resp_player = xtm.xt_player_api(req, "1", username="u", password="p")
    resp_panel = xtm.xt_panel_api(req, "1", username="u", password="p")
    assert resp_panel == resp_player


def test_root_player_api_uses_single_xtream(monkeypatch, tmp_path):
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
    resp_root = xtm.player_api(req, username="u", password="p", action="get_live_streams")
    resp_player = xtm.xt_player_api(
        req, "1", username="u", password="p", action="get_live_streams"
    )
    assert resp_root == resp_player


def test_root_player_api_requires_xt_id(monkeypatch, tmp_path):
    xtm = setup_env(monkeypatch, tmp_path)

    def fake_xtreams():
        return [
            {
                "id": "1",
                "username": "u1",
                "password": "p1",
                "live_list_ids": [],
                "movie_list_ids": [],
                "series_list_ids": [],
                "mixed_list_ids": [],
            },
            {
                "id": "2",
                "username": "u2",
                "password": "p2",
                "live_list_ids": [],
                "movie_list_ids": [],
                "series_list_ids": [],
                "mixed_list_ids": [],
            },
        ]

    monkeypatch.setattr(xtm, "_xtreams", fake_xtreams)

    req = make_request()
    with pytest.raises(xtm.HTTPException) as exc:
        xtm.player_api(req, username="u1", password="p1", action="get_live_streams")
    assert exc.value.status_code == 400


def test_root_player_api_accepts_xt_id(monkeypatch, tmp_path):
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

    def fake_xtreams():
        return [
            {
                "id": "1",
                "username": "u1",
                "password": "p1",
                "live_list_ids": ["l"],
                "movie_list_ids": [],
                "series_list_ids": [],
                "mixed_list_ids": [],
            },
            {
                "id": "2",
                "username": "u2",
                "password": "p2",
                "live_list_ids": [],
                "movie_list_ids": [],
                "series_list_ids": [],
                "mixed_list_ids": [],
            },
        ]

    def fake_read_playlist(pid):
        return {"l": [live_item]}.get(pid, [])

    monkeypatch.setattr(xtm, "_xtreams", fake_xtreams)
    monkeypatch.setattr(xtm, "_read_playlist", fake_read_playlist)

    req = make_request()
    resp_root = xtm.player_api(
        req,
        username="u1",
        password="p1",
        xt_id="1",
        action="get_live_streams",
    )
    resp_player = xtm.xt_player_api(
        req, "1", username="u1", password="p1", action="get_live_streams"
    )
    assert resp_root == resp_player


def test_root_panel_api_alias(monkeypatch, tmp_path):
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
    resp_root = xtm.panel_api(
        req, username="u", password="p", action="get_live_streams"
    )
    resp_panel = xtm.xt_panel_api(
        req, "1", username="u", password="p", action="get_live_streams"
    )
    assert resp_root == resp_panel

