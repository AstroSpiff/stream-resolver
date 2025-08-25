#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
animeworld_resolver.py
Usa animeworld_scraper.get_stream(slug, episode). Se restituisce MP4 ok, altrimenti wrapper HLS via MediaFlow-Proxy.
"""
import sys, json
from urllib.parse import urlparse, parse_qs
from mfp_conf import load_mediaflow

try:
    import animeworld_scraper as AWS
except Exception:
    AWS = None

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
    if AWS is None:
        print(json.dumps({"ok": False, "error": "scraper_import_failed"})); sys.exit(2)

    parsed = urlparse(url)
    # Supporta: https://animeworld.so/play/<slug>?ep=<n>
    slug = parsed.path.strip("/").replace("play/", "")
    qs = parse_qs(parsed.query or "")
    ep = None
    try:
        if "ep" in qs: ep = int(qs["ep"][0])
    except Exception:
        ep = None

    r = AWS.get_stream(slug, ep)  # restituisce {'mp4_url': ..., 'episode_page': ...} 
    mp4 = (r or {}).get("mp4_url")
    page = (r or {}).get("episode_page")

    if mp4:
        if mp4.endswith(".mp4"):
            print(mp4); return
        if ".m3u8" in mp4:
            mfp, pwd = load_mediaflow()
            if mfp and pwd:
                print(_proxy_hls(mfp, pwd, mp4)); return

    # fallback: restituisce la pagina episodio
    print(page or url)

if __name__ == "__main__":
    main()
