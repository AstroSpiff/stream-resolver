import os
import sys
from pathlib import Path
import importlib

from starlette.requests import Request


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def import_xtm(tmp_path):
    os.environ["APP_DIR"] = str(tmp_path)
    return importlib.reload(importlib.import_module("app.xtream_manager"))


def make_request():
    return Request({
        "type": "http",
        "scheme": "http",
        "server": ("test", 80),
        "path": "/",
        "headers": [],
    })


def test_try_extract_tv_triplet_series(tmp_path):
    xtm = import_xtm(tmp_path)
    url1 = "http://example.com/series/123/season/4/5"
    url2 = "http://example.com/series/123/4/5"
    url3 = "http://example.com/series/user/pass/123/4/5.m3u8"
    assert xtm.try_extract_tv_triplet(url1) == ("123", 4, 5)
    assert xtm.try_extract_tv_triplet(url2) == ("123", 4, 5)
    assert xtm.try_extract_tv_triplet(url3) == ("123", 4, 5)


def test_build_series_collections_with_series_urls(tmp_path):
    xtm = import_xtm(tmp_path)
    url = "http://example.com/series/user/pass/123/season/2/3.m3u8"
    item = xtm.M3UItem(
        title="My Show S02E03",
        url=url,
        attrs={},
        group="Serie",
        tvg_id="",
        tvg_logo="",
        raw="",
    )
    req = make_request()
    series_map, cat_map = xtm.build_series_collections(req, [item])
    assert "123" in series_map
    sm = series_map["123"]
    assert "2" in sm["episodes_by_season"]
    ep = sm["episodes_by_season"]["2"][0]
    assert ep["id"] == "123-S02E03"
