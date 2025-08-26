import pathlib
import sys
from urllib.parse import quote

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app.main as main


def test_wrap_proxy_encodes_target(monkeypatch):
    monkeypatch.setattr(main, "MEDIAFLOW_PROXY", "http://proxy")
    url = "http://example.com/a?b=1&c=2"
    out = main.wrap_proxy(url, True)
    assert out == f"http://proxy/fetch?target={quote(url, safe='')}"

