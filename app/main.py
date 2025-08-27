# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import uuid
from typing import Dict, List, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl, BaseModel

from app.xtream_manager import setup_xtream

from .adapter import ResolverError, run_resolver
# ========= resolver esterni =========
# (restano invariati; usiamo ancora adapter/registry per Vavoo & co.)
from .registry import pick_script_for

# configure logging at application level
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# -----------------------------------------------------------------------------
# Config & bootstrap (UI + settings)
# -----------------------------------------------------------------------------
APP_DIR = os.environ.get("APP_DIR", "/app")
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(APP_DIR, "app", "static"))
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/app/config")
PLAYLISTS_DIR = os.path.join(CONFIG_DIR, "playlists")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(PLAYLISTS_DIR, exist_ok=True)

SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
PLAYLISTS_INDEX = os.path.join(CONFIG_DIR, "playlists.json")

DEFAULT_SETTINGS = {
    "mediaflow_url": "",
    "api_password": "",
    "stream_resolver_url": ""
}

def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.exception("File not found when reading JSON from %s", path)
        return default
    except Exception:
        logger.exception("Error reading JSON from %s", path)
        return default

def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        logger.exception("Error writing JSON to %s", path)

def _load_settings() -> Dict[str, str]:
    """Carica solo settings.json (file ufficiale)."""
    s1 = _read_json(SETTINGS_FILE, {})
    return {**DEFAULT_SETTINGS, **s1}

def _save_settings(data: Dict[str, str]) -> None:
    safe = {k: (data.get(k) or "").strip() for k in DEFAULT_SETTINGS.keys()}
    _write_json(SETTINGS_FILE, safe)

def _now_ts() -> int:
    return int(time.time())

