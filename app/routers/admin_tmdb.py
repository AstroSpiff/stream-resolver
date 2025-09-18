# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import threading
import zlib
from typing import Any, Dict, List, Optional, Tuple, Sequence, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session

from app import config, db
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# Small helper to guard against DBs with hard VARCHAR limits left from older schemas.
def _limit(text: Optional[str], maxlen: int) -> str:
    try:
        s = str(text or "")
    except Exception:
        s = ""
    return s if len(s) <= maxlen else s[:maxlen]

# --- Globals for Job Management ---
_TMDB_JOB = {
    "running": False,
    "total": 0,
    "done": 0,
    "mode": "",
    "error": "",
    # diagnostics
    "regex_hits": 0,
    "map_hits": 0,
    "search_hits": 0,
    "updated": 0,
    "skipped": 0,
    "last": {},
}
_TMDB_STOP = threading.Event()


# --- Utility Functions ---
def _norm_title_year(title: str, attrs: Dict[str, str]) -> Tuple[str, Optional[int]]:
    """Extracts a clean title and year from a playlist item."""
    t = (title or "").strip()
    # Remove common season/episode markers from titles to improve search
    t = re.sub(r"\bS\d{1,2}\s*E\d{1,2}\b", "", t, flags=re.I).strip()  # S01E01 or S01 E01
    t = re.sub(r"\b\d{1,2}x\d{1,2}\b", "", t, flags=re.I).strip()       # 1x01
    t = re.sub(r"\bStagione\s*\d+\b", "", t, flags=re.I).strip()         # Stagione 1
    t = re.sub(r"\bSeason\s*\d+\b", "", t, flags=re.I).strip()           # Season 1
    
    year = None
    m = re.search(r"\b(19|20)\d{2}\b", t)
    if m:
        year = int(m.group(0))
    else:
        for k in ("tvg-year", "tvg_year", "year"):
            v = (attrs.get(k) or "").strip()
            m2 = re.search(r"\b(19|20)\d{2}\b", v)
            if m2:
                year = int(m2.group(0))
                break
    
    t = re.sub(r"\s*\([^()]*\d{4}[^()]*\)", " ", t).strip() # Remove year in parenthesis
    t = re.sub(r"\s+", " ", t)
    return t, year


def _sig_for(kind: str, title: str, year: Optional[int]) -> str:
    """Generates a stable signature for a media item."""
    base = f"{kind}:{(title or '').lower()}:{year or 0}"
    return f"s{zlib.crc32(base.encode('utf-8')):08x}"


def _tmdb_image_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    """Build a full TMDB image URL from a file path.

    Accepts TMDB file paths like "/abc123.jpg" and returns a URL using the
    configured size (default "w500"). If the input is empty, returns None.
    If the input already looks like an absolute URL, it is returned as-is.
    """
    if not path:
        return None
    try:
        p = str(path).strip()
    except Exception:
        return None
    if not p:
        return None
    if p.startswith("http://") or p.startswith("https://"):
        return p
    base = f"https://image.tmdb.org/t/p/{size}"
    if p.startswith("/"):
        return base + p
    return f"{base}/{p}"


# --- Core TMDB Processing Logic ---

def _get_tmdb_id_from_url(url: str, rules: Sequence[db.TMDBRegexRule]) -> Optional[Tuple[int, str]]:
    """Tries to extract a TMDB ID from a URL using configured regex rules."""
    if not url:
        return None
    for rule in rules:
        try:
            if re.search(rule.domain_regex, url, re.I):
                match = re.search(rule.extraction_regex, url)
                if match and match.groups():
                    tmdb_id_str = match.group(1)
                    return int(tmdb_id_str), rule.media_type
        except re.error:
            continue
    return None

def _get_or_create_map(session: Session, sig: str, kind: str, tmdb_id: int) -> db.TMDBMap:
    """Get or create a TMDBMap entry."""
    m = session.get(db.TMDBMap, sig)
    if not m:
        m = db.TMDBMap(sig=sig, kind=kind, tmdb_id=tmdb_id)
        session.add(m)
    else:
        m.tmdb_id = tmdb_id
    return m


def _search_tmdb(client: httpx.Client, api_key: str, lang: str, query: str, year: Optional[int], kind: str) -> Optional[int]:
    """Searches TMDB and returns the best matching ID."""
    params = {"api_key": api_key, "query": query, "language": lang}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = str(year)

    # TMDB uses 'tv' for series searches
    endpoint_kind = "tv" if kind == "series" else kind
    r = client.get(f"https://api.themoviedb.org/3/search/{endpoint_kind}", params=params)
    r.raise_for_status()
    data = r.json()
    results = data.get("results")
    return int(results[0]["id"]) if results else None


def _pick_youtube_trailer(videos: dict) -> Optional[str]:
    try:
        for v in (videos or {}).get("results", []) or []:
            if (v.get("site") == "YouTube") and (v.get("type") in ("Trailer", "Teaser")):
                return v.get("key")
    except Exception:
        pass
    return None


def _pick_logo_path(images: dict, lang: str) -> Optional[str]:
    try:
        logos = (images or {}).get("logos") or []
        # prefer matching language, then any
        for pref in (lang.split("-")[0], None):
            for it in logos:
                if pref is None or (it.get("iso_639_1") == pref):
                    if it.get("file_path"):
                        return it.get("file_path")
    except Exception:
        pass
    return None


def _pick_backdrop_path(images: dict, lang: str) -> Optional[str]:
    try:
        backs = (images or {}).get("backdrops") or []
        pref_lang = (lang.split("-")[0] if lang else None)
        # prefer matching language, then any with file_path
        for it in backs:
            if pref_lang and it.get("iso_639_1") == pref_lang and it.get("file_path"):
                return it.get("file_path")
        for it in backs:
            if it.get("file_path"):
                return it.get("file_path")
    except Exception:
        pass
    return None


