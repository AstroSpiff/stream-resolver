# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
import logging
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from urllib.parse import quote, urlparse

from app import config
from app.services.xtream import (
    now_ts,
    spawn_build,
    build_xtream_cache,
    stream_resolver_base,
    M3UItem,
    items_for_xtream_selection,
    split_mixed_items,
    build_live_streams,
    build_vod_streams,
    build_series_collections,
    require_xtream,
    get_and_validate_xtream,
    require_xt_id,
    require_xt_creds,
    xmltv_from_cache,
    build_vod_info,
)
from app.services import policies as pol
from app.logutil import redact_url
import httpx

router = APIRouter()
logger = logging.getLogger(__name__)


@router.api_route("/xtream/{xt_id}", methods=["GET", "HEAD"])
async def xt_root_stub(
    request: Request,
    xt_id: str,
    action: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    vod_id: Optional[str] = None,
    series_id: Optional[str] = None,
):
    if action is not None:
        return await xt_player_api(
            request,
            xt_id=xt_id,
            action=action,
            username=username,
            password=password,
            vod_id=vod_id,
            series_id=series_id,
        )
    return JSONResponse(
        {
            "status": "ok",
            "xt_id": xt_id,
            "api": {
                "player_api": f"/xtream/{xt_id}/player_api.php",
                "panel_api": f"/xtream/{xt_id}/panel_api.php",
                "get": f"/xtream/{xt_id}/get.php",
            },
        }
    )


