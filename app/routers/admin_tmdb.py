# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException

from app import config
from app import db

router = APIRouter()

_TMDB_JOB = {
    "running": False,
    "total": 0,
    "done": 0,
    "mode": "",
    "error": "",
}
_TMDB_STOP = threading.Event()


def _norm_title_year(title: str, attrs: Dict[str, str]) -> Tuple[str, Optional[int]]:
    import re
    t = (title or "").strip()
    # remove SxxEyy tokens
    t = re.sub(r"\bS\d{1,2}E\d{1,2}\b", "", t, flags=re.I).strip()
    # year from title or attrs
    year = None
    m = re.search(r"(19|20)\d{2}", t)
    if m:
        year = int(m.group(0))
    else:
        for k in ("tvg-year", "tvg_year", "year"):
            v = (attrs.get(k) or "").strip()
            m2 = re.search(r"(19|20)\d{2}", v)
            if m2:
                year = int(m2.group(0))
                break
    # strip year-in-parenthesis from title
    t = re.sub(r"\s*\([^()]*\)\s*", " ", t).strip()
    t = re.sub(r"\s+", " ", t)
    return t, year


def _sig_for(kind: str, title: str, year: Optional[int]) -> str:
    base = f"{kind}:{(title or '').lower()}:{year or 0}"
    import zlib
    return f"s{zlib.crc32(base.encode('utf-8')):08x}"


def _tmdb_image_url(path: str) -> str:
    if not path:
        return ""
    return f"https://image.tmdb.org/t/p/w500{path}"


