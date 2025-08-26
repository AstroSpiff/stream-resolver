import importlib
import sys
from pathlib import Path
import urllib.parse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _get_wrap_proxy(monkeypatch, proxy=None):
    if proxy is None:
        monkeypatch.delenv("MEDIAFLOW_PROXY", raising=False)
    else:
        monkeypatch.setenv("MEDIAFLOW_PROXY", proxy)
    import app.main as main
    importlib.reload(main)
    return main.wrap_proxy


def test_wrap_proxy_wraps_url(monkeypatch):
    wrap_proxy = _get_wrap_proxy(monkeypatch, "http://proxy")
    url = "simple"
    expected = f"http://proxy/fetch?target={urllib.parse.quote(url, safe='')}"
    assert wrap_proxy(url, True) == expected


def test_wrap_proxy_passthrough(monkeypatch):
    wrap_proxy = _get_wrap_proxy(monkeypatch)
    url = "simple"
    assert wrap_proxy(url, True) == url
    assert wrap_proxy(url, False) == url