@router.get("/xtream/{xt_id}/player_api.php")
async def xt_player_api(
    request: Request,
    xt_id: str,
    action: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    vod_id: Optional[str] = None,
    series_id: Optional[str] = None,
):
    if not username or not password:
        raise HTTPException(401, "Unauthorized")
    xt = require_xtream(xt_id, username, password)

    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    every_hours = int(xt.get("every_hours", 12) or 12)
    last_refresh = int(xt.get("last_refresh", 0) or 0)
    expired = now_ts() - last_refresh > every_hours * 3600

    cache_data: Optional[Dict[str, Any]] = config.read_json(cache_file, None)
    if expired and cache_data:
        spawn_build(stream_resolver_base(request), xt)
    if cache_data is None:
        base_override = (xt.get("resolver_url") or "").strip() or stream_resolver_base(request)
        cache_data = build_xtream_cache(base_override, xt)

    live_streams = cache_data.get("live_streams", [])
    vod_streams = cache_data.get("vod_streams", [])
    series_map = cache_data.get("series_map", {})
    live_cat_map = cache_data.get("live_categories", {})
    vod_cat_map = cache_data.get("vod_categories", {})
    series_cat_map = cache_data.get("series_categories", {})
    # Normalizza categorie vuote che possono arrivare come lista
    if isinstance(live_cat_map, list):
        live_cat_map = {}
    if isinstance(vod_cat_map, list):
        vod_cat_map = {}
    if isinstance(series_cat_map, list):
        series_cat_map = {}
    movie_items = [M3UItem(**m) for m in cache_data.get("movie_items", [])]
    counts = cache_data.get("counts", {})

    available_channels = counts.get("available_channels", len(live_streams))
    available_movies = counts.get("available_movies", len(vod_streams))
    available_series = counts.get("available_series", len(series_map))

    if action is None:
        try:
            base = (xt.get("resolver_url") or "").strip() or str(request.base_url).rstrip("/")
        except Exception:
            base = str(request.base_url).rstrip("/")
        now = now_ts()
        try:
            pu = urllib.parse.urlparse(base)
            proto = pu.scheme or "http"
            host = pu.hostname or "localhost"
            port_num = pu.port or (443 if proto == "https" else 80)
            port = str(port_num)
        except Exception:
            proto, host, port = "http", "localhost", "80"

        sel_live = set((xt.get('export_live_fields') or []))
        base_live_streams = []
        for s in live_streams:
            row = {
                "num": s.get("num"),
                "name": s.get("name"),
                "stream_type": "live",
                "stream_id": s.get("stream_id"),
                "stream_icon": s.get("stream_icon", ""),
                "epg_channel_id": s.get("epg_channel_id", ""),
                "category_id": str(s.get("category_id", "")),
                "added": s.get("added", ""),
                "is_adult": "0",
                "custom_sid": "",
                "tv_archive": 0,
                "tv_archive_duration": 0,
                "direct_source": s.get("direct_source"),
                "container_extension": "m3u8",
            }
            if 'category_name' in sel_live:
                row['category_name'] = s.get('category_name')
            if 'category_id' in sel_live:
                row['category_id'] = str(s.get('category_id', ''))
            if 'stream_type' in sel_live:
                row['stream_type'] = 'live'
            if 'rating' in sel_live and s.get('rating') is not None:
                row['rating'] = s.get('rating')
            if 'rating_5based' in sel_live and s.get('rating_5based') is not None:
                row['rating_5based'] = s.get('rating_5based')
            if 'added' in sel_live:
                row['added'] = s.get('added')
            if 'tv_archive' in sel_live:
                row['tv_archive'] = s.get('tv_archive')
            if 'tv_archive_duration' in sel_live:
                row['tv_archive_duration'] = s.get('tv_archive_duration')
            if 'direct_source' in sel_live:
                row['direct_source'] = s.get('direct_source')
            if 'custom_sid' in sel_live:
                row['custom_sid'] = s.get('custom_sid')
            base_live_streams.append(row)
        live_categories = [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(live_cat_map.items(), key=lambda x: x[1])
        ]
        vod_categories = [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(vod_cat_map.items(), key=lambda x: x[1])
        ]
        series_categories = [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(series_cat_map.items(), key=lambda x: x[1])
        ]

        return {
            "user_info": {
                "auth": 1,
                "status": "Active",
                "username": username,
                "password": password,
                "message": "",
                "is_trial": "0",
                "active_cons": 1,
                "created_at": now,
                "max_connections": 1,
                "allowed_output_formats": ["ts", "m3u8", "rtmp", "mp4"],
            },
            "server_info": {
                "url": host,
                "port": port,
                "https_port": port,
                "server_protocol": proto,
                "timestamp_now": now,
                "time_now": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
            },
            "available_channels": available_channels,
            "available_movies": available_movies,
            "available_series": available_series,
            "live_streams": base_live_streams,
            "live_categories": live_categories,
            "vod_categories": vod_categories,
            "series_categories": series_categories,
            "allowed_output_formats": ["ts", "m3u8", "rtmp", "mp4"],
        }

    if action == "get_live_categories":
        return (
            [{"category_id": "0", "category_name": "All", "parent_id": 0}]
            + [
                {"category_id": cid, "category_name": name, "parent_id": 0}
                for name, cid in sorted(live_cat_map.items(), key=lambda x: x[1])
            ]
        )

    if action == "get_live_streams":
        q = request.query_params
        cat = q.get("category_id")
        items = live_streams
        if cat and str(cat) not in ("0", "-1"):
            items = [s for s in items if str(s.get("category_id")) == str(cat)]
        ua = str(request.headers.get("user-agent", "")).lower()
        if "tivimate" in ua:
            sel_live = set((xt.get('export_live_fields') or []))
            minimal = []
            for s in items:
                row = {
                    "num": int(s.get("num", 0) or 0),
                    "name": s.get("name", ""),
                    "stream_type": "live",
                    "stream_id": int(s.get("stream_id", 0) or 0),
                    "category_id": str(s.get("category_id", "")),
                    "stream_icon": s.get("stream_icon", ""),
                    "epg_channel_id": s.get("epg_channel_id", ""),
                    "container_extension": "m3u8",
                    "stream_status": 1,
                }
                if 'category_name' in sel_live:
                    row['category_name'] = s.get('category_name')
                if 'rating' in sel_live and s.get('rating') is not None:
                    row['rating'] = s.get('rating')
                if 'rating_5based' in sel_live and s.get('rating_5based') is not None:
                    row['rating_5based'] = s.get('rating_5based')
                if 'added' in sel_live:
                    row['added'] = s.get('added')
                if 'tv_archive' in sel_live:
                    row['tv_archive'] = s.get('tv_archive')
                if 'tv_archive_duration' in sel_live:
                    row['tv_archive_duration'] = s.get('tv_archive_duration')
                if 'direct_source' in sel_live:
                    row['direct_source'] = s.get('direct_source')
                if 'custom_sid' in sel_live:
                    row['custom_sid'] = s.get('custom_sid')
                minimal.append(row)
            items = minimal
        try:
            limit = max(0, min(int(q.get("limit", 0)), 500))
        except ValueError:
            limit = 0
        try:
            page = max(1, int(q.get("page", 1)))
        except ValueError:
            page = 1
        if limit:
            start = (page - 1) * limit
            items = items[start : start + limit]
        return items

    if action == "get_vod_categories":
        return [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(vod_cat_map.items(), key=lambda x: x[1])
        ]

    if action == "get_vod_streams":
        q = request.query_params
        cat = q.get("category_id")
        items = vod_streams
        if cat and str(cat) not in ("0", "-1"):
            items = [s for s in items if str(s.get("category_id")) == str(cat)]
        try:
            limit = max(0, min(int(q.get("limit", 0)), 500))
        except ValueError:
            limit = 0
        try:
            page = max(1, int(q.get("page", 1)))
        except ValueError:
            page = 1
        if limit:
            start = (page - 1) * limit
            items = items[start : start + limit]
        return items

    if action == "get_vod_info":
        if not vod_id:
            raise HTTPException(400, "vod_id mancante")
        base_url = stream_resolver_base(request)
        out = build_vod_info(base_url, vod_id, movie_items, xt)
        # Applica export selezionati (Film) con overlay TMDB
        try:
            sel = set((xt.get('export_movie_fields') or []))
            if sel:
                # Trova item scelto per titolo/anno
                chosen: Optional[M3UItem] = None
                for it in movie_items:
                    mid = it.url.split('/')[-1]
                    try:
                        mid_int = int(mid)
                    except Exception:
                        mid_int = None
                    if str(mid_int) == str(vod_id):
                        chosen = it
                        break
                if not chosen:
                    for it in movie_items:
                        from app.services.xtream import crc32_num
                        if str(crc32_num(it.url)) == str(vod_id):
                            chosen = it
                            break
                from app.routers.admin_tmdb import _norm_title_year, _sig_for, _tmdb_image_url
                from app import db as _db
                from sqlalchemy import select
                lang = (config.load_settings().get('tmdb') or {}).get('language') or 'it-IT'
                if chosen:
                    t, y = _norm_title_year(chosen.title, chosen.attrs or {})
                    sig = _sig_for('movie', t, y)
                    with _db.SessionLocal() as s2:
                        m = s2.get(_db.TMDBMap, sig)
                        if m:
                            row = s2.get(_db.TMDBMovie, {"tmdb_id": m.tmdb_id, "language": lang})
                            if row:
                                info = out.get('info', {})
                                # overlay fields according to selection
                                if 'overview' in sel and (row.overview or '').strip():
                                    info['plot'] = row.overview
                                # Support either explicit 'poster' or 'movie_image' selection
                                if ('poster' in sel or 'movie_image' in sel) and (row.poster_path or '').strip():
                                    info['movie_image'] = _tmdb_image_url(row.poster_path)
                                    info['cover_big'] = info['movie_image']
                                if 'backdrop' in sel and row.backdrop_path:
                                    info['backdrop_path'] = [_tmdb_image_url(row.backdrop_path)]
                                if 'rating' in sel and row.rating is not None:
                                    info['rating'] = float(row.rating)
                                if 'year' in sel:
                                    yv = None
                                    if row.release_year:
                                        yv = str(row.release_year)
                                    elif row.release_date:
                                        try:
                                            yv = str(int((row.release_date or '').split('-')[0]))
                                        except Exception:
                                            yv = None
                                    if yv:
                                        info['year'] = yv
                                        info['releasedate'] = yv
                                if 'duration' in sel and row.runtime_mins:
                                    secs = int(row.runtime_mins) * 60
                                    info['duration_secs'] = str(secs)
                                    from app.services.xtream import _fmt_hhmmss as _fmt
                                    info['duration'] = _fmt(secs)
                                if 'duration_secs' in sel and row.runtime_mins:
                                    secs = int(row.runtime_mins) * 60
                                    info['duration_secs'] = str(secs)
                                if 'imdb_id' in sel and row.imdb_id:
                                    info['imdb_id'] = row.imdb_id
                                if 'genres' in sel and row.genres:
                                    # DB stores genres as CSV string
                                    info['genre'] = row.genres
                                if ('countries' in sel or 'country' in sel) and row.production_countries:
                                    info['country'] = row.production_countries
                                if 'production_countries' in sel and row.production_countries:
                                    info['production_countries'] = row.production_countries
                                if 'cast' in sel and row.cast:
                                    info['cast'] = row.cast
                                if 'director' in sel and row.director:
                                    info['director'] = row.director
                                if 'youtube_trailer' in sel and row.youtube_trailer:
                                    info['youtube_trailer'] = f"https://www.youtube.com/watch?v={row.youtube_trailer}"
                                if 'rating_5based' in sel and (info.get('rating') is not None):
                                    try:
                                        info['rating_5based'] = float(info.get('rating')) / 2.0
                                    except Exception:
                                        pass
                                if 'releasedate' in sel and (row.release_date or '').strip():
                                    info['releasedate'] = row.release_date
                                if 'tmdb_id' in sel:
                                    info['tmdb_id'] = str(row.tmdb_id)
                                out['info'] = info
                                # movie_data level additions
                                md = out.get('movie_data', {})
                                if 'direct_source' in sel:
                                    md['direct_source'] = md.get('direct_source') or ''
                                if 'custom_sid' in sel:
                                    md['custom_sid'] = md.get('custom_sid') or ''
                                if 'stream_icon' in sel:
                                    try:
                                        vs = next((x for x in vod_streams if str(x.get('stream_id')) == str(vod_id)), None)
                                        if vs and vs.get('stream_icon'):
                                            md['stream_icon'] = vs.get('stream_icon')
                                    except Exception:
                                        pass
                                out['movie_data'] = md
                # Merge from cached VOD list where possible (bitrate/added/category_id)
                try:
                    vs = next((x for x in vod_streams if str(x.get('stream_id')) == str(vod_id)), None)
                    if vs:
                        if 'bitrate' in sel:
                            out['info']['bitrate'] = vs.get('bitrate')
                        if 'added' in sel:
                            out['movie_data']['added'] = vs.get('added') or out['movie_data'].get('added', '')
                        if 'category_id' in sel:
                            out['movie_data']['category_id'] = vs.get('category_id')
                        if 'category_ids' in sel:
                            try:
                                out['movie_data']['category_ids'] = [vs.get('category_id')] if vs.get('category_id') else []
                            except Exception:
                                pass
                        if 'num' in sel and vs.get('num') is not None:
                            out['movie_data']['num'] = vs.get('num')
                        if 'direct_source' in sel and (vs.get('direct_source')):
                            out['movie_data']['direct_source'] = vs.get('direct_source')
                except Exception:
                    pass
        except Exception:
            # Overlay best-effort; non fatale
            pass
        return out

    if action == "get_short_epg":
        return {"epg_listings": []}

    if action == "get_simple_data_table":
        return {"epg_listings": []}

    if action == "get_series_categories":
        return [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(series_cat_map.items(), key=lambda x: x[1])
        ]

    if action == "get_series":
        out = []
        sel = set((xt.get('export_series_fields') or []))
        from app.routers.admin_tmdb import _norm_title_year, _sig_for, _tmdb_image_url
        from app import db as _db
        lang = (config.load_settings().get('tmdb') or {}).get('language') or 'it-IT'
        for sid, s in series_map.items():
            row_out = {
                "series_id": s.get("series_id"),
                "name": s.get("name"),
                "cover": s.get("cover"),
                "plot": s.get("plot"),
                "rating": s.get("rating"),
                "category_id": s.get("category_id"),
            }
            if sel:
                try:
                    t, _ = _norm_title_year(s.get('name') or '', {})
                    sig = _sig_for('series', t, None)
                    with _db.SessionLocal() as s2:
                        m = s2.get(_db.TMDBMap, sig)
                        if m:
                            row = s2.get(_db.TMDBSeries, {"tmdb_id": m.tmdb_id, "language": lang})
                            if row:
                                if 'overview' in sel and (row.overview or '').strip():
                                    row_out['plot'] = row.overview
                                if ('poster' in sel or 'cover' in sel) and (row.poster_path or '').strip():
                                    row_out['cover'] = _tmdb_image_url(row.poster_path)
                                if 'rating' in sel and row.rating is not None:
                                    row_out['rating'] = float(row.rating)
                                if 'tmdb_id' in sel:
                                    row_out['tmdb_id'] = str(row.tmdb_id)
                                if 'imdb_id' in sel and row.imdb_id:
                                    row_out['imdb_id'] = row.imdb_id
                                if 'origin_country' in sel and row.origin_country:
                                    row_out['origin_country'] = row.origin_country
                                if 'youtube_trailer' in sel and row.youtube_trailer:
                                    row_out['youtube_trailer'] = f"https://www.youtube.com/watch?v={row.youtube_trailer}"
                                if 'network' in sel and row.networks:
                                    row_out['network'] = row.networks
                                if 'status' in sel and row.status:
                                    row_out['status'] = row.status
                except Exception:
                    pass
            if 'num' in sel:
                row_out['num'] = len(out) + 1
            if 'stream_type' in sel:
                row_out['stream_type'] = 'series'
            if 'cover_big' in sel and row_out.get('cover'):
                row_out['cover_big'] = row_out.get('cover')
            if 'category_ids' in sel and row_out.get('category_id') is not None:
                try:
                    row_out['category_ids'] = [row_out.get('category_id')]
                except Exception:
                    pass
            out.append(row_out)
        q = request.query_params
        cat = q.get("category_id")
        if cat:
            out = [x for x in out if str(x.get("category_id")) == str(cat)]
        try:
            limit = max(0, min(int(q.get("limit", 0)), 500))
        except ValueError:
            limit = 0
        try:
            page = max(1, int(q.get("page", 1)))
        except ValueError:
            page = 1
        if limit:
            start = (page - 1) * limit
            out = out[start : start + limit]
        return out

    if action == "get_series_info":
        if not series_id:
            raise HTTPException(400, "series_id mancante")
        s = series_map.get(str(series_id))
        if not s:
            raise HTTPException(404, "Serie non trovata")
        info = {
            "name": s.get("name"),
            "cover": s.get("cover"),
            "plot": s.get("plot"),
            "rating": s.get("rating"),
            "releaseDate": None,
            "stream_type": "series",
            "series_id": s.get("series_id"),
            "backdrop_path": [],
        }
        seasons_list = []
        for k in sorted(s.get("episodes_by_season", {}).keys(), key=lambda x: int(x)):
            seasons_list.append(
                {
                    "air_date": "",
                    "episode_count": len(s["episodes_by_season"][k]),
                    "season_number": int(k),
                    "name": f"Season {int(k)}",
                }
            )
        # Overlay TMDB secondo selezione export
        try:
            sel_s = set((xt.get('export_series_fields') or []))
            sel_e = set((xt.get('export_episode_fields') or []))
            sel_season = set((xt.get('export_season_fields') or []))
            from app.routers.admin_tmdb import _norm_title_year, _sig_for, _tmdb_image_url
            from app import db as _db
            from sqlalchemy import select
            lang = (config.load_settings().get('tmdb') or {}).get('language') or 'it-IT'
            t, _ = _norm_title_year(s.get('name') or '', {})
            sig = _sig_for('series', t, None)
            with _db.SessionLocal() as s2:
                m = s2.get(_db.TMDBMap, sig)
                if m:
                    row = s2.get(_db.TMDBSeries, {"tmdb_id": m.tmdb_id, "language": lang})
                    if row and sel_s:
                        if 'overview' in sel_s and (row.overview or '').strip():
                            info['plot'] = row.overview
                        if ('poster' in sel_s or 'cover' in sel_s) and (row.poster_path or '').strip():
                            info['cover'] = _tmdb_image_url(row.poster_path)
                        if 'backdrop' in sel_s and row.backdrop_path:
                            info['backdrop_path'] = [_tmdb_image_url(row.backdrop_path)]
                        if 'rating' in sel_s and row.rating is not None:
                            info['rating'] = float(row.rating)
                        if 'rating_5based' in sel_s and row.rating is not None:
                            try:
                                info['rating_5based'] = float(row.rating) / 2.0
                            except Exception:
                                pass
                        if 'year' in sel_s:
                            if row.first_year:
                                info['releaseDate'] = str(row.first_year)
                            elif row.first_air_date:
                                try:
                                    info['releaseDate'] = str(int((row.first_air_date or '').split('-')[0]))
                                except Exception:
                                    pass
                        if 'releaseDate' in sel_s and (row.first_air_date or '').strip():
                            info['releaseDate'] = row.first_air_date
                        if 'genre' in sel_s and row.genres:
                            info['genre'] = row.genres
                        if 'cast' in sel_s and row.cast:
                            info['cast'] = row.cast
                        if 'director' in sel_s and row.created_by:
                            info['director'] = row.created_by
                        if 'episode_run_time' in sel_s and row.episode_run_time_mins:
                            info['episode_run_time'] = str(row.episode_run_time_mins)
                        if 'tmdb_id' in sel_s:
                            info['tmdb_id'] = str(row.tmdb_id)
                        if 'imdb_id' in sel_s and row.imdb_id:
                            info['imdb_id'] = row.imdb_id
                        if 'origin_country' in sel_s and row.origin_country:
                            info['origin_country'] = row.origin_country
                        if 'youtube_trailer' in sel_s and row.youtube_trailer:
                            info['youtube_trailer'] = f"https://www.youtube.com/watch?v={row.youtube_trailer}"
                        if 'network' in sel_s and row.networks:
                            info['network'] = row.networks
                        if 'status' in sel_s and row.status:
                            info['status'] = row.status
                    # Episodi: arricchisci ogni episodio se richiesto
                    if sel_e:
                        eps_by_season = s.get('episodes_by_season', {})
                        new_eps = {}
                        for skey, eps in eps_by_season.items():
                            season_num = int(skey)
                            new_list = []
                            for ep in eps:
                                ep_num = int(ep.get('episode_num') or 0)
                                ep_info = dict(ep.get('info') or {})
                                # Trova episodio TMDB
                                q = s2.query(_db.TMDBEpisode).filter(
                                    _db.TMDBEpisode.tmdb_series_id == m.tmdb_id,
                                    _db.TMDBEpisode.language == lang,
                                    _db.TMDBEpisode.season == season_num,
                                    _db.TMDBEpisode.episode == ep_num,
                                ).first()
                                if q:
                                    if 'name' in sel_e and (q.name or '').strip():
                                        ep['title'] = q.name
                                    if ('overview' in sel_e or 'plot' in sel_e) and (q.overview or '').strip():
                                        ep_info['plot'] = q.overview
                                    if 'duration' in sel_e and q.duration_mins:
                                        secs = int(q.duration_mins) * 60
                                        ep_info['duration'] = str(secs)
                                        ep_info['duration_secs'] = str(secs)
                                        from app.services.xtream import _fmt_hhmmss as _fmt
                                        ep_info['duration_fmt'] = _fmt(secs)
                                    if 'duration_secs' in sel_e and q.duration_mins:
                                        secs = int(q.duration_mins) * 60
                                        ep_info['duration_secs'] = str(secs)
                                    if 'still' in sel_e and (q.still_path or '').strip():
                                        ep_info['movie_image'] = _tmdb_image_url(q.still_path)
                                    if 'backdrop_path' in sel_e and (q.still_path or '').strip():
                                        ep_info['backdrop_path'] = [_tmdb_image_url(q.still_path)]
                                    if 'air_date' in sel_e and (q.air_date or '').strip():
                                        ep_info['air_date'] = q.air_date
                                    if 'guest_stars' in sel_e and q.guest_stars:
                                        try:
                                            if isinstance(q.guest_stars, list):
                                                ep_info['guest_stars'] = ", ".join([str(x) for x in q.guest_stars])
                                            else:
                                                ep_info['guest_stars'] = str(q.guest_stars)
                                        except Exception:
                                            pass
                                    if 'crew' in sel_e and q.crew:
                                        try:
                                            if isinstance(q.crew, list):
                                                ep_info['crew'] = ", ".join([str(x) for x in q.crew])
                                            else:
                                                ep_info['crew'] = str(q.crew)
                                        except Exception:
                                            pass
                                    if 'rating' in sel_e and q.vote_average is not None:
                                        ep_info['rating'] = float(q.vote_average)
                                    if 'releaseDate' in sel_e and (q.air_date or '').strip():
                                        ep_info['releasedate'] = q.air_date
                                    if 'imdb_id' in sel_e and q.imdb_id:
                                        ep_info['imdb_id'] = q.imdb_id
                                    if 'tmdb_id' in sel_e and q.episode_tmdb_id:
                                        ep_info['tmdb_id'] = str(q.episode_tmdb_id)
                                if 'added' in sel_e:
                                    ep['added'] = ep.get('added', '')
                                if 'custom_sid' in sel_e:
                                    ep['custom_sid'] = ep.get('custom_sid', '')
                                ep['info'] = ep_info
                                new_list.append(ep)
                            new_eps[skey] = new_list
                        s['episodes_by_season'] = new_eps
                    # Seasons: enrich season list according to selection (from tmdb_seasons)
                    if sel_season and row:
                        try:
                            from app import db as _db
                            s_rows = s2.query(_db.TMDBSeason).filter(
                                _db.TMDBSeason.tmdb_series_id == m.tmdb_id,
                                _db.TMDBSeason.language == lang,
                            ).all()
                            seasons_by_num = {int(x.season_number): x for x in s_rows}
                            new_seasons = []
                            for ss in seasons_list:
                                snum = int(ss.get('season_number') or 0)
                                srow = seasons_by_num.get(snum)
                                if srow:
                                    if 'name' in sel_season and (srow.name or '').strip():
                                        ss['name'] = srow.name
                                    if 'poster_path' in sel_season and (srow.poster_path or '').strip():
                                        ss['poster_path'] = srow.poster_path
                                    if 'cover' in sel_season and (srow.poster_path or '').strip():
                                        ss['cover'] = _tmdb_image_url(str(srow.poster_path))
                                    if 'air_date' in sel_season and (srow.air_date or '').strip():
                                        ss['air_date'] = srow.air_date
                                    if 'id' in sel_season and srow.season_tmdb_id:
                                        ss['id'] = str(srow.season_tmdb_id)
                                new_seasons.append(ss)
                            seasons_list = new_seasons
                        except Exception:
                            pass
        except Exception:
            pass
        return {"info": info, "episodes": s.get("episodes_by_season", {}), "seasons": seasons_list}

    raise HTTPException(400, f"action non supportata: {action}")


