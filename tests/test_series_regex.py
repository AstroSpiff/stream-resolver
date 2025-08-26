import pathlib
import sys
import importlib

import pytest


class DummyRequest:
    base_url = "http://testserver/"


@pytest.fixture
def xm(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    # ensure repository root is in sys.path for module import
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import app.xtream_manager as module
    importlib.reload(module)
    return module


def test_try_extract_tv_triplet_series(xm):
    url1 = "http://host/series/123/season/1/2"
    url2 = "http://host/series/123/1/2"
    url3 = "http://host/series/user/pass/123/1/2.m3u8"
    assert xm.try_extract_tv_triplet(url1) == ("123", 1, 2)
    assert xm.try_extract_tv_triplet(url2) == ("123", 1, 2)
    assert xm.try_extract_tv_triplet(url3) == ("123", 1, 2)


def test_try_extract_movie_id(xm):
    url1 = "http://host/movie/123/path"
    url2 = "http://host/movie/user/pass/456.m3u8"
    assert xm.try_extract_movie_id(url1) == "123"
    assert xm.try_extract_movie_id(url2) == "456"


def test_build_series_collections_series(xm):
    item = xm.M3UItem(
        title="My Show S01E02",
        url="http://host/series/123/season/1/2",
        attrs={},
        group="Serie",
        tvg_id="",
        tvg_logo="",
        raw="",
    )
    series_map, cat_map = xm.build_series_collections(DummyRequest(), [item])
    assert "123" in series_map
    episodes = series_map["123"]["episodes_by_season"]["1"]
    assert episodes[0]["title"] == "S01E02"
