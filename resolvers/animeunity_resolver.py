#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
animeunity_resolver.py
Estrae MP4/m3u8 tramite animeunity_scraper; se esce HLS o embed, passa via MediaFlow-Proxy.
"""
import sys, json
from urllib.parse import urlparse
from mfp_conf import load_mediaflow

try:
    import animeunity_scraper as AUS
except Exception:
    AUS = None

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
    # Schema già usato nel tuo ecosistema: /proxy/hls/manifest.m3u8?d=...&api_password=...
    from urllib.parse import urlencode
    return f"{mfp_base}/proxy/hls/manifest.m3u8?{urlencode({'d': target, 'api_password': pwd})}"

def main():
    payload = _read_payload(sys.argv)
    url = (payload.get("url") or "").strip()
    if not url:
        print(json.dumps({"ok": False, "error": "no_url_provided"})); sys.exit(1)
    if AUS is None:
        print(json.dumps({"ok": False, "error": "scraper_import_failed"})); sys.exit(2)

    # URL attesi: https://www.animeunity.so/anime/<id>-<slug>/<episode>
    try:
        path = urlparse(url).path.strip("/").split("/")
        idx = path.index("anime")
        id_slug = path[idx+1]
        episode = path[idx+2]
        anime_id = id_slug.split("-")[0]
        anime_slug = "-".join(id_slug.split("-")[1:])
    except Exception:
        print(json.dumps({"ok": False, "error": "unrecognized_url_pattern"})); sys.exit(3)

    r = AUS.get_stream(anime_id, anime_slug, episode)
    mp4 = (r or {}).get("mp4_url")
    embed = (r or {}).get("embed_url")

    # Caso “buono”: MP4 diretto
    if mp4 and mp4.endswith(".mp4"):
        print(mp4); return

    # Fallback HLS o embed → MediaFlow Proxy
    m3u8 = None
    for cand in (mp4, embed):
        if cand and ".m3u8" in cand:
            m3u8 = cand; break

    mfp, pwd = load_mediaflow()
    if m3u8 and mfp and pwd:
        print(_proxy_hls(mfp, pwd, m3u8)); return

    # Ulteriore fallback: restituisce la pagina
    print(url)

if __name__ == "__main__":
    main()