def _ensure_http(url_or_host: str) -> str:
    u = (url_or_host or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "http://" + u

# --- helpers Mediaflow (common) ----------------------------------------------
def _enc(u: str) -> str:
    import urllib.parse
    return urllib.parse.quote(u, safe="")


# -----------------------------------------------------------------------------
# Costanti/utility
# -----------------------------------------------------------------------------
VIX_HOSTS = {"vixsrc.to", "www.vixsrc.to", "vixsrl.to", "www.vixsrl.to"}

def _parse_host(u: str) -> str:
    try:
        return urllib.parse.urlparse(u).hostname or ""
    except Exception:
        return ""

# -----------------------------------------------------------------------------
# PASSO SPECIALE per VixSrc/VixSrl → MediaFlow extractor con redirect_stream=true
# (MODIFICA RICHIESTA: single-hop SOLO per VixSrc; il resto resta invariato)
# -----------------------------------------------------------------------------
def build_vixcloud_redirect(original_url: str) -> str:
    st = _load_settings()
    mflow = _ensure_http((st.get("mediaflow_url") or "").rstrip("/"))
    pwd = st.get("api_password") or ""
    if not mflow or not pwd:
        raise HTTPException(status_code=400, detail="Config mancante: imposta mediaflow_url e api_password in /admin.")
    return (
        f"{mflow}/extractor/video"
        f"?host=VixCloud&redirect_stream=true"
        f"&api_password={_enc(pwd)}&d={_enc(original_url)}"
    )
# -----------------------------------------------------------------------------
# Resolver “generico” (per Vavoo & co.) via adapter/registry
# -----------------------------------------------------------------------------
MEDIAFLOW_PROXY = os.environ.get("MEDIAFLOW_PROXY", "")  # (opzionale, non usata per VixSrc)
PYTHON_CMD      = os.environ.get("RESOLVER_COMMAND", "python3")
RESOLVERS_DIR   = os.environ.get("RESOLVERS_DIR", "/opt/external-resolvers")

class ResolveIn(BaseModel):
    url: AnyHttpUrl
    headers: Optional[Dict[str, str]] = None
    useProxy: Optional[bool] = False

def wrap_proxy(url: str, enabled: bool) -> str:
    if enabled and MEDIAFLOW_PROXY:
        base = MEDIAFLOW_PROXY.rstrip("/")
        return f"{base}/fetch?target={urllib.parse.quote(url, safe='')}"
    return url

def _handle_generic(url: str, kind: str, headers: Optional[Dict[str, str]], use_proxy: bool):
    """
    Percorso standard: usa i resolver esterni se presenti, altrimenti ritorna la URL così com'è.
    """
    try:
        host = _parse_host(url).lower()
        script_path = pick_script_for(host)
        if not script_path:
            # no resolver → ritorna as-is (eventuale proxy wrapper)
            return {
                "ok": True,
                "type": "unknown",
                "resolvedUrl": wrap_proxy(url, use_proxy),
                "headers": headers or {},
                "meta": {"resolver": None, "note": "no_resolver_for_domain"}
            }

        out = run_resolver(
            script_path, url, kind,
            headers=headers,
            python_command=PYTHON_CMD,
            cwd=os.path.dirname(script_path)
        )
        out["resolvedUrl"] = wrap_proxy(out.get("resolvedUrl", ""), use_proxy)
        out.setdefault("meta", {})["resolver"] = os.path.basename(script_path)
        return out

    except ResolverError as e:
        # errore "applicativo" del resolver
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        # errore inatteso
        raise HTTPException(status_code=500, detail=f"resolver_internal_error: {e}")

# -----------------------------------------------------------------------------
# Playlist utils (UI)
# -----------------------------------------------------------------------------
M3U_HEADER_RE = re.compile(r"^#EXTM3U", re.IGNORECASE)

def _resolver_link_for(url: str, settings: Dict[str, str], mode: str) -> str:
    base = _ensure_http(settings.get("stream_resolver_url") or "")
    if not base:
        # se non configurato, restituisce url originale
        return url
    endpoint = "tv" if (mode or "").lower() == "tv" else "video"
    return f"{base.rstrip('/')}/{endpoint}?u={_enc(url)}"

def convert_playlist_text(src_text: str, mode: str, settings: Dict[str, str]) -> str:
    """
    Converte una playlist M3U generica in una M3U che punta al nostro resolver
    (/video?u=... oppure /tv?u=... in base a 'mode').
    """
    lines = src_text.splitlines()
    out: List[str] = []
    saw_header = False
    seen_urls: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not saw_header and M3U_HEADER_RE.match(stripped):
            saw_header = True
        if stripped.startswith("#"):
            if mode == "video" and not stripped.startswith("#EXT"):
                continue
            if mode == "video" and stripped.startswith("#EXTINF"):
                line = re.sub(r'\s*group-title="[^"]*"', "", line)
            out.append(line)
            continue
        if stripped.lower().startswith(("http://", "https://")):
            if stripped in seen_urls:
                continue
            seen_urls.add(stripped)
            out.append(_resolver_link_for(stripped, settings, mode))
        elif stripped == "":
            out.append("")
        else:
            out.append(line)
    if not out or not M3U_HEADER_RE.match(out[0].strip()):
        out.insert(0, "#EXTM3U")
    return "\n".join(out) + "\n"

async def fetch_text(url: str, timeout: float = 40.0) -> str:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "StreamResolver/1.2 (+httpx)"}
    ) as s:
        r = await s.get(url)
        r.raise_for_status()
        return r.text

def _read_playlists_index() -> List[Dict]:
    return _read_json(PLAYLISTS_INDEX, [])

def _write_playlists_index(items: List[Dict]) -> None:
    _write_json(PLAYLISTS_INDEX, items)

def _find_playlist(items: List[Dict], pid: str) -> Optional[Dict]:
    for it in items:
        if it.get("id") == pid:
            return it
    return None

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
APP = FastAPI(title="Stream Resolver", version="1.2.0")

@APP.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("HTTP %s %s headers=%s",
                request.method,
                str(request.url),
                dict(request.headers))
    return await call_next(request)

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# static admin
if os.path.isdir(STATIC_DIR):
    APP.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@APP.get("/", response_class=HTMLResponse)