@router.get("/xtream/{xt_id}/panel_api.php")
async def xt_panel_api(
    request: Request,
    xt_id: str,
    action: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    vod_id: Optional[str] = None,
    series_id: Optional[str] = None,
):
    if action:
        return await xt_player_api(
            request,
            xt_id,
            action=action,
            username=username,
            password=password,
            vod_id=vod_id,
            series_id=series_id,
        )
    if not username or not password:
        raise HTTPException(401, "Unauthorized")
    xt = require_xtream(xt_id, username, password)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    cache_data: Optional[Dict[str, Any]] = config.read_json(cache_file, None)
    every_hours = int(xt.get("every_hours", 12) or 12)
    last_refresh = int(xt.get("last_refresh", 0) or 0)
    if (cache_data is not None) and (now_ts() - last_refresh > every_hours * 3600):
        spawn_build(stream_resolver_base(request), xt)
    if cache_data is None:
        cache_data = build_xtream_cache(stream_resolver_base(request), xt)

    live_streams = cache_data.get("live_streams", [])
    vod_streams = cache_data.get("vod_streams", [])
    series_map = cache_data.get("series_map", {})
    live_cat_map = cache_data.get("live_categories", {})
    vod_cat_map = cache_data.get("vod_categories", {})
    series_cat_map = cache_data.get("series_categories", {})

    base = str(request.base_url).rstrip("/")
    now = now_ts()
    try:
        pu = urllib.parse.urlparse(base)
        proto = pu.scheme or "http"
        host = pu.hostname or "localhost"
        port_num = pu.port or (443 if proto == "https" else 80)
        port = str(port_num)
    except Exception:
        proto, host, port = "http", "localhost", "80"

    user_info = {
        "auth": 1,
        "status": "Active",
        "username": username,
        "password": password,
        "message": "",
        "is_trial": "0",
        "active_cons": 1,
        "created_at": now,
        "max_connections": 1,
        "allowed_output_formats": ["ts", "m3u8", "rtmp", "mp4"],
    }
    server_info = {
        "url": host,
        "port": port,
        "https_port": port,
        "server_protocol": proto,
        "timestamp_now": now,
        "time_now": "",
    }
    return {
        "user_info": user_info,
        "server_info": server_info,
        "live_categories": [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(live_cat_map.items(), key=lambda x: x[1])
        ],
        "vod_categories": [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(vod_cat_map.items(), key=lambda x: x[1])
        ],
        "series_categories": [
            {"category_id": cid, "category_name": name, "parent_id": 0}
            for name, cid in sorted(series_cat_map.items(), key=lambda x: x[1])
        ],
        "available_channels": len(live_streams),
        "available_movies": len(vod_streams),
        "available_series": len(series_map),
    }


