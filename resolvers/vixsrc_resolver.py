# -*- coding: utf-8 -*-
import os
import json
import urllib.parse
from typing import Dict, Optional
import httpx

DEFAULT_SETTINGS_PATHS = [
    os.environ.get("MFP_SETTINGS_JSON") or "/app/config/mfp_settings.json",
    "/app/config/settings.json",
]

class MediaflowError(RuntimeError):
    pass

def _load_settings() -> Dict[str, str]:
    for path in DEFAULT_SETTINGS_PATHS:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Supporta sia mfp_settings.json che settings.json
            mediaflow_url = data.get("mediaflow_url") or data.get("MEDIAFLOW_URL")
            api_password = data.get("api_password") or data.get("API_PASSWORD")
            if mediaflow_url and api_password:
                return {"mediaflow_url": mediaflow_url.rstrip("/"), "api_password": api_password}
        except FileNotFoundError:
            pass
    raise MediaflowError("Impostazioni MediaFlow non trovate (mfp_settings.json / settings.json).")

def _enc(u: str) -> str:
    return urllib.parse.quote(u, safe="")

def _build_proxy_url(kind: str, mediaflow_url: str, api_password: str,
                     stream_url: str, headers: Dict[str, str]) -> str:
    """
    kind: 'hls' | 'mpd2hls'
    headers: dict con eventuali referer/origin/user-agent/cookie ricevuti dall'extractor
    """
    base = f"{mediaflow_url}/proxy/hls/manifest.m3u8" if kind == "hls" \
           else f"{mediaflow_url}/proxy/mpd/playlist.m3u8"

    params = [
        ("d", stream_url),
        ("api_password", api_password),
    ]
    # Propaga header come h_*
    mapping = {
        "referer": "h_referer",
        "origin": "h_origin",
        "user-agent": "h_user-agent",
        "cookie": "h_cookie",
    }
    for k, v in headers.items():
        lk = k.lower()
        if lk in mapping and v:
            params.append((mapping[lk], v))

    query = "&".join(f"{k}={_enc(v)}" for k, v in params if v)
    return f"{base}?{query}"

def _detect_ext(url: str) -> str:
    low = url.lower().split("?")[0]
    if low.endswith(".m3u8"):
        return "hls"
    if low.endswith(".mpd"):
        return "mpd"
    return ""

def resolve(url: str) -> Dict[str, str]:
    """
    Esegue:
      1) /extractor/video (host=vixsrc)
      2) /proxy/hls/... oppure /proxy/mpd/playlist.m3u8 (MPD->HLS)
    Ritorna: {"final_url": "..."} puntando a MediaFlow, pronto per ffmpeg/player.
    """
    st = _load_settings()
    mflow = st["mediaflow_url"]
    pwd = st["api_password"]

    # 1) EXTRACTOR
    # Supporta vixsrc.to e mirror vixsrl.to
    host = "vixsrc"
    endpoint = f"{mflow}/extractor/video"
    q = f"host={host}&d={_enc(url)}&api_password={_enc(pwd)}"
    extractor_url = f"{endpoint}?{q}"

    with httpx.Client(follow_redirects=True, timeout=30) as s:
        r = s.get(extractor_url)
        if r.status_code != 200:
            raise MediaflowError(f"Extractor error {r.status_code}: {r.text[:200]}")
        data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        # fallback: alcune installazioni ritornano già un dict 'result'
        res = data.get("result") or data

        stream_url: Optional[str] = res.get("stream_url") or res.get("url") or ""
        if not stream_url:
            raise MediaflowError("Extractor non ha restituito 'stream_url'.")

        headers = res.get("headers") or {}
        # 2) PROXY compatibile ffmpeg (senza transcodifica)
        ext = _detect_ext(stream_url)
        if ext == "hls":
            final_url = _build_proxy_url("hls", mflow, pwd, stream_url, headers)
        elif ext == "mpd":
            final_url = _build_proxy_url("mpd2hls", mflow, pwd, stream_url, headers)
        else:
            # se non riconosciamo, proviamo HLS per default
            final_url = _build_proxy_url("hls", mflow, pwd, stream_url, headers)

    return {"final_url": final_url}