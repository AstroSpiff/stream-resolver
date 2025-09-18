# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path
from sqlalchemy import select
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
    order_num: Optional[int] = None
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

    # Gestione ordine (1..N) con auto-rinumerazione
    if data.order_num is not None:
        try:
            new_pos = max(1, int(data.order_num))
        except Exception:
            raise HTTPException(status_code=400, detail="order_num non valido")
        # Applica su DB per coerenza (backend=db)
        try:
            from app import db as _db
            with _db.SessionLocal() as s:
                rows = s.execute(select(_db.Playlist)).scalars().all()
                # Ordine attuale: per order_num poi name
                rows_sorted = sorted(rows, key=lambda r: ((r.order_num is None), (r.order_num or 10**9), r.name or ""))
                # Rimuovi target e reinserisci nella nuova posizione
                others = [r for r in rows_sorted if r.id != pid]
                new_pos = min(max(1, new_pos), len(others) + 1)
                ordered = others[: new_pos - 1] + [next(r for r in rows if r.id == pid)] + others[new_pos - 1 :]
                # Rinumerazione 1..N
                for idx, r in enumerate(ordered, start=1):
                    r.order_num = idx
                s.commit()
        except Exception:
            # Fallback: ignora errore ordine, non blocca altri campi
            pass

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
                    for mi in items:
                        u = (mi.url or '').strip()
                        if not u:
                            continue
                        kind = 'live'
                        series_id, season, episode = None, None, None
                        tv_triplet = try_extract_tv_triplet(u)
                        if tv_triplet:
                            kind = 'episode'
                            series_id, season, episode = tv_triplet
                        elif guess_is_series(mi):
                            kind = 'series'
                        elif try_extract_movie_id(u) or guess_is_movie(mi):
                            kind = 'movie'

                        # Normalizza attributi noti
                        a = mi.attrs or {}
                        def _as_int(x):
                            try:
                                return int(str(x).strip())
                            except Exception:
                                return None
                        def _as_bool_int(x):
                            s2 = str(x).strip().lower()
                            if s2 in ('1','true','yes','on'):
                                return 1
                            if s2 in ('0','false','no','off'):
                                return 0
                            return None
                        special = a.get('special') if isinstance(a, dict) else None
                        # Headers/licenza
                        h = (special.get('headers') if isinstance(special, dict) else {}) or {}
                        lic = (special.get('license') if isinstance(special, dict) else {}) or {}
                        fmt = (special.get('format') if isinstance(special, dict) else None) or None
                        reqp = 1 if (isinstance(special, dict) and special.get('requires_proxy')) else 0
                        # Pulisci dall'attrs i campi normalizzati in colonne
                        cleaned_attrs = {}
                        try:
                            cleaned_attrs = dict(a)
                            for k in ['tvg-chno','tvg-id','tvg-name','group-title','radio','karaoke']:
                                if k in cleaned_attrs:
                                    cleaned_attrs.pop(k, None)
                            # Se special presente, rimuovi i sotto-campi già mappati in colonne mantenendo eventuali altri
                            sp = cleaned_attrs.get('special') if isinstance(cleaned_attrs.get('special'), dict) else None
                            if sp:
                                for sk in ['headers','license','format','requires_proxy']:
                                    sp.pop(sk, None)
                                # Rimuovi special vuoto
                                if not sp:
                                    cleaned_attrs.pop('special', None)
                        except Exception:
                            cleaned_attrs = a or {}

                        s.add(db.PlaylistItem(
                            playlist_id=pid,
                            original_url=u,
                            title=mi.title,
                            group_title=mi.group,
                            tvg_id=mi.tvg_id,
                            tvg_logo=mi.tvg_logo,
                            tvg_chno=_as_int(a.get('tvg-chno')),
                            tvg_name=a.get('tvg-name') or None,
                            radio=_as_bool_int(a.get('radio')),
                            karaoke=_as_bool_int(a.get('karaoke')),
                            headers_user_agent=(h.get('User-Agent') or h.get('user-agent') or None),
                            headers_referer=(h.get('Referer') or h.get('referer') or None),
                            headers_origin=(h.get('Origin') or h.get('origin') or None),
                            headers_cookie=(h.get('Cookie') or h.get('cookie') or None),
                            license_type=(str(lic.get('type')).lower() if lic.get('type') else None),
                            clearkey_kid=(lic.get('key_id') or lic.get('kid') or None),
                            clearkey_key=(lic.get('key') or None),
                            stream_format=(fmt if fmt in ('hls','dash') else None),
                            requires_proxy=(reqp if reqp in (0,1) else None),
                            attrs=cleaned_attrs,
                            kind=kind,
                            series_id=series_id,
                            season=season,
                            episode=episode,
                        ))
                        # Upsert ingest status (movie/series/episode) for incremental TMDB processing
                        try:
                            from app.routers.admin_tmdb import _norm_title_year, _sig_for
                            now = config.now_ts()
                            if kind == 'movie':
                                t_norm, y = _norm_title_year(mi.title, mi.attrs or {})
                                sig = _sig_for('movie', t_norm, y)
                                row_st = s.execute(select(db.TMDBIngestStatus).where(db.TMDBIngestStatus.key_type=='movie', db.TMDBIngestStatus.movie_sig==sig)).scalar_one_or_none()
                                if not row_st:
                                    s.add(db.TMDBIngestStatus(key_type='movie', movie_sig=sig, title_norm=t_norm, year=y or None, status='pending', first_seen_ts=now, last_seen_ts=now))
                                else:
                                    row_st.last_seen_ts = now
                            elif kind == 'series':
                                t_norm, y = _norm_title_year(mi.title, mi.attrs or {})
                                sig = _sig_for('series', t_norm, y)
                                row_st = s.execute(select(db.TMDBIngestStatus).where(db.TMDBIngestStatus.key_type=='series', db.TMDBIngestStatus.series_sig==sig)).scalar_one_or_none()
                                if not row_st:
                                    s.add(db.TMDBIngestStatus(key_type='series', series_sig=sig, title_norm=t_norm, year=y or None, status='pending', first_seen_ts=now, last_seen_ts=now))
                                else:
                                    row_st.last_seen_ts = now
                            elif kind == 'episode' and series_id is not None and season is not None and episode is not None:
                                t_norm, _y = _norm_title_year(mi.title, mi.attrs or {})
                                sig = _sig_for('series', t_norm, None)
                                row_st = s.execute(select(db.TMDBIngestStatus).where(
                                    db.TMDBIngestStatus.key_type=='episode',
                                    db.TMDBIngestStatus.series_sig==sig,
                                    db.TMDBIngestStatus.season==season,
                                    db.TMDBIngestStatus.episode==episode,
                                )).scalar_one_or_none()
                                if not row_st:
                                    s.add(db.TMDBIngestStatus(key_type='episode', series_sig=sig, season=season, episode=episode, title_norm=t_norm, year=None, status='pending', first_seen_ts=now, last_seen_ts=now))
                                else:
                                    row_st.last_seen_ts = now
                        except Exception:
                            pass
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


