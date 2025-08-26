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


def test_xt_get_php_uses_durations(monkeypatch, tmp_path):
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

    vod_item = xtm.M3UItem(
        title="Movie One",
        url="http://example.com/movie/10/file",
        attrs={"tvg-duration": "90"},
        group="Film",
        tvg_id="",
        tvg_logo="",
        raw="",
    )

    series_item = xtm.M3UItem(
        title="Show S01E02",
        url="http://example.com/series/20/season/1/2",
        attrs={"tvg-duration": "40"},
        group="Serie",
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
                "movie_list_ids": ["v"],
                "series_list_ids": ["s"],
                "mixed_list_ids": [],
            }
        ]

    def fake_read_playlist(pid):
        return {
            "l": [live_item],
            "v": [vod_item],
            "s": [series_item],
        }.get(pid, [])

    monkeypatch.setattr(xtm, "_xtreams", fake_xtreams)
    monkeypatch.setattr(xtm, "_read_playlist", fake_read_playlist)

    req = make_request()
    resp = xtm.xt_get_php(req, "1", username="u", password="p")
    body = resp.body.decode()
    lines = body.strip().splitlines()

    assert "#EXTINF:-1" in lines[1]
    assert "#EXTINF:90" in lines[3]
    assert "#EXTINF:40" in lines[5]

