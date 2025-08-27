import pathlib
import sys
import importlib
import urllib.parse

import pytest


@pytest.fixture
def xm(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import app.xtream_manager as module
    importlib.reload(module)
    return module


def test_try_extract_movie_id_wrapped(xm):
    inner = "http://host/movie/789"
    encoded = urllib.parse.quote(urllib.parse.quote(inner, safe=""), safe="")
    url = f"http://wrapper/video?u={encoded}"
    assert xm.try_extract_movie_id(url) == "789"