def home():
    index_path = os.path.join(STATIC_DIR, "admin", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Stream Resolver</h1><p>GUI non trovata.</p>")

@APP.get("/health")
def health():
    st = _load_settings()
    configured = bool((st.get("mediaflow_url") or "").strip()
                      and (st.get("api_password") or "").strip())
    return {
        "ok": True,
        "ts": _now_ts(),
        "resolvers_dir": RESOLVERS_DIR,
        "proxy": MEDIAFLOW_PROXY or None,
        "configured": configured
    }

setup_xtream(APP)

# -----------------------------------------------------------------------------
# ENDPOINTS: VIDEO/TV
# -----------------------------------------------------------------------------
def _vix_fastpath(url: str) -> str:
    host = _parse_host(url).lower()
    if host in VIX_HOSTS:
        return build_vixcloud_redirect(url)
    return ""

def _handle_with_vix(url: str, kind: str, headers: Optional[Dict[str, str]], use_proxy: bool):
    """
    SOLO per link VixSrc/VixSrl: usa fastpath single-hop (redirect_stream=true).
    Per tutto il resto: percorso generico (resolver esterni, es. Vavoo).
    """
    fast = _vix_fastpath(url)  # <— fastpath attivo SOLO per domini VixSrc
    if fast:
        return {"ok": True, "resolvedUrl": fast, "meta": {"resolver": "MediaFlow.VixCloud"}}
    return _handle_generic(url, kind, headers, use_proxy)

# --- GET/HEAD (redirect immediato, per player) ---
@APP.api_route("/tv", methods=["GET", "HEAD"])
def tv_get(u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    data = _handle_with_vix(str(u), "tv", None, useProxy)
    if not data.get("ok") or not data.get("resolvedUrl"):
        raise HTTPException(status_code=502, detail="unable_to_resolve")
    return RedirectResponse(url=data["resolvedUrl"], status_code=302)

@APP.api_route("/video", methods=["GET", "HEAD"])
def video_get(u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    data = _handle_with_vix(str(u), "video", None, useProxy)
    if not data.get("ok") or not data.get("resolvedUrl"):
        raise HTTPException(status_code=502, detail="unable_to_resolve")
    return RedirectResponse(url=data["resolvedUrl"], status_code=302)

@APP.api_route("/play", methods=["GET", "HEAD"])  # alias comodo per /tv
def play_get(u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    data = _handle_with_vix(str(u), "tv", None, useProxy)
    if not data.get("ok") or not data.get("resolvedUrl"):
        raise HTTPException(status_code=502, detail="unable_to_resolve")
    return RedirectResponse(url=data["resolvedUrl"], status_code=302)

# --- DEBUG (restituisce JSON senza redirect) ---
@APP.get("/debug/tv")
def tv_debug(u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    try:
        data = _handle_with_vix(str(u), "tv", None, useProxy)
        return JSONResponse(data)
    except HTTPException as e:
        return JSONResponse({"detail": f"debug_tv_error: {e.detail}"}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"detail": f"debug_tv_error: {e}"}, status_code=500)

@APP.get("/debug/video")
def video_debug(u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    try:
        data = _handle_with_vix(str(u), "video", None, useProxy)
        return JSONResponse(data)
    except HTTPException as e:
        return JSONResponse({"detail": f"debug_video_error: {e.detail}"}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"detail": f"debug_video_error: {e}"}, status_code=500)

# --- POST (JSON, utile per integrazioni) ---
@APP.post("/tv")
def tv_post(payload: ResolveIn = Body(...)):
    return JSONResponse(_handle_with_vix(str(payload.url), "tv", payload.headers, payload.useProxy or False))

@APP.post("/video")
def video_post(payload: ResolveIn = Body(...)):
    return JSONResponse(_handle_with_vix(str(payload.url), "video", payload.headers, payload.useProxy or False))

# -----------------------------------------------------------------------------
# ADMIN API – settings
# -----------------------------------------------------------------------------
@APP.get("/admin/settings.json")
def admin_get_settings():
    return {"settings": _load_settings()}

class SettingsIn(BaseModel):
    mediaflow_url: str = ""
    api_password: str = ""
    stream_resolver_url: str = ""

@APP.post("/admin/settings.json")
def admin_save_settings(payload: SettingsIn):
    data = payload.model_dump()
    # normalizza il resolver URL per accettare anche "host:porta"
    if data.get("stream_resolver_url"):
        data["stream_resolver_url"] = _ensure_http(data["stream_resolver_url"])
    _save_settings(data)
    return {"ok": True}

# -----------------------------------------------------------------------------
# ADMIN API – convert (una tantum) → ritorna file .m3u
# -----------------------------------------------------------------------------
class ConvertIn(BaseModel):
    url: str
    mode: str = "video"  # "video" | "tv"

@APP.post("/admin/convert")
async def admin_convert_once(body: ConvertIn):
    if not body.url:
        raise HTTPException(status_code=400, detail="URL mancante")
    src = await fetch_text(body.url)
    out = convert_playlist_text(src, body.mode, _load_settings())
    filename = "converted.m3u" if body.mode != "tv" else "converted_tv.m3u"
    return PlainTextResponse(
        out,
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
# -----------------------------------------------------------------------------
# ADMIN API – playlists CRUD
# -----------------------------------------------------------------------------
class PlaylistCreate(BaseModel):
    name: str
    url: str
    mode: str = "video"
    every_hours: int = 12
    resolver_url: str = ""

@APP.get("/admin/playlists.json")
def admin_list_playlists():
    return {"items": _read_playlists_index()}

@APP.post("/admin/playlists")
def admin_add_playlist(data: PlaylistCreate):
    if not data.name or not data.url:
        raise HTTPException(status_code=400, detail="Nome e URL richiesti")
    items = _read_playlists_index()
    pid = uuid.uuid4().hex[:10]
    it = {
        "id": pid,
        "name": data.name.strip(),
        "url": data.url.strip(),
        "mode": data.mode,
        "every_hours": max(1, int(data.every_hours or 12)),
        "resolver_url": _ensure_http(data.resolver_url) if data.resolver_url else "",
        "last_refresh": 0
    }
    items.append(it)
    _write_playlists_index(items)
    return {"ok": True, "id": pid}

class PlaylistUpdate(BaseModel):
    url: Optional[str] = None
    every_hours: Optional[int] = None
    resolver_url: Optional[str] = None
    refresh: bool = False

@APP.post("/admin/playlists/{pid}/update")
async def admin_update_playlist(pid: str = Path(...), data: PlaylistUpdate = Body(...)):
    items = _read_playlists_index()
    it = _find_playlist(items, pid)
    if not it:
        raise HTTPException(status_code=404, detail="Playlist non trovata")

    if data.url is not None:
        new_url = (data.url or "").strip()
        if not new_url or not (new_url.lower().startswith("http://") or new_url.lower().startswith("https://")):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        it["url"] = new_url

    if data.every_hours is not None:
        it["every_hours"] = max(1, int(data.every_hours))

    if data.resolver_url is not None:
        it["resolver_url"] = _ensure_http(data.resolver_url) if data.resolver_url else ""

    if data.refresh:
        try:
            src = await fetch_text(it["url"])
            settings = _load_settings()
            if it.get("resolver_url"):
                settings = {**settings, "stream_resolver_url": it["resolver_url"]}
            out = convert_playlist_text(src, it["mode"], settings)
            out_path = os.path.join(PLAYLISTS_DIR, f"{pid}.m3u")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(out)
            it["last_refresh"] = _now_ts()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Errore refresh: {e}")

    _write_playlists_index(items)
    return {"ok": True}

@APP.delete("/admin/playlists/{pid}")
def admin_delete_playlist(pid: str):
    items = _read_playlists_index()
    new_items = [x for x in items if x.get("id") != pid]
    _write_playlists_index(new_items)
    try:
        os.remove(os.path.join(PLAYLISTS_DIR, f"{pid}.m3u"))
    except FileNotFoundError:
        pass
    return {"ok": True}

# -----------------------------------------------------------------------------
# Serving delle playlist convertite
# -----------------------------------------------------------------------------
@APP.get("/lists/{pid}.m3u")
def serve_playlist(pid: str):
    path = os.path.join(PLAYLISTS_DIR, f"{pid}.m3u")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Playlist non trovata")
    return FileResponse(path, media_type="audio/x-mpegurl", filename=f"{pid}.m3u")