def _run_tmdb_job(missing_only: bool):
    import httpx
    from sqlalchemy import select
    _TMDB_JOB.update({"running": True, "done": 0, "error": "", "mode": ("missing_only" if missing_only else "full")})
    _TMDB_STOP.clear()
    try:
        st = config.load_settings()
        tmdb = st.get("tmdb") or {}
        api_key = (tmdb.get("api_key") or "").strip()
        language = (tmdb.get("language") or "it-IT").strip()
        if not api_key:
            raise RuntimeError("TMDB API key non configurata")
        mf = set((tmdb.get("movie_fields") or []))
        if 'title' in mf: mf.add('name')
        movie_fields = mf
        sf = set((tmdb.get("series_fields") or []))
        series_fields = sf
        ef = set((tmdb.get("episode_fields") or []))
        episode_fields = ef
        with db.SessionLocal() as s:
            movies = s.execute(select(db.PlaylistItem).where(db.PlaylistItem.kind == 'movie')).scalars().all()
            series = s.execute(select(db.PlaylistItem).where(db.PlaylistItem.kind == 'series')).scalars().all()
            total = len(movies) + len(series)
            _TMDB_JOB["total"] = total
            client = httpx.Client(timeout=20.0, follow_redirects=True)
            # Movies
            for it in movies:
                if _TMDB_STOP.is_set():
                    _TMDB_JOB["error"] = "Interrotto dall'utente"
                    break
                t, y = _norm_title_year(it.title, it.attrs or {})
                sig = _sig_for('movie', t, y)
                mrow = s.get(db.TMDBMap, sig)
                tmdb_id = mrow.tmdb_id if mrow else None
                row = None
                if tmdb_id:
                    row = s.get(db.TMDBMovie, {"tmdb_id": tmdb_id, "language": language})
                need_fetch = False
                if not tmdb_id or not row:
                    need_fetch = True
                elif missing_only:
                    # fetch solo se qualche campo richiesto manca
                    for f in movie_fields:
                        if getattr(row, f"{ 'title' if f=='name' else f }", None) in (None, ""):
                            need_fetch = True
                            break
                if need_fetch:
                    # search
                    params = {"api_key": api_key, "query": t, "language": language}
                    if y:
                        params["year"] = y
                    r = client.get("https://api.themoviedb.org/3/search/movie", params=params)
                    data = r.json()
                    res = (data.get("results") or [])
                    if not res:
                        _TMDB_JOB["done"] += 1
                        continue
                    best = res[0]
                    tmdb_id = int(best.get("id"))
                    # details (more complete)
                    r2 = client.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}", params={"api_key": api_key, "language": language, "append_to_response": "videos,images,keywords,release_dates"})
                    det = r2.json()
                    # extras if needed
                    ext = {}
                    creds = {}
                    if any(k in movie_fields for k in ("imdb_id",)):
                        ext = client.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids", params={"api_key": api_key}).json()
                    if any(k in movie_fields for k in ("cast","director")):
                        creds = client.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits", params={"api_key": api_key}).json()
                    # upsert mapping
                    if not mrow:
                        s.add(db.TMDBMap(sig=sig, kind='movie', tmdb_id=tmdb_id))
                    else:
                        mrow.tmdb_id = tmdb_id
                    # upsert localized row
                    row = s.get(db.TMDBMovie, {"tmdb_id": tmdb_id, "language": language})
                    if not row:
                        row = db.TMDBMovie(tmdb_id=tmdb_id, language=language, title=det.get("title") or det.get("name") or "")
                        s.add(row)
                    # apply selected fields
                    if 'name' in movie_fields:
                        row.title = det.get("title") or row.title
                    if 'overview' in movie_fields:
                        row.overview = det.get("overview") or row.overview
                    if 'poster' in movie_fields:
                        row.poster_path = det.get("poster_path") or row.poster_path
                    if 'backdrop' in movie_fields:
                        row.backdrop_path = det.get("backdrop_path") or row.backdrop_path
                    if 'rating' in movie_fields:
                        row.rating = det.get("vote_average") or row.rating
                        try:
                            row.rating_votes = int(det.get('vote_count') or 0) or row.rating_votes
                        except Exception:
                            pass
                    if 'year' in movie_fields:
                        d = (det.get("release_date") or "")
                        try:
                            row.release_year = int(d.split("-")[0]) if d else row.release_year
                        except Exception:
                            pass
                    if 'duration' in movie_fields:
                        try:
                            row.runtime_mins = int(det.get("runtime") or 0) or row.runtime_mins
                        except Exception:
                            pass
                    if 'imdb_id' in movie_fields:
                        row.imdb_id = ext.get('imdb_id') or row.imdb_id
                    if 'genres' in movie_fields:
                        row.genres = [g.get('name') for g in (det.get('genres') or [])] or row.genres
                    if 'production_countries' in movie_fields:
                        row.production_countries = [c.get('name') for c in (det.get('production_countries') or [])] or row.production_countries
                    if 'cast' in movie_fields or 'director' in movie_fields:
                        cast_list = [c.get('name') for c in (creds.get('cast') or [])][:20]
                        dir_list = [c.get('name') for c in (creds.get('crew') or []) if (c.get('job') == 'Director')][:5]
                        if 'cast' in movie_fields and cast_list:
                            row.cast = ", ".join(cast_list)
                        if 'director' in movie_fields and dir_list:
                            row.director = ", ".join(dir_list)
                        if 'writers' in movie_fields:
                            wjobs = {"Writer","Screenplay","Story","Author"}
                            wr = [c.get('name') for c in (creds.get('crew') or []) if (c.get('job') in wjobs)]
                            if wr:
                                row.writers = list(dict.fromkeys(wr))
                    if 'logo' in movie_fields:
                        imgs = (det.get('images') or {})
                        logos = imgs.get('logos') or []
                        if logos:
                            row.logo_path = logos[0].get('file_path') or row.logo_path
                    # Extended movie fields
                    if 'original_title' in movie_fields:
                        row.original_title = det.get('original_title') or row.original_title
                    if 'original_language' in movie_fields:
                        row.original_language = det.get('original_language') or row.original_language
                    if 'tagline' in movie_fields:
                        row.tagline = det.get('tagline') or row.tagline
                    if 'release_date' in movie_fields:
                        row.release_date = det.get('release_date') or row.release_date
                    if 'status' in movie_fields:
                        row.status = det.get('status') or row.status
                    if 'collection' in movie_fields:
                        bc = det.get('belongs_to_collection') or {}
                        if bc:
                            row.collection = {k: bc.get(k) for k in ('id','name','poster_path','backdrop_path')}
                    if 'youtube_trailer' in movie_fields:
                        vids = (det.get('videos') or {}).get('results') or []
                        yt = next((v for v in vids if (v.get('site') == 'YouTube' and (v.get('type') or '').lower() == 'trailer' and v.get('key'))), None)
                        row.youtube_trailer = (yt.get('key') if yt else row.youtube_trailer) or row.youtube_trailer
                    if 'images' in movie_fields:
                        imgs = det.get('images') or {}
                        row.images = {
                            'posters': [p.get('file_path') for p in (imgs.get('posters') or []) if p.get('file_path')],
                            'backdrops': [b.get('file_path') for b in (imgs.get('backdrops') or []) if b.get('file_path')],
                            'logos': [l.get('file_path') for l in (imgs.get('logos') or []) if l.get('file_path')],
                        }
                    if 'production_companies' in movie_fields:
                        row.production_companies = [c.get('name') for c in (det.get('production_companies') or []) if c.get('name')]
                    if 'production_countries' in movie_fields:
                        row.production_countries = [c.get('name') for c in (det.get('production_countries') or []) if c.get('name')]
                    if 'keywords' in movie_fields:
                        kw = det.get('keywords') or {}
                        arr = (kw.get('keywords') if isinstance(kw.get('keywords'), list) else kw.get('results')) or []
                        row.keywords = [k.get('name') for k in arr if k.get('name')]
                    if 'spoken_languages' in movie_fields:
                        row.spoken_languages = [l.get('iso_639_1') or l.get('name') for l in (det.get('spoken_languages') or []) if (l.get('iso_639_1') or l.get('name'))]
                    if 'revenue' in movie_fields:
                        try:
                            row.revenue = int(det.get('revenue') or 0) or row.revenue
                        except Exception:
                            pass
                    if 'budget' in movie_fields:
                        try:
                            row.budget = int(det.get('budget') or 0) or row.budget
                        except Exception:
                            pass
                    if 'popularity' in movie_fields:
                        try:
                            row.popularity = float(det.get('popularity') or 0) or row.popularity
                        except Exception:
                            pass
                    if 'certification' in movie_fields:
                        try:
                            rds = (det.get('release_dates') or {}).get('results') or []
                            # prefer IT, then US
                            def pick_cert(country: str) -> Optional[str]:
                                for it2 in rds:
                                    if it2.get('iso_3166_1') == country:
                                        for rd in (it2.get('release_dates') or []):
                                            if (rd.get('certification') or '').strip():
                                                return rd.get('certification').strip()
                                return None
                            cert = pick_cert('IT') or pick_cert('US')
                            if cert:
                                row.certification = cert
                        except Exception:
                            pass
                    s.commit()
                _TMDB_JOB["done"] += 1
            # Series
            for it in series:
                if _TMDB_STOP.is_set():
                    _TMDB_JOB["error"] = "Interrotto dall'utente"
                    break
                t, y = _norm_title_year(it.title, it.attrs or {})
                sig = _sig_for('series', t, None)
                mrow = s.get(db.TMDBMap, sig)
                tmdb_id = mrow.tmdb_id if mrow else None
                row = None
                if tmdb_id:
                    row = s.get(db.TMDBSeries, {"tmdb_id": tmdb_id, "language": language})
                need_fetch = False
                if not tmdb_id or not row:
                    need_fetch = True
                elif missing_only:
                    for f in series_fields:
                        if getattr(row, f"{ 'name' if f=='name' else f }", None) in (None, ""):
                            need_fetch = True
                            break
                if need_fetch:
                    params = {"api_key": api_key, "query": t, "language": language}
                    r = client.get("https://api.themoviedb.org/3/search/tv", params=params)
                    data = r.json()
                    res = (data.get("results") or [])
                    if not res:
                        _TMDB_JOB["done"] += 1
                        continue
                    best = res[0]
                    tmdb_id = int(best.get("id"))
                    r2 = client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", params={"api_key": api_key, "language": language, "append_to_response": "videos,images,keywords,release_dates"})
                    det = r2.json()
                    ext = {}
                    creds = {}
                    if any(k in series_fields for k in ("imdb_id",)):
                        ext = client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids", params={"api_key": api_key}).json()
                    if any(k in series_fields for k in ("cast",)):
                        creds = client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/credits", params={"api_key": api_key}).json()
                    if not mrow:
                        s.add(db.TMDBMap(sig=sig, kind='series', tmdb_id=tmdb_id))
                    else:
                        mrow.tmdb_id = tmdb_id
                    row = s.get(db.TMDBSeries, {"tmdb_id": tmdb_id, "language": language})
                    if not row:
                        row = db.TMDBSeries(tmdb_id=tmdb_id, language=language, name=det.get("name") or det.get("original_name") or "")
                        s.add(row)
                    if 'name' in series_fields:
                        row.name = det.get("name") or row.name
                    if 'overview' in series_fields:
                        row.overview = det.get("overview") or row.overview
                    if 'poster' in series_fields:
                        row.poster_path = det.get("poster_path") or row.poster_path
                    if 'backdrop' in series_fields:
                        row.backdrop_path = det.get("backdrop_path") or row.backdrop_path
                    if 'rating' in series_fields:
                        row.rating = det.get("vote_average") or row.rating
                        try:
                            row.rating_votes = int(det.get('vote_count') or 0) or row.rating_votes
                        except Exception:
                            pass
                    if 'year' in series_fields:
                        d = (det.get("first_air_date") or "")
                        try:
                            row.first_year = int(d.split("-")[0]) if d else row.first_year
                        except Exception:
                            pass
                    if 'duration' in series_fields:
                        try:
                            er = det.get('episode_run_time') or []
                            row.episode_run_time_mins = int(er[0]) if er else row.episode_run_time_mins
                        except Exception:
                            pass
                    if 'imdb_id' in series_fields:
                        row.imdb_id = ext.get('imdb_id') or row.imdb_id
                    if 'genres' in series_fields:
                        row.genres = [g.get('name') for g in (det.get('genres') or [])] or row.genres
                    # countries not required for series-level NFO fields — skip
                    if 'cast' in series_fields:
                        cast_list = [c.get('name') for c in (creds.get('cast') or [])][:10]
                        if cast_list:
                            row.cast = ", ".join(cast_list)
                    if 'logo' in series_fields:
                        imgs = (det.get('images') or {})
                        logos = imgs.get('logos') or []
                        if logos:
                            row.logo_path = logos[0].get('file_path') or row.logo_path
                    if 'seasons' in series_fields:
                        try:
                            row.seasons_count = int(det.get('number_of_seasons') or 0) or row.seasons_count
                        except Exception:
                            pass
                    if 'episodes' in series_fields:
                        try:
                            row.episodes_count = int(det.get('number_of_episodes') or 0) or row.episodes_count
                        except Exception:
                            pass
                    # Extended series fields
                    if 'original_name' in series_fields:
                        row.original_name = det.get('original_name') or row.original_name
                    if 'original_language' in series_fields:
                        row.original_language = det.get('original_language') or row.original_language
                    if 'tagline' in series_fields:
                        row.tagline = det.get('tagline') or row.tagline
                    if 'first_air_date' in series_fields:
                        row.first_air_date = det.get('first_air_date') or row.first_air_date
                    if 'last_air_date' in series_fields:
                        row.last_air_date = det.get('last_air_date') or row.last_air_date
                    if 'status' in series_fields:
                        row.status = det.get('status') or row.status
                    if 'in_production' in series_fields:
                        try:
                            row.in_production = int(bool(det.get('in_production')))  # store as 0/1
                        except Exception:
                            pass
                    if 'created_by' in series_fields:
                        row.created_by = [c.get('name') for c in (det.get('created_by') or []) if c.get('name')]
                    if 'networks' in series_fields:
                        row.networks = [n.get('name') for n in (det.get('networks') or []) if n.get('name')]
                    if 'origin_country' in series_fields:
                        row.origin_country = det.get('origin_country') or row.origin_country
                    if 'youtube_trailer' in series_fields:
                        vids = (det.get('videos') or {}).get('results') or []
                        yt = next((v for v in vids if (v.get('site') == 'YouTube' and (v.get('type') or '').lower() == 'trailer' and v.get('key'))), None)
                        row.youtube_trailer = (yt.get('key') if yt else row.youtube_trailer) or row.youtube_trailer
                    if 'images' in series_fields:
                        imgs = det.get('images') or {}
                        row.images = {
                            'posters': [p.get('file_path') for p in (imgs.get('posters') or []) if p.get('file_path')],
                            'backdrops': [b.get('file_path') for b in (imgs.get('backdrops') or []) if b.get('file_path')],
                        }
                    if 'keywords' in series_fields:
                        kw = det.get('keywords') or {}
                        arr = kw.get('results') or kw.get('keywords') or []
                        row.keywords = [k.get('name') for k in arr if k.get('name')]
                    if 'seasons_summary' in series_fields or 'seasons' in series_fields:
                        seasons = []
                        for ss in det.get('seasons') or []:
                            seasons.append({
                                'season_number': ss.get('season_number'),
                                'name': ss.get('name'),
                                'poster_path': ss.get('poster_path'),
                            })
                        if seasons:
                            row.seasons_json = seasons
                    if 'type' in series_fields:
                        row.type = det.get('type') or row.type
                    if 'last_next_episodes' in series_fields or 'last_episode' in series_fields:
                        row.last_episode = det.get('last_episode_to_air') or row.last_episode
                    if 'last_next_episodes' in series_fields or 'next_episode' in series_fields:
                        row.next_episode = det.get('next_episode_to_air') or row.next_episode
                    s.commit()
                _TMDB_JOB["done"] += 1

            # Episodes (episode-level)
            if episode_fields:
                done_eps = set()
                from app.services.xtream import try_extract_tv_triplet
                for it in series:
                    if _TMDB_STOP.is_set():
                        _TMDB_JOB["error"] = "Interrotto dall'utente"
                        break
                    t, _ = _norm_title_year(it.title, it.attrs or {})
                    sig = _sig_for('series', t, None)
                    mrow = s.get(db.TMDBMap, sig)
                    if not mrow:
                        _TMDB_JOB["done"] += 1
                        continue
                    tmdb_id = mrow.tmdb_id
                    trip = try_extract_tv_triplet(it.url)
                    if not trip:
                        _TMDB_JOB["done"] += 1
                        continue
                    _sid, season, episode = trip
                    key = (tmdb_id, season, episode)
                    if key in done_eps:
                        _TMDB_JOB["done"] += 1
                        continue
                    done_eps.add(key)
                    er = client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}", params={"api_key": api_key, "language": language, "append_to_response": "images"}).json()
                    if not er or not er.get('id'):
                        _TMDB_JOB["done"] += 1
                        continue
                    epid = int(er.get('id'))
                    rowe = s.get(db.TMDBEpisode, {"episode_tmdb_id": epid, "language": language})
                    if not rowe:
                        rowe = db.TMDBEpisode(episode_tmdb_id=epid, language=language, tmdb_series_id=tmdb_id, season=int(season), episode=int(episode))
                        s.add(rowe)
                    if 'name' in episode_fields:
                        rowe.name = er.get('name') or rowe.name
                    if 'overview' in episode_fields:
                        rowe.overview = er.get('overview') or rowe.overview
                    if 'air_date' in episode_fields:
                        rowe.air_date = er.get('air_date') or rowe.air_date
                    if 'still' in episode_fields:
                        rowe.still_path = er.get('still_path') or rowe.still_path
                    if 'duration' in episode_fields:
                        try:
                            rowe.duration_mins = int(er.get('runtime') or 0) or rowe.duration_mins
                        except Exception:
                            pass
                    if 'guest_stars' in episode_fields:
                        rowe.guest_stars = [g.get('name') for g in (er.get('guest_stars') or [])]
                    if 'rating' in episode_fields:
                        try:
                            rowe.vote_average = float(er.get('vote_average') or 0) or rowe.vote_average
                        except Exception:
                            pass
                    if 'imdb_id' in episode_fields:
                        try:
                            ext_ep = client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}/external_ids", params={"api_key": api_key}).json()
                            rowe.imdb_id = ext_ep.get('imdb_id') or rowe.imdb_id
                        except Exception:
                            pass
                    if 'production_code' in episode_fields:
                        rowe.production_code = er.get('production_code') or rowe.production_code
                    if 'crew' in episode_fields:
                        rowe.crew = [c.get('name') for c in (er.get('crew') or []) if c.get('name')]
                    if 'vote_average' in episode_fields:
                        try:
                            rowe.vote_average = float(er.get('vote_average') or 0) or rowe.vote_average
                        except Exception:
                            pass
                    s.commit()
                    _TMDB_JOB["done"] += 1
    except Exception as e:
        _TMDB_JOB["error"] = str(e)
    finally:
        _TMDB_JOB["running"] = False


@router.post("/admin/tmdb/refresh")
def tmdb_refresh(payload: Dict[str, bool]):
    if _TMDB_JOB["running"]:
        return {"ok": False, "status": "running"}
    missing_only = bool(payload.get("missing_only"))
    t = threading.Thread(target=_run_tmdb_job, args=(missing_only,), daemon=True)
    t.start()
    return {"ok": True, "status": "started"}


@router.get("/admin/tmdb/status")
def tmdb_status():
    return {"job": _TMDB_JOB}


@router.post("/admin/tmdb/stop")
def tmdb_stop():
    if _TMDB_JOB["running"]:
        _TMDB_STOP.set()
        return {"ok": True, "status": "stopping"}
    return {"ok": False, "status": "idle"}
