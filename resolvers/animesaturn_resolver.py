#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
animesaturn_resolver.py
Si appoggia alle funzioni del tuo animesaturn.py.
Se stream è m3u8 → wrapper HLS via MediaFlow-Proxy.
"""
import sys, json
from mfp_conf import load_mediaflow

try:
    import animesaturn as AS
except Exception:
    AS = None

def _read_payload(argv):
    if len(argv) >= 2 and argv[1] != "--json":
        return {"url": argv[1]}
    if len(argv) >= 3 and argv[1] == "--json":
        return {"url": argv[2]}
    try:
        data = sys.stdin.read().strip()
        if data:
            return json.loads(data)
    except Exception:
        pass
    return {}

def _proxy_hls(mfp_base: str, pwd: str, target: str) -> str:
    from urllib.parse import urlencode
    return f"{mfp_base}/proxy/hls/manifest.m3u8?{urlencode({'d': target, 'api_password': pwd})}"

def main():
    p = _read_payload(sys.argv)
    url = (p.get("url") or "").strip()
    if not url:
        print(json.dumps({"ok": False, "error": "no_url_provided"})); sys.exit(1)
    if AS is None:
        print(json.dumps({"ok": False, "error": "scraper_import_failed"})); sys.exit(2)

    watch = AS.get_watch_url(url)
    if not watch:
        print(json.dumps({"ok": False, "error": "watch_not_found"})); sys.exit(3)

    link = AS.extract_mp4_url(watch)  # atteso .mp4 o .m3u8
    if not link:
        print(json.dumps({"ok": False, "error": "stream_not_found"})); sys.exit(4)

    if link.endswith(".m3u8"):
        mfp, pwd = load_mediaflow()
        if mfp and pwd:
            print(_proxy_hls(mfp, pwd, link)); return

    print(link)

if __name__ == "__main__":
    main()