@router.get("/xtream/{xt_id}/xmltv.php")
async def xt_xmltv(xt_id: str, username: Optional[str] = None, password: Optional[str] = None):
    if not username or not password:
        raise HTTPException(401, "Unauthorized")
    _ = require_xtream(xt_id, username, password)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    cache = config.read_json(cache_file, None)
    xml = xmltv_from_cache(cache)
    return PlainTextResponse(xml, media_type="application/xml")


@router.get("/xmltv.php")
async def root_xmltv(username: Optional[str] = None, password: Optional[str] = None, xt_id: Optional[str] = None):
    xt = get_and_validate_xtream(username, password, xt_id)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{require_xt_id(xt)}.json")
    cache = config.read_json(cache_file, None)
    xml = xmltv_from_cache(cache)
    return PlainTextResponse(xml, media_type="application/xml")


@router.get("/xtream/{xt_id}/get.php")
async def xt_get_php(
    request: Request,
    xt_id: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    playlist_type: str = "m3u",
    output: str = "ts",
):
    if not username or not password:
        raise HTTPException(401, "Unauthorized")
    xt = require_xtream(xt_id, username, password)
    # Raccogli e smista le liste in base al contenuto, includendo le miste
    live_items = items_for_xtream_selection(xt.get("live_list_ids", []))
    movie_items = items_for_xtream_selection(xt.get("movie_list_ids", []))
    series_items = items_for_xtream_selection(xt.get("series_list_ids", []))
    mixed_items = items_for_xtream_selection(xt.get("mixed_list_ids", []))
    m_live, m_movies, m_series = split_mixed_items(mixed_items)
    live_items += m_live
    movie_items += m_movies
    series_items += m_series
    base_url = (xt.get("resolver_url") or "").strip() or stream_resolver_base(request)
    live_streams, _ = build_live_streams(base_url, live_items, xt)
    vod_streams, _ = build_vod_streams(base_url, movie_items, xt)
    series_map, _ = build_series_collections(base_url, series_items, xt)
    lines = ["#EXTM3U"]
    used_tvg_counts: Dict[str, int] = {}
    used_tvg_set: set[str] = set()
    for s in live_streams:
        name = s["name"]
        logo = s.get("stream_icon", "")
        grp = s.get("category_name") or s.get("category_id", "")
        base_id = s.get("epg_channel_id") or s.get("tvg_id") or str(s.get("stream_id")) or "ch"
        tvgid = base_id
        if tvgid in used_tvg_set:
            used_tvg_counts[base_id] = used_tvg_counts.get(base_id, 0) + 1
            i = used_tvg_counts[base_id]
            while f"{base_id}_{i}" in used_tvg_set:
                i += 1
            tvgid = f"{base_id}_{i}"
            used_tvg_counts[base_id] = i
        used_tvg_set.add(tvgid)
        url = s["direct_source"]
        lines.append(f'#EXTINF:-1 tvg-id="{tvgid}" tvg-logo="{logo}" group-title="{grp}",{name}')
        lines.append(url)
    for s in vod_streams:
        name = s["name"]
        logo = s.get("stream_icon", "")
        grp = s.get("category_name") or s.get("category_id", "")
        url = s["direct_source"]
        try:
            dur = int(float(s.get("duration") or 0))
        except (TypeError, ValueError):
            dur = 0
        if dur <= 0:
            dur = 1
        lines.append(f'#EXTINF:{dur} tvg-logo="{logo}" group-title="{grp}",{name}')
        lines.append(url)
    for sid, sm in series_map.items():
        cover = sm["cover"]
        grp = sm.get("category_name") or sm.get("category_id", "")
        for season, eps in sm["episodes_by_season"].items():
            for ep in eps:
                title = f'{sm["name"]} {ep["title"]}'
                url = ep["direct_source"]
                try:
                    dur = int(float(ep.get("info", {}).get("duration") or 0))
                except (TypeError, ValueError):
                    dur = 0
                if dur <= 0:
                    dur = 1
                lines.append(f'#EXTINF:{dur} tvg-logo="{cover}" group-title="{grp}",{title}')
                lines.append(url)
    txt = "\n".join(lines) + "\n"
    return PlainTextResponse(txt, media_type="audio/x-mpegurl")


