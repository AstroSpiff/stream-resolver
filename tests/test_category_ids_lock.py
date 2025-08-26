import importlib
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def import_xtm(tmp_path):
    os.environ["APP_DIR"] = str(tmp_path)
    return importlib.reload(importlib.import_module("app.xtream_manager"))


def test_get_category_id_concurrent(tmp_path):
    xtm = import_xtm(tmp_path)
    names = [f"cat{i}" for i in range(5)]

    def worker(name):
        return xtm.get_category_id(name, 1000)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(worker, name) for name in names for _ in range(2)]
        [f.result() for f in futures]

    data = xtm.load_json(xtm.CATEGORY_IDS_JSON, {})
    for name in names:
        assert name in data
        assert data[name] == xtm.stable_category_id(name, 1000)