def _pick_poster_path(images: dict, lang: str) -> Optional[str]:
    try:
        posters = (images or {}).get("posters") or []
        pref_lang = (lang.split("-")[0] if lang else None)
        # prefer matching language, then EN, then any
        for it in posters:
            if pref_lang and it.get("iso_639_1") == pref_lang and it.get("file_path"):
                return it.get("file_path")
        for it in posters:
            if it.get("iso_639_1") == "en" and it.get("file_path"):
                return it.get("file_path")
        for it in posters:
            if it.get("file_path"):
                return it.get("file_path")
    except Exception:
        pass
    return None

def _pick_certification(release_dates: dict, country_preference: list[str] = ["IT", "US"]) -> Optional[str]:
    try:
        results = (release_dates or {}).get("results") or []
        for cc in country_preference:
            for r in results:
                if (r.get("iso_3166_1") == cc):
                    for rel in (r.get("release_dates") or []):
                        cert = (rel or {}).get("certification")
                        if cert:
                            return cert
    except Exception:
        pass
    return None


def _update_movie_details(session: Session, client: httpx.Client, api_key: str, lang: str, tmdb_id: int):
    """Fetches and updates a single movie's details in the database."""
    r = client.get(
        f"https://api.themoviedb.org/3/movie/{tmdb_id}",
        params={
            "api_key": api_key,
            "language": lang,
            "append_to_response": "credits,external_ids,videos,images,release_dates",
            # accept configured language, then English, then no language
            "include_image_language": f"{(lang or 'en').split('-')[0]},en,null",
            # ensure trailers in EN if local language missing
            "include_video_language": f"{(lang or 'en').split('-')[0]},en,null",
        }
    )
    if r.status_code != 200:
        return

    det = r.json()
    row = session.get(db.TMDBMovie, {"tmdb_id": tmdb_id, "language": lang})
    if not row:
        row = db.TMDBMovie(tmdb_id=tmdb_id, language=lang)
        session.add(row)

    row.title = det.get("title") or det.get("name")
    row.overview = _limit(det.get("overview"), 4000)
    row.poster_path = det.get("poster_path")
    row.backdrop_path = det.get("backdrop_path")
    row.rating = det.get("vote_average")
    row.runtime_mins = det.get("runtime")
    row.imdb_id = (det.get("external_ids") or {}).get("imdb_id")
    try:
        row.genres = ", ".join([g.get("name") for g in (det.get("genres") or []) if g.get("name")])
    except Exception:
        row.genres = None
    row.original_title = det.get("original_title")
    row.tagline = det.get("tagline")
    row.release_date = det.get("release_date")
    # Collections: upsert collection and association in join table
    try:
        coll = det.get("belongs_to_collection")
        if coll and isinstance(coll, dict) and coll.get("id") is not None:
            raw_id = coll.get("id")
            cid: Optional[int] = None
            if isinstance(raw_id, int):
                cid = raw_id
            elif isinstance(raw_id, str):
                try:
                    cid = int(raw_id)
                except ValueError:
                    cid = None
            if cid is None:
                return
            crow = session.get(db.TMDBCollection, cid)
            if not crow:
                crow = db.TMDBCollection(id=cid)
                session.add(crow)
            crow.name = coll.get("name") or crow.name or ""
            # If collection has no poster/backdrop in shallow object, fetch images and pick best
            cpost = coll.get("poster_path")
            cback = coll.get("backdrop_path")
            if not (cpost and cback):
                try:
                    ir = client.get(
                        f"https://api.themoviedb.org/3/collection/{cid}/images",
                        params={"api_key": api_key, "include_image_language": f"{(lang or 'en').split('-')[0]},en,null"}
                    )
                    if ir.status_code == 200:
                        ij = ir.json()
                        cpost = cpost or _pick_poster_path(ij or {}, lang)
                        cback = cback or _pick_backdrop_path(ij or {}, lang)
                except Exception:
                    pass
            crow.poster_path = cpost or crow.poster_path
            crow.backdrop_path = cback or crow.backdrop_path
            # association
            try:
                exists = session.get(db.TMDBCollectionMovie, {"collection_id": cid, "movie_tmdb_id": tmdb_id})
            except Exception:
                exists = None
            if not exists:
                session.add(db.TMDBCollectionMovie(collection_id=cid, movie_tmdb_id=tmdb_id))
    except Exception:
        pass
    row.youtube_trailer = _pick_youtube_trailer(det.get("videos") or {})
    # Fallback: fetch videos without language filter if still missing
    if not row.youtube_trailer:
        try:
            vr = client.get(
                f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos",
                params={"api_key": api_key}
            )
            if vr.status_code == 200:
                vd = vr.json() or {}
                for v in (vd.get("results") or []):
                    if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser") and v.get("key"):
                        row.youtube_trailer = v.get("key")
                        break
        except Exception:
            pass
    row.logo_path = _pick_logo_path(det.get("images") or {}, lang)
    # Fallbacks for poster/backdrop via images lists if primary fields are missing
    if not (row.poster_path or "").strip():
        try:
            row.poster_path = _pick_poster_path(det.get("images") or {}, lang) or row.poster_path
        except Exception:
            pass
    if not (row.backdrop_path or "").strip():
        try:
            row.backdrop_path = _pick_backdrop_path(det.get("images") or {}, lang) or row.backdrop_path
        except Exception:
            pass
    # Normalize to CSV strings
    try:
        pcs = [c.get("name") for c in (det.get("production_companies") or []) if c.get("name")]
        row.production_companies = ", ".join(pcs) if pcs else None
    except Exception:
        row.production_companies = None
    try:
        pcn = []
        for c in (det.get("production_countries") or []):
            if isinstance(c, dict):
                nm = c.get("name") or c.get("iso_3166_1")
                if nm:
                    pcn.append(nm)
        row.production_countries = ", ".join(pcn) if pcn else None
    except Exception:
        row.production_countries = None
    
    credits = det.get("credits", {})
    row.cast = ", ".join([c.get("name") for c in (credits.get("cast") or [])[:10]])
    row.director = ", ".join([c.get("name") for c in (credits.get("crew") or []) if c.get("job") == "Director"])
    # Writers (CSV)
    try:
        writers = [c.get("name") for c in (credits.get("crew") or []) if c.get("job") in ("Writer", "Screenplay", "Author") and c.get("name")]
        row.writers = ", ".join(writers) if writers else None
    except Exception:
        row.writers = None
    # Certification (country preference IT -> US)
    row.certification = _pick_certification(det.get("release_dates") or {})
    
    if det.get("release_date"):
        try:
            row.release_year = int(det["release_date"].split("-")[0])
        except (ValueError, IndexError):
            pass
    session.commit()