class ReorderIn(BaseModel):
    order: List[str]


@router.post("/admin/playlists/reorder")
def admin_reorder_playlists(data: ReorderIn):
    ids = [str(x) for x in (data.order or [])]
    if not ids:
        raise HTTPException(400, "order mancante")
    try:
        from app import db as _db
        with _db.SessionLocal() as s:
            rows = s.execute(select(_db.Playlist)).scalars().all()
            by_id = {r.id: r for r in rows}
            ordered: List[_db.Playlist] = []
            for i in ids:
                r = by_id.get(i)
                if r:
                    ordered.append(r)
            # aggiungi eventuali rimanenti in coda mantenendo l'ordine attuale
            remaining = [r for r in rows if r.id not in ids]
            # mantieni l'ordine relativo di quelli senza posizione esplicita
            remaining_sorted = sorted(remaining, key=lambda r: ((r.order_num is None), (r.order_num or 10**9), r.name or ""))
            ordered.extend(remaining_sorted)
            # Rinumerazione 1..N
            for idx, r in enumerate(ordered, start=1):
                r.order_num = idx
            s.commit()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Errore riordino: {e}")


@router.delete("/admin/playlists/{pid}")
def admin_delete_playlist(pid: str):
    items = m3u.read_playlists_index()
    new_items = [x for x in items if x.get("id") != pid]
    m3u.write_playlists_index(new_items)
    try:
        os.remove(os.path.join(config.PLAYLISTS_DIR, f"{pid}.m3u"))
    except FileNotFoundError:
        pass
    # Backend DB: rimuovi playlist e items e ripulisci stati TMDB orfani
    if config.get_storage_backend() == 'db':
        try:
            from app import db as _db
            from sqlalchemy import select
            with _db.SessionLocal() as s:
                # Cancella elementi e playlist
                s.query(_db.PlaylistItem).filter(_db.PlaylistItem.playlist_id == pid).delete(synchronize_session=False)
                s.query(_db.Playlist).filter(_db.Playlist.id == pid).delete(synchronize_session=False)
                s.commit()
                # Ricalcola firme presenti per ripulire tmdb_ingest_status
                from app.routers.admin_tmdb import _norm_title_year, _sig_for
                rows = s.execute(select(_db.PlaylistItem)).scalars().all()
                movie_sigs: set[str] = set()
                series_sigs: set[str] = set()
                ep_triplets: set[tuple[str,int,int]] = set()
                for r in rows:
                    kind = (r.kind or 'live').lower()
                    # Calcola sempre la signature coerente con ingest
                    t_norm, y = _norm_title_year(r.title or '', (r.attrs or {}))
                    if kind == 'movie':
                        sig = _sig_for('movie', t_norm, y)
                        movie_sigs.add(sig)
                    elif kind == 'series':
                        sig = _sig_for('series', t_norm, None)
                        series_sigs.add(sig)
                    elif kind == 'episode':
                        sig = _sig_for('series', t_norm, None)
                        try:
                            if r.season is not None and r.episode is not None:
                                ep_triplets.add((sig, int(r.season), int(r.episode)))
                        except Exception:
                            pass
                # Cancella stati non più referenziati
                to_del = []
                sts = s.execute(select(_db.TMDBIngestStatus)).scalars().all()
                for st in sts:
                    kt = (st.key_type or '').lower()
                    if kt == 'movie':
                        if st.movie_sig and st.movie_sig not in movie_sigs:
                            to_del.append(st)
                    elif kt == 'series':
                        if st.series_sig and st.series_sig not in series_sigs:
                            to_del.append(st)
                    elif kt == 'episode':
                        trip = None
                        try:
                            if st.series_sig is not None and st.season is not None and st.episode is not None:
                                trip = (st.series_sig, int(st.season), int(st.episode))
                        except Exception:
                            trip = None
                        if trip and trip not in ep_triplets:
                            to_del.append(st)
                for st in to_del:
                    s.delete(st)
                if to_del:
                    s.commit()
        except Exception:
            # Non bloccare l'API se la pulizia fallisce
            pass
    return {"ok": True}


@router.get("/lists/{pid}.m3u")
def serve_playlist(pid: str):
    path = os.path.join(config.PLAYLISTS_DIR, f"{pid}.m3u")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Playlist non trovata")
    return FileResponse(path, media_type="audio/x-mpegurl", filename=f"{pid}.m3u")
