# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app import config
from app import db
from app.services import m3u

router = APIRouter()


@router.get("/admin/settings.json")
def admin_get_settings():
    return {"settings": config.load_settings()}


class MediaflowPreset(BaseModel):
    name: str
    url: str
    api_password: str = ""


class ResolverPreset(BaseModel):
    name: str
    url: str


class TMDBConfig(BaseModel):
    api_key: str = ""
    language: str = "it-IT"
    movie_fields: Optional[List[str]] = None
    series_fields: Optional[List[str]] = None
    season_fields: Optional[List[str]] = None
    episode_fields: Optional[List[str]] = None


class SettingsIn(BaseModel):
    mediaflow_url: str = ""
    api_password: str = ""
    stream_resolver_url: str = ""
    mediaflows: Optional[List[MediaflowPreset]] = None
    resolvers: Optional[List[ResolverPreset]] = None
    # DB / TMDB
    database_url: Optional[str] = None
    db_profiles: Optional[List[Dict[str, str]]] = None
    active_db: Optional[str] = None
    tmdb: Optional[TMDBConfig] = None


@router.post("/admin/settings.json")
def admin_save_settings(payload: SettingsIn):
    data = payload.model_dump()
    if data.get("stream_resolver_url"):
        data["stream_resolver_url"] = config.ensure_http(data["stream_resolver_url"])
    if isinstance(data.get("resolvers"), list):
        for it in data["resolvers"]:
            it["url"] = config.ensure_http(it.get("url") or "")
    if isinstance(data.get("mediaflows"), list):
        for it in data["mediaflows"]:
            it["url"] = config.ensure_http(it.get("url") or "")
    config.save_settings(data)
    # Rebind/Init DB engine (DB-only backend)
    try:
        from app import db as _db
        _db.reset_engine()
        _db.init_db()
    except Exception:
        pass
    return {"ok": True}


class ConvertIn(BaseModel):
    url: str
    mode: str = "video"  # "video" | "tv"
    resolver_url: Optional[str] = None