def _update_series_details(session: Session, client: httpx.Client, api_key: str, lang: str, tmdb_id: int):
    """Fetches and updates a single series' details in the database."""
    r = client.get(
        f"https://api.themoviedb.org/3/tv/{tmdb_id}",
        params={
            "api_key": api_key,
            "language": lang,
            "append_to_response": "credits,external_ids,videos,images",
            # accept configured language, then English, then no language
            "include_image_language": f"{(lang or 'en').split('-')[0]},en,null",
            # ensure trailers in EN if local language missing
            "include_video_language": f"{(lang or 'en').split('-')[0]},en,null",
        }
    )
    if r.status_code != 200:
        return

    det = r.json()
    row = session.get(db.TMDBSeries, {"tmdb_id": tmdb_id, "language": lang})
    if not row:
        row = db.TMDBSeries(tmdb_id=tmdb_id, language=lang)
        session.add(row)

    row.name = det.get("name") or det.get("original_name")
    row.overview = _limit(det.get("overview"), 4000)
    row.poster_path = det.get("poster_path")
    row.backdrop_path = det.get("backdrop_path")
    row.rating = det.get("vote_average")
    row.imdb_id = (det.get("external_ids") or {}).get("imdb_id")
    try:
        row.genres = ", ".join([g.get("name") for g in (det.get("genres") or []) if g.get("name")])
    except Exception:
        row.genres = None
    row.original_name = det.get("original_name")
    row.tagline = det.get("tagline")
    row.first_air_date = det.get("first_air_date")
    row.status = det.get("status")
    # Normalize arrays to CSV strings where appropriate
    try:
        cb = [p.get("name") for p in (det.get("created_by") or []) if p.get("name")]
        row.created_by = ", ".join(cb[:5]) if cb else None
    except Exception:
        row.created_by = None
    try:
        nets = [n.get("name") for n in (det.get("networks") or []) if n.get("name")]
        row.networks = ", ".join(nets) if nets else None
    except Exception:
        row.networks = None
    try:
        oc = [c for c in (det.get("origin_country") or []) if c]
        row.origin_country = ", ".join(oc) if oc else None
    except Exception:
        row.origin_country = None
    row.youtube_trailer = _pick_youtube_trailer(det.get("videos") or {})
    # Fallback: fetch videos without language filter if still missing
    if not row.youtube_trailer:
        try:
            vr = client.get(
                f"https://api.themoviedb.org/3/tv/{tmdb_id}/videos",
                params={"api_key": api_key}
            )
            if vr.status_code == 200:
                vd = vr.json() or {}
                for v in (vd.get("results") or []):
                    if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser") and v.get("key"):
                        row.youtube_trailer = v.get("key")
                        break
        except Exception:
            pass
    row.logo_path = _pick_logo_path(det.get("images") or {}, lang)
    # Fallbacks for poster/backdrop via images lists if primary fields are missing
    if not (row.poster_path or "").strip():
        try:
            row.poster_path = _pick_poster_path(det.get("images") or {}, lang) or row.poster_path
        except Exception:
            pass
    if not (row.backdrop_path or "").strip():
        try:
            row.backdrop_path = _pick_backdrop_path(det.get("images") or {}, lang) or row.backdrop_path
        except Exception:
            pass
    # seasons_json deprecated: seasons are stored in tmdb_seasons
    
    credits = det.get("credits", {})
    row.cast = ", ".join([c["name"] for c in credits.get("cast", [])[:10]])
    
    if det.get("first_air_date"):
        try:
            row.first_year = int(det["first_air_date"].split("-")[0])
        except (ValueError, IndexError):
            pass
    
    run_times = det.get("episode_run_time")
    if run_times:
        row.episode_run_time_mins = run_times[0]
    session.commit()
    # also fetch seasons/episodes details to populate TMDBEpisode table
    try:
        seasons = (det.get("seasons") or [])
        # Prepare backdrop fallbacks
        series_bd = det.get("backdrop_path")
        season_bd_map: dict[int, Optional[str]] = {}
        for s in seasons:
            sn = s.get("season_number")
            if sn is None:
                continue
            sr = client.get(
                f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{sn}",
                params={
                    "api_key": api_key,
                    "language": lang,
                    "append_to_response": "images",
                    "include_image_language": f"{(lang or 'en').split('-')[0]},en,null",
                }
            )
            if sr.status_code != 200:
                # Still ensure a fallback later
                season_bd_map[sn] = season_bd_map.get(sn) or series_bd
                continue
            sdet = sr.json()
            # Pick season backdrop if available, else fallback to series backdrop
            try:
                season_bd = _pick_backdrop_path(sdet.get("images") or {}, lang) or series_bd
                season_bd_map[sn] = season_bd
            except Exception:
                season_bd_map[sn] = series_bd
            # Upsert season row in DB
            try:
                sid = s.get("id") or sdet.get("id")
                if sid is not None:
                    row_season = session.get(db.TMDBSeason, {"season_tmdb_id": sid, "language": lang})
                    if not row_season:
                        row_season = db.TMDBSeason(season_tmdb_id=int(sid), language=lang)
                        session.add(row_season)
                    row_season.tmdb_series_id = tmdb_id
                    row_season.season_number = int(sn)
                    row_season.name = s.get("name") or sdet.get("name") or ""
                    row_season.overview = _limit(s.get("overview") or sdet.get("overview") or "", 4000)
                    row_season.air_date = s.get("air_date") or sdet.get("air_date")
                    row_season.episode_count = (s.get("episode_count") or (len(sdet.get("episodes") or []) if isinstance(sdet.get("episodes"), list) else None))
                    row_season.poster_path = s.get("poster_path") or sdet.get("poster_path") or (_pick_poster_path(sdet.get("images") or {}, lang) or "")
                    row_season.backdrop_path = season_bd
                    session.commit()
            except Exception:
                pass
            for ep in (sdet.get("episodes") or []):
                ep_id = ep.get("id")
                if ep_id is None:
                    continue
                row_ep = session.get(db.TMDBEpisode, {"episode_tmdb_id": ep_id, "language": lang})
                if not row_ep:
                    row_ep = db.TMDBEpisode(episode_tmdb_id=ep_id, language=lang)
                    session.add(row_ep)
                row_ep.tmdb_series_id = tmdb_id
                row_ep.season = ep.get("season_number") or sn
                row_ep.episode = ep.get("episode_number") or 0
                row_ep.name = ep.get("name") or ""
                row_ep.overview = _limit(ep.get("overview") or "", 4000)
                row_ep.air_date = ep.get("air_date")
                row_ep.still_path = ep.get("still_path") or ""
                row_ep.duration_mins = ep.get("runtime")
                row_ep.vote_average = ep.get("vote_average")
                # Normalize guest stars and crew to comma-separated names (max 10)
                try:
                    gs_list = []
                    for p in (ep.get("guest_stars") or []):
                        if isinstance(p, dict):
                            n = p.get("name")
                            if isinstance(n, str) and n:
                                gs_list.append(n)
                    if gs_list:
                        row_ep.guest_stars = ", ".join(gs_list[:10])
                except Exception:
                    pass
                try:
                    cw_list = []
                    for p in (ep.get("crew") or []):
                        if isinstance(p, dict):
                            n = p.get("name")
                            if isinstance(n, str) and n:
                                cw_list.append(n)
                    if cw_list:
                        row_ep.crew = ", ".join(cw_list[:10])
                except Exception:
                    pass
                # fetch imdb_id via external_ids (extra call per episode)
                if not row_ep.imdb_id:
                    try:
                        er = client.get(
                            f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{row_ep.season}/episode/{row_ep.episode}",
                            params={"api_key": api_key, "language": lang, "append_to_response": "external_ids"}
                        )
                        if er.status_code == 200:
                            ej = er.json()
                            row_ep.imdb_id = (ej.get("external_ids") or {}).get("imdb_id")
                    except Exception:
                        pass
                session.commit()
        # seasons_json deprecated: no merge; seasons data live in tmdb_seasons
    except Exception:
        # keep series update even if episodes fail
        pass