@router.get("/get.php")
async def root_get_php(
    request: Request,
    username: Optional[str] = None,
    password: Optional[str] = None,
    type: str = "m3u",
    output: str = "ts",
    xt_id: Optional[str] = None,
):
    xt = get_and_validate_xtream(username, password, xt_id)
    xt_user, xt_pass = require_xt_creds(xt)
    return await xt_get_php(
        request,
        xt_id=require_xt_id(xt),
        username=xt_user,
        password=xt_pass,
        playlist_type=type,
        output=output,
    )


@router.get("/xtream/{xt_id}/live/{u}/{p}/{stream_id}.{ext}")
async def xt_live_redirect(request: Request, xt_id: str, u: str, p: str, stream_id: str, ext: str):
    logger = logging.getLogger(__name__)
    xt = require_xtream(xt_id, u, p)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    data = config.read_json(cache_file, {})
    for s in data.get("live_streams", []):
        if str(s.get("stream_id")) == str(stream_id):
            url = s.get("direct_source")
            if url:
                # Se è un link interno /tv?u=..., prova ad applicare subito la policy (mediaflow) per massima compatibilità client
                try:
                    from urllib.parse import urlparse, parse_qs
                    pu = urlparse(url)
                    if pu.path.rstrip('/') == '/tv':
                        qs = parse_qs(pu.query)
                        orig = (qs.get('u') or [''])[0]
                        logger.info("xtream/live: stream_id=%s ext=%s direct_source=/tv u=%s", stream_id, ext, redact_url(orig))
                        if orig:
                            out = pol.apply_policy(request, orig, 'tv')
                            if out and out.get('ok') and out.get('resolvedUrl'):
                                target = out['resolvedUrl']
                                logger.info("xtream/live: policy resolved -> %s", redact_url(target))
                                # Optional precheck to log proxy reachability
                                if os.environ.get("MF_PRECHECK_HEAD", "").lower() in ("1","true","yes"):
                                    try:
                                        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as cli:
                                            r = await cli.head(target)
                                            logger.info("xtream/live: precheck HEAD %s -> %s", redact_url(target), r.status_code)
                                    except Exception as e:
                                        logger.warning("xtream/live: precheck error for %s: %s", redact_url(target), e)
                                # For TiviMate and similar, a first URL ending with .m3u8 helps extractor selection
                                # Se il target è un manifest HLS, restituisci un piccolo master .m3u8
                                # così il client sceglie HLS senza ulteriori redirect.
                                if 'm3u8' in (target or '').lower():
                                    body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=1500000\n" + target + "\n"
                                    logger.info("xtream/live: serving inline M3U8 stub -> %s", redact_url(target))
                                    return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl")
                                # Altrimenti, redirect diretto al target risolto
                                logger.info("xtream/live: redirecting directly to target %s", redact_url(target))
                                return RedirectResponse(url=target, status_code=302)
                except Exception:
                    logger.exception("xtream/live: error applying policy for stream_id=%s", stream_id)
                # Fallback: redirect to the original direct source URL
                # Ensure absolute URL for fallback
                try:
                    if url.startswith("/"):
                        base = (xt.get('resolver_url') or '').strip() or stream_resolver_base(request)
                        url_abs = base.rstrip('/') + url
                    else:
                        url_abs = url
                except Exception:
                    url_abs = url
                logger.info("xtream/live: fallback redirect to direct_source %s", redact_url(url_abs))
                return RedirectResponse(url=url_abs, status_code=302)
            break
    raise HTTPException(404, "Live stream non trovato")


