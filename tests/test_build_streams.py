import pathlib
import sys

import pytest

from test_series_regex import xm, DummyRequest  # reuse fixtures

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app.main as main


def _make_vod_item(xm_module, title: str, url: str, group: str = "Film", tvg_logo: str = "", **attrs):
    return xm_module.M3UItem(
        title=title,
        url=url,
        attrs=attrs,
        group=group,
        tvg_id="",
        tvg_logo=tvg_logo,
        raw="",
    )


def _make_live_item(xm_module, title: str, url: str, group: str = "Live"):
    return xm_module.M3UItem(
        title=title,
        url=url,
        attrs={},
        group=group,
        tvg_id="",
        tvg_logo="",
        raw="",
    )


def test_build_vod_streams_with_invalid_url(xm):
    req = DummyRequest()
    item1 = _make_vod_item(xm, "Movie One", "http://host/movie/123/path")
    item2 = _make_vod_item(xm, "Broken", "nota")
    streams, cat_map = xm.build_vod_streams(req, [item1, item2])
    assert len(streams) == 2
    required_keys = {"num", "name", "stream_id", "stream_type", "stream_icon", "rating", "added", "category_id", "category_name", "container_extension", "direct_source"}
    for s in streams:
        assert required_keys <= s.keys()
    s1, s2 = streams
    assert s1["stream_id"] == "123"
    assert s1["direct_source"] == f"http://testserver/video?u={xm.enc(item1.url)}"
    expected_crc = str(xm.crc32_num(item2.url))
    assert s2["stream_id"] == expected_crc
    assert s2["direct_source"] == f"http://testserver/video?u={xm.enc(item2.url)}"
    assert "Film" in cat_map


def test_build_live_streams_handles_invalid_urls(xm):
    req = DummyRequest()
    valid_url = "http://host/live/abcdef12345678"
    invalid_url = "bad"  # too short -> uses CRC
    item1 = _make_live_item(xm, "Live One", valid_url)
    item2 = _make_live_item(xm, "Live Two", invalid_url)
    streams, cat_map = xm.build_live_streams(req, [item1, item2])
    assert len(streams) == 2
    required_keys = {"num", "name", "stream_id", "stream_type", "stream_icon", "epg_channel_id", "category_id", "category_name", "added", "custom_sid", "container_extension", "direct_source"}
    for s in streams:
        assert required_keys <= s.keys()
    s1, s2 = streams
    token = valid_url.strip("/").split("/")[-1]
    assert s1["stream_id"] == f"lv_{token[:16]}"
    expected_crc = hex(xm.crc32_num(invalid_url))[2:]
    assert s2["stream_id"] == f"lv_{expected_crc[:16]}"
    assert s2["direct_source"] == f"http://testserver/tv?u={xm.enc(invalid_url)}"
    assert "Live" in cat_map


def test_build_vod_info_and_not_found(xm):
    req = DummyRequest()
    item = _make_vod_item(xm, "Some Movie", "http://host/movie/555/file", tvg_year="2020", tvg_logo="poster.jpg")
    info = xm.build_vod_info(req, "555", [item])
    assert info["info"]["name"] == "Some Movie (2020)"
    assert info["info"]["movie_image"] == "poster.jpg"
    assert info["info"]["releasedate"] == "2020"
    with pytest.raises(xm.HTTPException) as exc:
        xm.build_vod_info(req, "999", [item])
    assert exc.value.status_code == 404


def test_convert_playlist_text_adds_header_and_skips_invalid(xm):  # xm fixture ensures sys.path
    src = "#EXTINF:-1,Channel\nhttp://example.com/stream\nnotaurl\n"
    settings = {"stream_resolver_url": "http://resolver"}
    out = main.convert_playlist_text(src, "tv", settings)
    lines = out.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXTINF:-1,Channel"
    assert lines[2] == "http://resolver/tv?u=http%3A%2F%2Fexample.com%2Fstream"
    assert lines[3] == "notaurl"
    assert out.endswith("\n")