def _run_tmdb_job(missing_only: bool, media_type: str = 'all'):
    """The main background task for fetching TMDB data."""
    global _TMDB_JOB, _TMDB_STOP
    _TMDB_JOB.update({
        "running": True,
        "done": 0,
        "error": "",
        "mode": f"{media_type}_{'missing' if missing_only else 'full'}",
        "regex_hits": 0,
        "map_hits": 0,
        "search_hits": 0,
        "updated": 0,
        "skipped": 0,
        "last": {},
    })
    _TMDB_STOP.clear()

    try:
        settings = config.load_settings()
        tmdb_cfg = settings.get("tmdb", {})
        api_key = tmdb_cfg.get("api_key", "").strip()
        lang = tmdb_cfg.get("language", "it-IT").strip()

        if not api_key:
            raise RuntimeError("TMDB API key not configured")

        with db.SessionLocal() as session, httpx.Client(timeout=20.0) as client:
            rules = session.execute(select(db.TMDBRegexRule).order_by(db.TMDBRegexRule.priority)).scalars().all()
            
            items_to_process = []
            if media_type in ('all', 'movie'):
                items_to_process.extend(session.execute(select(db.PlaylistItem).where(db.PlaylistItem.kind == 'movie')).scalars().all())
            if media_type in ('all', 'series', 'tv'):
                items_to_process.extend(session.execute(select(db.PlaylistItem).where(db.PlaylistItem.kind == 'series')).scalars().all())
            
            _TMDB_JOB["total"] = len(items_to_process)

            for item in items_to_process:
                if _TMDB_STOP.is_set():
                    _TMDB_JOB["error"] = "User interrupted"
                    break
                
                try:
                    tmdb_id = None
                    kind = item.kind
                    source = None  # regex | map | search

                    # 1. Try to get TMDB ID from URL regex
                    id_from_url, type_from_rule = _get_tmdb_id_from_url(item.original_url, rules) or (None, None)
                    if id_from_url:
                        tmdb_id = id_from_url
                        kind = type_from_rule or item.kind
                        source = "regex"
                        # Also create/update mapping by normalized title/year for future lookups
                        try:
                            title2, year2 = _norm_title_year(item.title, item.attrs or {})
                            if title2:
                                sig2 = _sig_for(kind, title2, year2)
                                _get_or_create_map(session, sig2, kind, tmdb_id)
                        except Exception:
                            pass
                    
                    # 2. Fallback to title/year search
                    else:
                        title, year = _norm_title_year(item.title, item.attrs or {})
                        if not title:
                            continue
                        sig = _sig_for(item.kind, title, year)
                        tmdb_map = session.get(db.TMDBMap, sig)
                        if tmdb_map:
                            tmdb_id = tmdb_map.tmdb_id
                            source = "map"
                        else:
                            tmdb_id = _search_tmdb(client, api_key, lang, title, year, item.kind)
                            if tmdb_id:
                                _get_or_create_map(session, sig, item.kind, tmdb_id)
                                source = "search"

                    # 3. Fetch and update if we have an ID
                    if tmdb_id:
                        is_movie = (kind == 'movie')
                        model = db.TMDBMovie if is_movie else db.TMDBSeries
                        data_row = session.get(model, {"tmdb_id": tmdb_id, "language": lang})
                        
                        needs_fetch = True
                        if missing_only and data_row:
                            needs_fetch = False
                        # If existing but missing extended fields, force fetch
                        if data_row:
                            if is_movie:
                                mrow = cast(db.TMDBMovie, data_row)
                                if any([
                                    mrow.original_title is None,
                                    mrow.tagline is None,
                                    mrow.release_date is None,
                                    mrow.logo_path is None,
                                    mrow.youtube_trailer is None,
                                    mrow.production_companies is None,
                                    mrow.production_countries is None,
                                    mrow.writers is None,
                                    mrow.certification is None,
                                ]):
                                    needs_fetch = True
                            else:
                                srow = cast(db.TMDBSeries, data_row)
                                if any([
                                    srow.original_name is None,
                                    srow.tagline is None,
                                    srow.first_air_date is None,
                                    srow.status is None,
                                    srow.created_by is None,
                                    srow.networks is None,
                                    srow.origin_country is None,
                                    srow.youtube_trailer is None,
                                    srow.logo_path is None,
                                    srow.episode_run_time_mins is None,
                                ]):
                                    needs_fetch = True
                        
                        # If series data exists but no episodes yet, still fetch to populate episodes
                        ensure_episodes = False
                        if (not needs_fetch) and (not is_movie):
                            try:
                                from sqlalchemy import func
                                eps_count = session.query(func.count(db.TMDBEpisode.episode_tmdb_id)).filter(
                                    db.TMDBEpisode.tmdb_series_id == tmdb_id,
                                    db.TMDBEpisode.language == lang,
                                ).scalar() or 0
                                if eps_count == 0:
                                    ensure_episodes = True
                            except Exception:
                                pass

                        if needs_fetch or ensure_episodes:
                            if is_movie:
                                _update_movie_details(session, client, api_key, lang, tmdb_id)
                            else:
                                _update_series_details(session, client, api_key, lang, tmdb_id)
                            _TMDB_JOB["updated"] += 1
                        else:
                            _TMDB_JOB["skipped"] += 1

                    # update source counters and last item diagnostics
                    if source == "regex":
                        _TMDB_JOB["regex_hits"] += 1
                    elif source == "map":
                        _TMDB_JOB["map_hits"] += 1
                    elif source == "search":
                        _TMDB_JOB["search_hits"] += 1

                    _TMDB_JOB["last"] = {
                        "playlist_item_id": item.id,
                        "title": item.title,
                        "kind": kind,
                        "source": source,
                        "tmdb_id": tmdb_id,
                    }
                
                finally:
                    _TMDB_JOB["done"] += 1
                    session.commit()

    except Exception as e:
        _TMDB_JOB["error"] = str(e)
    finally:
        _TMDB_JOB["running"] = False