@router.get("/xtream/{xt_id}/movie/{u}/{p}/{stream_id}.{ext}")
async def xt_movie_redirect(request: Request, xt_id: str, u: str, p: str, stream_id: str, ext: str):
    xt = require_xtream(xt_id, u, p)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    data = config.read_json(cache_file, {})
    for s in data.get("vod_streams", []):
        if str(s.get("stream_id")) == str(stream_id):
            url = s.get("direct_source")
            if url:
                # Apply policy if it's an internal /tv link
                try:
                    from urllib.parse import urlparse, parse_qs, quote as _quote
                    pu = urlparse(url)
                    if pu.path.rstrip('/') == '/tv':
                        qs = parse_qs(pu.query)
                        orig = (qs.get('u') or [''])[0]
                        out = pol.apply_policy(request, orig, 'tv')
                        if out and out.get('ok') and out.get('resolvedUrl'):
                            target = out['resolvedUrl']
                            ua = (request.headers.get('user-agent') or '').lower()
                            # Se è HLS, serviamo uno stub M3U8 (no proxy)
                            if 'm3u8' in (target or '').lower():
                                body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=1500000\n" + target + "\n"
                                logger.info("xtream/movie: serving inline M3U8 stub -> %s", redact_url(target))
                                return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl")
                            logger.info("xtream/movie: redirecting directly to target %s", redact_url(target))
                            return RedirectResponse(url=target, status_code=302)
                except Exception:
                    pass
                # Fallback: redirect to direct source (absolute)
                try:
                    if url.startswith('/'):
                        base = (xt.get('resolver_url') or '').strip() or stream_resolver_base(request)
                        url_abs = base.rstrip('/') + url
                    else:
                        url_abs = url
                except Exception:
                    url_abs = url
                return RedirectResponse(url=url_abs, status_code=302)
            break
    raise HTTPException(404, "VOD stream non trovato")