@router.post("/admin/convert")
async def admin_convert_once(body: ConvertIn):
    if not body.url:
        raise HTTPException(status_code=400, detail="URL mancante")
    src = await m3u.fetch_text(body.url)
    settings = config.load_settings()
    if body.resolver_url:
        settings = {**settings, "resolvers": [{"name": "override", "url": body.resolver_url}]}
    out = m3u.convert_playlist_text(src, body.mode, settings)
    filename = "converted.m3u" if body.mode != "tv" else "converted_tv.m3u"
    return PlainTextResponse(
        out,
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class PlaylistCreate(BaseModel):
    name: str
    url: str
    mode: str = "film"
    every_hours: int = 12
    resolver_url: str = ""


@router.get("/admin/playlists.json")
def admin_list_playlists():
    return {"items": m3u.read_playlists_index()}


def _normalize_mode(mode: str) -> str:
    m = (mode or "").strip().lower()
    if m in ("tv", "live"): return "live"
    if m in ("video", "vod", "film", "movie"): return "film"
    if m in ("series", "serie", "serietv"): return "series"
    if m in ("mixed", "misto", "mix"): return "mixed"
    return "film"

@router.post("/admin/playlists")
def admin_add_playlist(data: PlaylistCreate):
    if not data.name or not data.url:
        raise HTTPException(status_code=400, detail="Nome e URL richiesti")
    items = m3u.read_playlists_index()
    pid = uuid.uuid4().hex[:10]
    it = {
        "id": pid,
        "name": data.name.strip(),
        "url": data.url.strip(),
        "mode": _normalize_mode(data.mode),
        "every_hours": max(1, int(data.every_hours or 12)),
        "resolver_url": config.ensure_http(data.resolver_url) if data.resolver_url else "",
        "last_refresh": 0,
    }
    items.append(it)
    m3u.write_playlists_index(items)
    return {"ok": True, "id": pid}


class PlaylistUpdate(BaseModel):
    url: Optional[str] = None
    name: Optional[str] = None
    mode: Optional[str] = None
    every_hours: Optional[int] = None
    resolver_url: Optional[str] = None
    refresh: bool = False


@router.post("/admin/playlists/{pid}/update")
async def admin_update_playlist(pid: str = Path(...), data: PlaylistUpdate = Body(...)):
    playlists = m3u.read_playlists_index()
    it = m3u.find_playlist(playlists, pid)
    if not it:
        raise HTTPException(status_code=404, detail="Playlist non trovata")

    if data.name is not None:
        new_name = (data.name or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Nome non può essere vuoto")
        it["name"] = new_name

    if data.mode is not None:
        it["mode"] = _normalize_mode(data.mode)

    if data.url is not None:
        new_url = (data.url or "").strip()
        if not new_url or not (new_url.lower().startswith("http://") or new_url.lower().startswith("https://")):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
        it["url"] = new_url

    if data.every_hours is not None:
        it["every_hours"] = max(1, int(data.every_hours))

    if data.resolver_url is not None:
        it["resolver_url"] = config.ensure_http(data.resolver_url) if data.resolver_url else ""

    if data.refresh:
        try:
            src = await m3u.fetch_text(it["url"])
            # In backend DB: importa soltanto nel DB (niente conversione/scrittura file)
            if config.get_storage_backend() == 'db':
                from app.services.xtream import parse_m3u, guess_is_series, guess_is_movie, try_extract_movie_id, try_extract_tv_triplet
                from app import db
                items = parse_m3u(src)
                with db.SessionLocal() as s:
                    p = s.get(db.Playlist, pid)
                    if not p:
                        p = db.Playlist(id=pid, name=it.get('name') or '', url=it.get('url') or '', mode=it.get('mode') or 'film')
                        s.add(p)
                        s.flush()
                    s.query(db.PlaylistItem).filter(db.PlaylistItem.playlist_id == pid).delete(synchronize_session=False)
                    seen_urls = set()
                    for mi in items:
                        u = (mi.url or '').strip()
                        if not u: 
                            continue
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        kind = 'live'
                        if try_extract_tv_triplet(u) or guess_is_series(mi):
                            kind = 'series'
                        elif try_extract_movie_id(u) or guess_is_movie(mi):
                            kind = 'movie'
                        s.add(db.PlaylistItem(
                            playlist_id=pid,
                            original_url=u,
                            title=mi.title,
                            group_title=mi.group,
                            tvg_id=mi.tvg_id,
                            tvg_logo=mi.tvg_logo,
                            attrs=mi.attrs or {},
                            kind=kind,
                        ))
                    s.commit()
                it["last_refresh"] = config.now_ts()
            else:
                # Modalità legacy JSON: conversione e scrittura file .m3u
                src_settings = config.load_settings()
                if it.get("resolver_url"):
                    src_settings = {**src_settings, "resolvers": [{"name": "override", "url": it["resolver_url"]}]}
                out = m3u.convert_playlist_text(src, it["mode"], src_settings)
                out_path = os.path.join(config.PLAYLISTS_DIR, f"{pid}.m3u")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(out)
                it["last_refresh"] = config.now_ts()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Errore refresh: {e}")

    m3u.write_playlists_index(playlists)
    return {"ok": True}


@router.delete("/admin/playlists/{pid}")
def admin_delete_playlist(pid: str):
    items = m3u.read_playlists_index()
    new_items = [x for x in items if x.get("id") != pid]
    m3u.write_playlists_index(new_items)
    try:
        os.remove(os.path.join(config.PLAYLISTS_DIR, f"{pid}.m3u"))
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.get("/lists/{pid}.m3u")
def serve_playlist(pid: str):
    path = os.path.join(config.PLAYLISTS_DIR, f"{pid}.m3u")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Playlist non trovata")
    return FileResponse(path, media_type="audio/x-mpegurl", filename=f"{pid}.m3u")