# --- API Endpoints for TMDB Regex Rules ---

class TMDBRuleIn(BaseModel):
    name: Optional[str] = "Rule"
    priority: Optional[int] = 100
    domain_regex: str
    extraction_regex: str
    media_type: Optional[str] = "movie"  # movie|series

class TMDBRuleTestIn(BaseModel):
    url: str


@router.get("/admin/tmdb/rules")
def get_tmdb_rules(session: Session = Depends(db.get_db)):
    rules = session.execute(select(db.TMDBRegexRule).order_by(db.TMDBRegexRule.priority)).scalars().all()
    return [
        {
            "id": rule.id,
            "name": rule.name,
            "priority": rule.priority,
            "domain_regex": rule.domain_regex,
            "extraction_regex": rule.extraction_regex,
            "media_type": rule.media_type,
        }
        for rule in rules
    ]

@router.post("/admin/tmdb/rules")
def create_tmdb_rule(data: TMDBRuleIn = Body(...), session: Session = Depends(db.get_db)):
    print("--- EXECUTING create_tmdb_rule ---")
    print(f"--- RECEIVED DATA: {data.dict()} ---")
    try:
        new_rule = db.TMDBRegexRule(
            name=(data.name or "Rule"),
            priority=int(data.priority or 100),
            domain_regex=data.domain_regex,
            extraction_regex=data.extraction_regex,
            media_type=(data.media_type or "movie"),
        )
        session.add(new_rule)
        session.commit()
        return {"ok": True, "id": new_rule.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/admin/tmdb/rules/{rule_id}")
def delete_tmdb_rule(rule_id: int, session: Session = Depends(db.get_db)):
    rule = session.get(db.TMDBRegexRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(rule)
    session.commit()
    return {"ok": True}


@router.post("/admin/tmdb/rules/test")
def test_tmdb_rule(data: TMDBRuleTestIn = Body(...), session: Session = Depends(db.get_db)):
    """Tests the current TMDB regex rules against a provided URL.
    Returns the extracted TMDB ID, media_type, and matched rule if any.
    """
    url = (data.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    rules = session.execute(select(db.TMDBRegexRule).order_by(db.TMDBRegexRule.priority)).scalars().all()
    out = {
        "url": url,
        "matched": False,
        "tmdb_id": None,
        "media_type": None,
        "rule": None,
    }
    for rule in rules:
        try:
            if re.search(rule.domain_regex, url, re.I):
                m = re.search(rule.extraction_regex, url)
                if m and m.groups():
                    out["matched"] = True
                    try:
                        out["tmdb_id"] = int(m.group(1))
                    except Exception:
                        out["tmdb_id"] = None
                    out["media_type"] = rule.media_type
                    out["rule"] = {
                        "id": rule.id, "name": rule.name, "priority": rule.priority,
                        "domain_regex": rule.domain_regex, "extraction_regex": rule.extraction_regex,
                    }
                    break
        except re.error:
            continue
    return out


# --- API Endpoints for Job Management ---

@router.post("/admin/tmdb/refresh")
def tmdb_refresh(payload: Dict[str, Any]):
    """Starts a TMDB metadata refresh job."""
    if _TMDB_JOB.get("running"):
        raise HTTPException(status_code=409, detail="A TMDB job is already running.")
    
    mode = payload.get("mode") or "full"
    missing_only = bool(payload.get("missing_only"))
    media_type = payload.get("media_type", 'all')

    target = _run_tmdb_job
    args = (missing_only, media_type)
    if mode == 'incremental':
        target = _run_tmdb_incremental
        args = ()
    
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    
    return {"ok": True, "status": "started"}


@router.get("/admin/tmdb/status")
def tmdb_status():
    """Returns the status of the current TMDB job."""
    return {"job": _TMDB_JOB}


def _run_tmdb_incremental():
    global _TMDB_JOB, _TMDB_STOP
    _TMDB_JOB.update({"running": True, "done": 0, "error": "", "mode": "incremental", "total": 0})
    _TMDB_STOP.clear()
    try:
        settings = config.load_settings()
        tmdb_cfg = settings.get("tmdb", {})
        api_key = (tmdb_cfg.get("api_key") or "").strip()
        lang = (tmdb_cfg.get("language") or "it-IT").strip()
        if not api_key:
            raise RuntimeError("TMDB API key not configured")
        with db.SessionLocal() as session, httpx.Client(timeout=20.0) as client:
            # collect pending ingest items
            pending = session.execute(select(db.TMDBIngestStatus).where(db.TMDBIngestStatus.status=="pending")).scalars().all()
            movies = [x for x in pending if (x.key_type=="movie" and x.movie_sig)]
            series = [x for x in pending if (x.key_type=="series" and x.series_sig)]
            episodes = [x for x in pending if (x.key_type=="episode" and x.series_sig and x.season is not None and x.episode is not None)]
            _TMDB_JOB["total"] = len(movies) + len(series) + len(episodes)

            # helper to resolve id via map or search
            def resolve(kind: str, title_norm: str, year: Optional[int]):
                sig = _sig_for(kind, title_norm, year)
                m = session.get(db.TMDBMap, sig)
                if m:
                    return m.tmdb_id
                tmdb_id = _search_tmdb(client, api_key, lang, title_norm, year, kind)
                if tmdb_id:
                    _get_or_create_map(session, sig, kind, tmdb_id)
                return tmdb_id

            # movies
            for it in movies:
                if _TMDB_STOP.is_set():
                    _TMDB_JOB["error"] = "User interrupted"
                    break
                try:
                    tmdb_id = it.tmdb_id or resolve('movie', it.title_norm or '', it.year)
                    if tmdb_id:
                        _update_movie_details(session, client, api_key, lang, tmdb_id)
                        it.tmdb_id = tmdb_id
                        it.status = 'done'
                        it.last_processed_ts = config.now_ts()
                except Exception as e:
                    it.status = 'error'; it.last_error = str(e); it.retries = int(it.retries or 0) + 1
                finally:
                    _TMDB_JOB["done"] += 1
                    session.commit()

            # series
            for it in series:
                if _TMDB_STOP.is_set():
                    _TMDB_JOB["error"] = "User interrupted"
                    break
                try:
                    tmdb_id = it.tmdb_id or resolve('series', it.title_norm or '', it.year)
                    if tmdb_id:
                        _update_series_details(session, client, api_key, lang, tmdb_id)
                        it.tmdb_id = tmdb_id
                        it.status = 'done'
                        it.last_processed_ts = config.now_ts()
                except Exception as e:
                    it.status = 'error'; it.last_error = str(e); it.retries = int(it.retries or 0) + 1
                finally:
                    _TMDB_JOB["done"] += 1
                    session.commit()

            # episodes: group by series_sig+season, process season once
            from collections import defaultdict
            groups: dict[tuple[str,int], list[db.TMDBIngestStatus]] = defaultdict(list)
            for it in episodes:
                from typing import cast
                sig = cast(str, it.series_sig)
                sn = cast(int, it.season)
                groups[(sig, sn)].append(it)

            for (series_sig, season_num), group in groups.items():
                if _TMDB_STOP.is_set():
                    _TMDB_JOB["error"] = "User interrupted"
                    break
                try:
                    # resolve series tmdb id using any group's title_norm
                    title_norm = group[0].title_norm or ''
                    tmdb_id = group[0].tmdb_id or resolve('series', title_norm, None)
                    if tmdb_id:
                        # fetch only this season
                        sr = client.get(
                            f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}",
                            params={"api_key": api_key, "language": lang, "append_to_response": "images", "include_image_language": f"{(lang or 'en').split('-')[0]},en,null"}
                        )
                        if sr.status_code == 200:
                            sdet = sr.json()
                            # upsert season row
                            sid = sdet.get('id')
                            row_season = session.get(db.TMDBSeason, {"season_tmdb_id": sid, "language": lang}) if sid else None
                            if sid and not row_season:
                                row_season = db.TMDBSeason(season_tmdb_id=int(sid), language=lang)
                                session.add(row_season)
                            if row_season:
                                row_season.tmdb_series_id = tmdb_id
                                row_season.season_number = season_num
                                row_season.name = sdet.get('name') or row_season.name or ''
                                row_season.overview = _limit(sdet.get('overview') or row_season.overview or '', 4000)
                                row_season.air_date = sdet.get('air_date') or row_season.air_date
                                row_season.episode_count = (len(sdet.get('episodes') or []))
                                row_season.poster_path = sdet.get('poster_path') or ( _pick_poster_path(sdet.get('images') or {}, lang) or row_season.poster_path or '' )
                                row_season.backdrop_path = _pick_backdrop_path(sdet.get('images') or {}, lang) or row_season.backdrop_path
                            # upsert episodes in season
                            for ep in (sdet.get('episodes') or []):
                                if _TMDB_STOP.is_set():
                                    break
                                ep_id = ep.get('id')
                                if ep_id is None:
                                    continue
                                row_ep = session.get(db.TMDBEpisode, {"episode_tmdb_id": ep_id, "language": lang})
                                if not row_ep:
                                    row_ep = db.TMDBEpisode(episode_tmdb_id=ep_id, language=lang)
                                    session.add(row_ep)
                                row_ep.tmdb_series_id = tmdb_id
                                row_ep.season = ep.get('season_number') or season_num
                                row_ep.episode = ep.get('episode_number') or 0
                                row_ep.name = ep.get('name') or ''
                                row_ep.overview = _limit(ep.get('overview') or '', 4000)
                                row_ep.air_date = ep.get('air_date')
                                row_ep.still_path = ep.get('still_path') or ''
                                row_ep.duration_mins = ep.get('runtime')
                                row_ep.vote_average = ep.get('vote_average')
                            # mark all group as done
                            for it2 in group:
                                it2.tmdb_id = tmdb_id
                                it2.status = 'done'
                                it2.last_processed_ts = config.now_ts()
                except Exception as e:
                    for it2 in group:
                        it2.status = 'error'; it2.last_error = str(e); it2.retries = int(it2.retries or 0) + 1
                finally:
                    _TMDB_JOB["done"] += len(group)
                    session.commit()
    except Exception as e:
        _TMDB_JOB["error"] = str(e)
    finally:
        _TMDB_JOB["running"] = False


@router.post("/admin/tmdb/stop")
def tmdb_stop():
    """Stops a running TMDB job."""
    if _TMDB_JOB.get("running"):
        _TMDB_STOP.set()
        return {"ok": True, "status": "stopping"}
    return {"ok": False, "status": "idle"}


@router.post("/admin/tmdb/clear")
def tmdb_clear(payload: Optional[Dict[str, Any]] = Body(None)):
    """Deletes all TMDB cached data (map, movies, series, episodes).

    Accepts optional payload { what: ["map","movies","series","episodes"] }.
    Default is to clear all.
    """
    logger.info("TMDB clear requested payload=%s", payload)
    # By default clear everything, including dependent tables (collections, seasons)
    what = set(((payload or {}).get("what") or ["map","movies","series","episodes","seasons","collections"]))
    valid = {"map","movies","series","episodes","seasons","collections"}
    unknown = what - valid
    if unknown:
        raise HTTPException(400, f"unknown sections: {', '.join(sorted(unknown))}")
    # Safety: disallow while a job is running
    if _TMDB_JOB.get("running"):
        raise HTTPException(409, "Cannot clear while a TMDB job is running")

    out = {"deleted": {}, "reset": {}, "remaining": {}}
    with db.SessionLocal() as s:
        # Delete in dependency order:
        # episodes -> seasons -> series -> movies(+collections) -> map(partial or full)
        if "episodes" in what or "series" in what:
            try:
                res = s.execute(delete(db.TMDBEpisode))
                out["deleted"]["episodes"] = (out["deleted"].get("episodes", 0) or 0) + int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["episodes_error"] = str(e)

        # Delete seasons when explicitly requested or as part of clearing series
        if "seasons" in what or "series" in what:
            try:
                res = s.execute(delete(db.TMDBSeason))
                out["deleted"]["seasons"] = int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["seasons_error"] = str(e)

        if "series" in what:
            try:
                res = s.execute(delete(db.TMDBSeries))
                out["deleted"]["series"] = int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["series_error"] = str(e)
        if "movies" in what:
            try:
                res = s.execute(delete(db.TMDBMovie))
                out["deleted"]["movies"] = int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["movies_error"] = str(e)
            # Also clear collection associations and collections when clearing movies
            try:
                res = s.execute(delete(db.TMDBCollectionMovie))
                out["deleted"]["collection_movies"] = int(getattr(res, "rowcount", 0) or 0)
                res2 = s.execute(delete(db.TMDBCollection))
                out["deleted"]["collections"] = int(getattr(res2, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["collections_error"] = str(e)
        if "map" in what:
            try:
                res = s.execute(delete(db.TMDBMap))
                out["deleted"]["map"] = int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["map_error"] = str(e)
        else:
            # If maps are not fully cleared, remove those associated to cleared kinds
            try:
                from sqlalchemy import and_
                if "movies" in what:
                    res = s.execute(delete(db.TMDBMap).where(db.TMDBMap.kind == 'movie'))
                    out["deleted"]["map_movies"] = int(getattr(res, "rowcount", 0) or 0)
                if "series" in what:
                    res = s.execute(delete(db.TMDBMap).where(db.TMDBMap.kind == 'series'))
                    out["deleted"]["map_series"] = int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["map_kind_error"] = str(e)
        # Explicit collections clear if requested
        if "collections" in what:
            try:
                s.execute(delete(db.TMDBCollectionMovie))
                res = s.execute(delete(db.TMDBCollection))
                out["deleted"]["collections"] = int(getattr(res, "rowcount", 0) or 0)
            except Exception as e:
                out["deleted"]["collections_error"] = str(e)
        # Reset ingest statuses so that cleared items become pending again
        try:
            if "movies" in what:
                res = s.execute(
                    update(db.TMDBIngestStatus)
                    .where(db.TMDBIngestStatus.key_type == 'movie')
                    .values(status='pending', tmdb_id=None, last_error=None, retries=0, last_processed_ts=None)
                )
                out["reset"]["movies_status"] = int(getattr(res, "rowcount", 0) or 0)
            if "series" in what:
                res1 = s.execute(
                    update(db.TMDBIngestStatus)
                    .where(db.TMDBIngestStatus.key_type == 'series')
                    .values(status='pending', tmdb_id=None, last_error=None, retries=0, last_processed_ts=None)
                )
                out["reset"]["series_status"] = int(getattr(res1, "rowcount", 0) or 0)
                res2 = s.execute(
                    update(db.TMDBIngestStatus)
                    .where(db.TMDBIngestStatus.key_type == 'episode')
                    .values(status='pending', tmdb_id=None, last_error=None, retries=0, last_processed_ts=None)
                )
                out["reset"]["episodes_status"] = int(getattr(res2, "rowcount", 0) or 0)
            elif "episodes" in what:
                res = s.execute(
                    update(db.TMDBIngestStatus)
                    .where(db.TMDBIngestStatus.key_type == 'episode')
                    .values(status='pending', tmdb_id=None, last_error=None, retries=0, last_processed_ts=None)
                )
                out["reset"]["episodes_status"] = int(getattr(res, "rowcount", 0) or 0)
        except Exception as e:
            out["reset"]["error"] = str(e)

        s.commit()
        # Return remaining counts to confirm clear actually applied
        try:
            out["remaining"]["map"] = s.query(db.TMDBMap).count()
            out["remaining"]["movies"] = s.query(db.TMDBMovie).count()
            out["remaining"]["series"] = s.query(db.TMDBSeries).count()
            out["remaining"]["seasons"] = s.query(db.TMDBSeason).count()
            out["remaining"]["episodes"] = s.query(db.TMDBEpisode).count()
            out["remaining"]["collections"] = s.query(db.TMDBCollection).count()
        except Exception:
            pass
    return {"ok": True, **out}


@router.get("/admin/tmdb/counts")
def tmdb_counts():
    """Returns row counts for TMDB tables to verify clears/population."""
    out: Dict[str, int] = {}
    try:
        with db.SessionLocal() as s:
            out["map"] = s.query(db.TMDBMap).count()
            out["movies"] = s.query(db.TMDBMovie).count()
            out["series"] = s.query(db.TMDBSeries).count()
            out["seasons"] = s.query(db.TMDBSeason).count()
            out["episodes"] = s.query(db.TMDBEpisode).count()
    except Exception as e:
        raise HTTPException(500, f"count error: {e}")
    return {"ok": True, "counts": out}


@router.post("/admin/tmdb/cleanup_orphans")
def tmdb_cleanup_orphans():
    """Removes tmdb_ingest_status rows that are no longer referenced by any playlist items.

    Recomputes the set of movie/series signatures and episode triplets present in PlaylistItem,
    then deletes any ingest status rows not in those sets.
    """
    deleted = 0
    total = 0
    remaining = 0
    try:
        from sqlalchemy import select
        with db.SessionLocal() as s:
            # Compute current signatures from PlaylistItem
            rows = s.execute(select(db.PlaylistItem)).scalars().all()
            movie_sigs: set[str] = set()
            series_sigs: set[str] = set()
            ep_triplets: set[tuple[str, int, int]] = set()
            for r in rows:
                kind = (r.kind or 'live').lower()
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
            # Iterate existing statuses and delete orphans
            sts = s.execute(select(db.TMDBIngestStatus)).scalars().all()
            total = len(sts)
            for st in sts:
                kt = (st.key_type or '').lower()
                if kt == 'movie':
                    if st.movie_sig and st.movie_sig not in movie_sigs:
                        s.delete(st)
                        deleted += 1
                elif kt == 'series':
                    if st.series_sig and st.series_sig not in series_sigs:
                        s.delete(st)
                        deleted += 1
                elif kt == 'episode':
                    trip = None
                    try:
                        if st.series_sig is not None and st.season is not None and st.episode is not None:
                            trip = (st.series_sig, int(st.season), int(st.episode))
                    except Exception:
                        trip = None
                    if trip and trip not in ep_triplets:
                        s.delete(st)
                        deleted += 1
            if deleted:
                s.commit()
            remaining = s.query(db.TMDBIngestStatus).count()
        return {"ok": True, "deleted": deleted, "remaining": remaining, "total": total}
    except Exception as e:
        raise HTTPException(500, f"cleanup_orphans_error: {e}")