@router.get("/xtream/{xt_id}/series/{u}/{p}/{series_id}/{season}/{episode}.{ext}")
async def xt_series_redirect(
    request: Request, xt_id: str, u: str, p: str, series_id: str, season: int, episode: int, ext: str
):
    xt = require_xtream(xt_id, u, p)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    data = config.read_json(cache_file, {})
    sm = data.get("series_map", {}).get(str(series_id))
    if not sm:
        raise HTTPException(404, "Serie non trovata")
    ep_code = f"S{int(season):02d}E{int(episode):02d}"
    for ep in sm.get("episodes_by_season", {}).get(str(season), []):
        if ep.get("title") == ep_code:
            url = ep.get("direct_source")
            if url:
                # Apply policy if it's an internal /tv link
                try:
                    from urllib.parse import urlparse, parse_qs, quote as _quote
                    pu = urlparse(url)
                    if pu.path.rstrip('/') == '/tv':
                        qs = parse_qs(pu.query)
                        orig = (qs.get('u') or [''])[0]
                        out = pol.apply_policy(request, orig, 'tv')
                        if out and out.get('ok') and out.get('resolvedUrl'):
                            target = out['resolvedUrl']
                            ua = (request.headers.get('user-agent') or '').lower()
                            if 'm3u8' in (target or '').lower():
                                body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=1500000\n" + target + "\n"
                                logger.info("xtream/series: serving inline M3U8 stub -> %s", redact_url(target))
                                return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl")
                            logger.info("xtream/series: redirecting directly to target %s", redact_url(target))
                            return RedirectResponse(url=target, status_code=302)
                except Exception:
                    pass
                # Fallback: absolute direct source
                try:
                    if url.startswith('/'):
                        base = (xt.get('resolver_url') or '').strip() or stream_resolver_base(request)
                        url_abs = base.rstrip('/') + url
                    else:
                        url_abs = url
                except Exception:
                    url_abs = url
                return RedirectResponse(url=url_abs, status_code=302)
            break
    raise HTTPException(404, "Episodio non trovato")


@router.get("/xtream/{xt_id}/series/{u}/{p}/{episode_id}.{ext}")
async def xt_series_by_epid_redirect(request: Request, xt_id: str, u: str, p: str, episode_id: str, ext: str):
    xt = require_xtream(xt_id, u, p)
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    data = config.read_json(cache_file, {})
    series_map = data.get("series_map", {})
    for sid, sm in series_map.items():
        for eps in sm.get("episodes_by_season", {}).values():
            for ep in eps:
                if str(ep.get("id")) == str(episode_id):
                    url = ep.get("direct_source")
                    if url:
                        try:
                            from urllib.parse import urlparse, parse_qs, quote as _quote
                            pu = urlparse(url)
                            if pu.path.rstrip('/') == '/tv':
                                qs = parse_qs(pu.query)
                                orig = (qs.get('u') or [''])[0]
                                out = pol.apply_policy(request, orig, 'tv')
                                if out and out.get('ok') and out.get('resolvedUrl'):
                                    target = out['resolvedUrl']
                                    ua = (request.headers.get('user-agent') or '').lower()
                                    if 'm3u8' in (target or '').lower():
                                        body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=1500000\n" + target + "\n"
                                        logger.info("xtream/series-epid: serving inline M3U8 stub -> %s", redact_url(target))
                                        return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl")
                                    logger.info("xtream/series-epid: redirecting directly to target %s", redact_url(target))
                                    return RedirectResponse(url=target, status_code=302)
                        except Exception:
                            pass
                        # Fallback: absolute direct source
                        try:
                            if url.startswith('/'):
                                base = (xt.get('resolver_url') or '').strip() or stream_resolver_base(request)
                                url_abs = base.rstrip('/') + url
                            else:
                                url_abs = url
                        except Exception:
                            url_abs = url
                        return RedirectResponse(url=url_abs, status_code=302)
    raise HTTPException(404, "Episodio non trovato")


@router.get("/live/{u}/{p}/{stream_id}.{ext}")
async def live_no_xt(request: Request, u: str, p: str, stream_id: str, ext: str):
    xt = get_and_validate_xtream(u, p, None)
    return await xt_live_redirect(
        request,
        xt_id=require_xt_id(xt),
        u=u,
        p=p,
        stream_id=stream_id,
        ext=ext,
    )



@router.get("/movie/{u}/{p}/{stream_id}.{ext}")
async def movie_no_xt(request: Request, u: str, p: str, stream_id: str, ext: str):
    xt = get_and_validate_xtream(u, p, None)
    return await xt_movie_redirect(request, xt_id=require_xt_id(xt), u=u, p=p, stream_id=stream_id, ext=ext)


@router.get("/series/{u}/{p}/{series_id}/{season}/{episode}.{ext}")
async def series_no_xt(request: Request, u: str, p: str, series_id: str, season: int, episode: int, ext: str):
    xt = get_and_validate_xtream(u, p, None)
    return await xt_series_redirect(
        request,
        xt_id=require_xt_id(xt),
        u=u,
        p=p,
        series_id=series_id,
        season=season,
        episode=episode,
        ext=ext,
    )


@router.get("/series/{u}/{p}/{episode_id}.{ext}")
async def series_by_epid_no_xt(request: Request, u: str, p: str, episode_id: str, ext: str):
    xt = get_and_validate_xtream(u, p, None)
    return await xt_series_by_epid_redirect(
        request,
        xt_id=require_xt_id(xt),
        u=u,
        p=p,
        episode_id=episode_id,
        ext=ext,
    )


@router.get("/xtream/{xt_id}/redir/{u}/{p}/{name}.m3u8")
async def xt_minimal_redir(xt_id: str, u: str, p: str, name: str, target: Optional[str] = None):
    _ = require_xtream(xt_id, u, p)
    if not target:
        raise HTTPException(400, "target mancante")
    return RedirectResponse(url=target, status_code=302)

@router.get("/player_api.php")
async def root_player_api(
    request: Request,
    action: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    xt_id: Optional[str] = None,
    vod_id: Optional[str] = None,
    series_id: Optional[str] = None,
):
    xt = get_and_validate_xtream(username, password, xt_id)
    xt_user, xt_pass = require_xt_creds(xt)
    return await xt_player_api(
        request,
        xt_id=require_xt_id(xt),
        action=action,
        username=xt_user,
        password=xt_pass,
        vod_id=vod_id,
        series_id=series_id,
    )


@router.get("/panel_api.php")
async def root_panel_api(
    request: Request,
    action: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    xt_id: Optional[str] = None,
    vod_id: Optional[str] = None,
    series_id: Optional[str] = None,
):
    xt = get_and_validate_xtream(username, password, xt_id)
    xt_user, xt_pass = require_xt_creds(xt)
    return await xt_panel_api(
        request,
        xt_id=require_xt_id(xt),
        action=action,
        username=xt_user,
        password=xt_pass,
        vod_id=vod_id,
        series_id=series_id,
    )
