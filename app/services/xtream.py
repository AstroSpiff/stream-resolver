"""
Service Xtream: funzioni pure per gestione cache, parsing M3U, categorie.

End-point HTTP e logging specifico client restano nel router.
"""
from __future__ import annotations

import os
import re
import unicodedata
import urllib.parse
import zlib
import threading
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
from collections import defaultdict

from app import config
from app import db
from sqlalchemy.exc import OperationalError
import logging

logger = logging.getLogger(__name__)


# ====== SMALL UTILS ======
def now_ts() -> int:
    return config.now_ts()


def crc32_num(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def enc(url: str) -> str:
    return urllib.parse.quote(url, safe="")


# ====== PATHS ======
XTREAMS_JSON = config.XTREAMS_JSON
XTREAM_CACHE_DIR = config.XTREAM_CACHE_DIR
CATEGORY_IDS_JSON = config.CATEGORY_IDS_JSON
PLAYLISTS_DIR = config.PLAYLISTS_DIR


# ====== STORAGE ======
def xtreams() -> List[Dict[str, Any]]:
    with db.SessionLocal() as s:
        return db.list_xtreams(s)


def save_xtreams(items: List[Dict[str, Any]], overwrite: bool = False) -> None:
    with db.SessionLocal() as s:
        db.upsert_xtreams(s, items)
        s.commit()


# ====== CATEGORY IDS (persistent map) ======
CATEGORY_IDS_LOCK = threading.Lock()
with CATEGORY_IDS_LOCK:
    CATEGORY_IDS: Dict[str, str] = config.read_json(CATEGORY_IDS_JSON, {})


def stable_category_id(name: str, base: int) -> str:
    return str(base + (crc32_num(name) % 8999))


def get_category_id(name: str, base: int) -> str:
    with CATEGORY_IDS_LOCK:
        cid = CATEGORY_IDS.get(name)
        if cid:
            return cid
        cid = stable_category_id(name, base)
        CATEGORY_IDS[name] = cid
        config.write_json(CATEGORY_IDS_JSON, CATEGORY_IDS)
        return cid


def normalize_group_for_type(group: str, typ: str) -> str:
    g = (group or "").strip()
    if typ == "vod":
        g = re.sub(r"^(film|movies?)\s*-\s*", "", g, flags=re.I)
    elif typ == "series":
        g = re.sub(r"^(serietv|serie)\s*-\s*", "", g, flags=re.I)
    elif typ == "live":
        g = re.sub(r"^(live|tv)\s*-\s*", "", g, flags=re.I)
    return g or "Generale"


# ====== M3U parsing ======
M3U_LINE = re.compile(
    r'#EXTINF:(?P<duration>-?\d+)\s*(?P<attrs>(?:\s+[a-z0-9\-]+="[^"]*")*)\s*,\s*(?P<title>.*)$',
    re.IGNORECASE,
)
ATTR_RE = re.compile(r'([a-z0-9\-]+)="([^"]*)"', re.IGNORECASE)


@dataclass
class M3UItem:
    title: str
    url: str
    attrs: Dict[str, str]
    group: str
    tvg_id: str
    tvg_logo: str
    raw: str


def parse_m3u(text: str) -> List[M3UItem]:
    items: List[M3UItem] = []
    lines = [l.rstrip("\n") for l in text.splitlines()]
    last_inf: Optional[Tuple[Dict[str, str], str]] = None
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            m = M3U_LINE.match(line)
            if not m:
                continue
            attrs_str = m.group("attrs") or ""
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(attrs_str)}
            title = m.group("title").strip()
            last_inf = (attrs, title)
        elif line and not line.startswith("#"):
            if last_inf:
                attrs, title = last_inf
                group = attrs.get("group-title", "").strip()
                tvg_id = attrs.get("tvg-id", "").strip()
                tvg_logo = attrs.get("tvg-logo", "").strip()
                items.append(
                    M3UItem(
                        title=title,
                        url=line.strip(),
                        attrs=attrs,
                        group=group,
                        tvg_id=tvg_id,
                        tvg_logo=tvg_logo,
                        raw="",
                    )
                )
                last_inf = None
    return items


def _playlist_file(pl_id: str) -> str:
    return os.path.join(PLAYLISTS_DIR, f"{pl_id}.m3u")


def _read_playlist(pl_id: str) -> List[M3UItem]:
    # Se backend=db, ricostruisci la lista dagli items importati
    if config.get_storage_backend() == 'db':
        try:
            with db.SessionLocal() as s:
                rows = s.query(db.PlaylistItem).filter(db.PlaylistItem.playlist_id == pl_id).all()
                out: List[M3UItem] = []
                for r in rows:
                    out.append(M3UItem(
                        title=r.title or "",
                        url=r.original_url,
                        attrs=r.attrs or {},
                        group=r.group_title or "",
                        tvg_id=r.tvg_id or "",
                        tvg_logo=r.tvg_logo or "",
                        raw="",
                    ))
                return out
        except Exception:
            pass
    # Fallback: leggi da file m3u salvato
    path = _playlist_file(pl_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_m3u(f.read())
    except FileNotFoundError:
        return []


# ====== CLASSIFICATION ======
MOVIE_RE = re.compile(r"/movie/(?:[^/]+/[^/]+/)?(\d+)", re.I)
TV_RE = re.compile(r"/(?:tv|series)/(?:[^/]+/[^/]+/)?(\d+)/(?:season/)?(\d+)/(\d+)", re.I)
TV_RE_SHORT = re.compile(r"/(?:tv|series)/(?:[^/]+/[^/]+/)?(\d+)/(\d+)/(\d+)", re.I)


def try_extract_movie_id(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    if "u" in q and q["u"]:
        target_url = q["u"][0]
        while True:
            dec = urllib.parse.unquote(target_url)
            if dec == target_url:
                break
            target_url = dec
        m = MOVIE_RE.search(target_url)
        if m:
            return m.group(1)
    m = MOVIE_RE.search(url)
    return m.group(1) if m else None


def try_extract_tv_triplet(url: str) -> Optional[Tuple[str, int, int]]:
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    if "u" in q and q["u"]:
        url = urllib.parse.unquote(q["u"][0])
    else:
        url = urllib.parse.unquote(url)
    for rgx in (TV_RE, TV_RE_SHORT):
        m = rgx.search(url)
        if m:
            sid, season, episode = m.group(1), int(m.group(2)), int(m.group(3))
            return sid, season, episode
    return None


def guess_is_series(item: M3UItem) -> bool:
    if try_extract_tv_triplet(item.url):
        return True
    g = item.group.lower()
    t = item.title.lower()
    if "serie" in g or "series" in g or "stagione" in t or re.search(r"\bs\d{1,2}e\d{1,2}\b", t, re.I):
        return True
    return False


def guess_is_movie(item: M3UItem) -> bool:
    if try_extract_movie_id(item.url):
        return True
    g = item.group.lower()
    if "film" in g or "movie" in g:
        return True
    return False


# ====== MIXED CLASSIFICATION ======
def split_mixed_items(items: Iterable[M3UItem]):
    """Smista una lista mista in (live, movies, series) usando euristiche.

    - Series: priorità se rilevata tripla TV (sid/season/episode) o pattern serie.
    - Movies: se rilevato id film o pattern film.
    - Live: fallback per tutto ciò che non è film/serie.
    """
    live: List[M3UItem] = []
    movies: List[M3UItem] = []
    series: List[M3UItem] = []
    for it in items or []:
        try:
            if try_extract_tv_triplet(it.url) or guess_is_series(it):
                series.append(it)
                continue
            if try_extract_movie_id(it.url) or guess_is_movie(it):
                movies.append(it)
                continue
            # fallback: tratta come Live (canali)
            live.append(it)
        except Exception:
            # in caso di errori imprevisti, non perdere l'elemento: considera live
            live.append(it)
    return live, movies, series


# ====== NORMALIZZAZIONE ID CANALE ======
_PARENS_RE = re.compile(r"[()\[\]{}]")
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9_]+")


def _slug_id(name: str) -> str:
    s = (name or "").strip()
    s = _PARENS_RE.sub("", s)  # rimuovi parentesi
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")  # to ASCII
    s = s.replace(" ", "_")
    s = _NON_ALNUM_RE.sub("", s)  # rimuovi caratteri non alfanumerici
    return s or "channel"


def _fmt_hhmmss(secs: int) -> str:
    try:
        secs = max(1, int(secs))
    except Exception:
        secs = 1
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ====== DIRECT SOURCE ======
def _already_direct(url: str, base: str, endpoint: str) -> bool:
    try:
        u = urllib.parse.urlparse(url)
        b = urllib.parse.urlparse(base)
        qs = urllib.parse.parse_qs(u.query)
        return u.netloc == b.netloc and u.path.rstrip("/") == f"/{endpoint}" and "u" in qs
    except Exception:
        return False


def make_direct_video(base_url: str, original_url: str) -> str:
    if _already_direct(original_url, base_url, "video"):
        return original_url
    # Se è già un link /tv?u=... dello stesso host, estrai l'URL interno
    try:
        u = urllib.parse.urlparse(original_url)
        b = urllib.parse.urlparse(base_url)
        qs = urllib.parse.parse_qs(u.query)
        if u.netloc == b.netloc and u.path.rstrip("/") in ("/video", "/tv") and "u" in qs:
            inner = qs.get("u", [""])[0]
            if inner:
                return f"{base_url}/video?u={enc(inner)}"
    except Exception:
        pass
    return f"{base_url}/video?u={enc(original_url)}"


def make_direct_live(base_url: str, original_url: str) -> str:
    if _already_direct(original_url, base_url, "tv"):
        return original_url
    # Se è già un link /video?u=... dello stesso host, estrai l'URL interno
    try:
        u = urllib.parse.urlparse(original_url)
        b = urllib.parse.urlparse(base_url)
        qs = urllib.parse.parse_qs(u.query)
        if u.netloc == b.netloc and u.path.rstrip("/") in ("/video", "/tv") and "u" in qs:
            inner = qs.get("u", [""])[0]
            if inner:
                return f"{base_url}/tv?u={enc(inner)}"
    except Exception:
        pass
    return f"{base_url}/tv?u={enc(original_url)}"


# ====== DURATE ======
def _extract_duration(attrs: Dict[str, str]) -> int:
    for key in ("tvg-duration", "tvg-duration-secs", "duration", "duration_secs"):
        val = (attrs.get(key) or "").strip()
        if not val:
            continue
        try:
            secs = int(float(val))
            if secs > 0:
                return secs
        except ValueError:
            pass
        if ":" in val:
            parts = val.split(":")
            try:
                nums = [int(p) for p in parts]
            except ValueError:
                nums = []
            if len(nums) == 3:
                h, m, s = nums
            elif len(nums) == 2:
                h = 0
                m, s = nums
            else:
                h = m = s = -1
            if h >= 0 and m >= 0 and s >= 0:
                secs = h * 3600 + m * 60 + s
                if secs > 0:
                    return secs
    return 1


# ====== COSTRUZIONE STRUTTURE ======
def build_live_streams(base_url: str, items: Iterable[M3UItem]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    out: List[Dict[str, Any]] = []
    cat_map: Dict[str, str] = {}
    used_epg_ids: set[str] = set()
    base_counts: Dict[str, int] = defaultdict(int)
    used_stream_ids: set[int] = set()
    SAFE_MAX = 1_000_000_000
    num = 1
    for it in items:
        cat_name = normalize_group_for_type(it.group or "Live", "live")
        cat_id = get_category_id(cat_name, 1000)
        cat_map[cat_name] = cat_id
        sid = (crc32_num(it.url) % SAFE_MAX) + 1
        while sid in used_stream_ids:
            sid += 1
            if sid > SAFE_MAX:
                sid = 1
        used_stream_ids.add(sid)
        stream_id = sid
        base_epg = (it.tvg_id or "").strip() or _slug_id(it.title) or f"ch_{stream_id}"
        epg_id = base_epg
        if epg_id in used_epg_ids:
            base_counts[base_epg] += 1
            i = base_counts[base_epg]
            while f"{base_epg}_{i}" in used_epg_ids:
                i += 1
            epg_id = f"{base_epg}_{i}"
            base_counts[base_epg] = i
        used_epg_ids.add(epg_id)

        out.append(
            {
                "num": num,
                "name": it.title.strip(),
                "stream_type": "live",
                "type": "live",
                "type_name": "Live",
                "type_key": "live",
                "stream_id": stream_id,
                "stream_icon": it.tvg_logo or "",
                "epg_channel_id": epg_id,
                "tvg_id": epg_id,
                "category_id": cat_id,
                "category_id_int": int(cat_id),
                "category_name": cat_name,
                "added": str(now_ts()),
                "is_adult": "0",
                "custom_sid": "",
                "tv_archive": 0,
                "tv_archive_duration": 0,
                "bitrate": "0",
                "stream_status": 1,
                "container_extension": "m3u8",
                "direct_source": make_direct_live(base_url, it.url),
            }
        )
        num += 1
    return out, cat_map


def build_vod_streams(base_url: str, m3us: Iterable[M3UItem]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    out: List[Dict[str, Any]] = []
    cat_map: Dict[str, str] = {}
    num = 1
    st = config.load_settings()
    tmdb_cfg = (st.get('tmdb') or {})
    lang = tmdb_cfg.get('language') or 'it-IT'
    mv_fields = set((tmdb_cfg.get('movie_fields') or []))
    for it in m3us:
        if not (guess_is_movie(it) or try_extract_movie_id(it.url)):
            continue
        mid = try_extract_movie_id(it.url) or str(crc32_num(it.url))
        cat_name = normalize_group_for_type(it.group or "Film", "vod")
        cat_id = get_category_id(cat_name, 2000)
        cat_map[cat_name] = cat_id
        name = it.title.strip()
        stream_icon = it.tvg_logo or ""
        rating_val = None
        # Prefer TMDB metadata if present
        try:
            with db.SessionLocal() as s:
                # build signature like in admin_tmdb
                from app.routers.admin_tmdb import _norm_title_year, _sig_for
                t, y = _norm_title_year(it.title, it.attrs or {})
                sig = _sig_for('movie', t, y)
                mrow = s.get(db.TMDBMap, sig)
                if mrow:
                    row = s.get(db.TMDBMovie, {"tmdb_id": mrow.tmdb_id, "language": lang})
                    if row:
                        if 'name' in mv_fields and (row.title or ''):
                            name = row.title
                        if 'poster' in mv_fields and (row.poster_path or ''):
                            stream_icon = ("https://image.tmdb.org/t/p/w500" + row.poster_path)
                        if 'rating' in mv_fields and row.rating is not None:
                            rating_val = float(row.rating)
        except Exception:
            pass
        # Durata: preferisci TMDB runtime se selezionato, poi EXTINF
        dur_secs = _extract_duration(it.attrs)
        try:
            if 'duration' in mv_fields:
                with db.SessionLocal() as s:
                    from app.routers.admin_tmdb import _norm_title_year, _sig_for
                    t, y = _norm_title_year(it.title, it.attrs or {})
                    sig = _sig_for('movie', t, y)
                    mrow = s.get(db.TMDBMap, sig)
                    if mrow:
                        row = s.get(db.TMDBMovie, {"tmdb_id": mrow.tmdb_id, "language": lang})
                        if row and row.runtime_mins:
                            dur_secs = int(row.runtime_mins) * 60
        except Exception:
            pass
        if rating_val is None:
            rating_raw = (it.attrs.get("tvg-rating") or it.attrs.get("rating") or "").strip()
            try:
                rating_val = float(rating_raw) if rating_raw else None
            except Exception:
                rating_val = None
        try:
            rating_5 = int(min(5, max(0, round((rating_val or 0.0) / 2.0))))
        except Exception:
            rating_5 = 0

        out.append(
            {
                "num": str(num),
                "name": name,
                "stream_id": str(mid),
                "stream_type": "movie",
                "stream_icon": stream_icon,
                "rating": rating_val,
                "rating_5based": rating_5,
                "added": "",
                "duration": str(dur_secs),
                "duration_secs": str(dur_secs),
                "duration_fmt": _fmt_hhmmss(dur_secs),
                "category_id": cat_id,
                "category_name": cat_name,
                "bitrate": "0",
                "epg_channel_id": _slug_id(name),
                "container_extension": "m3u8",
                "direct_source": make_direct_video(base_url, it.url),
            }
        )
        num += 1
    return out, cat_map


def build_series_collections(base_url: str, items: Iterable[M3UItem]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    series_map: Dict[str, Dict[str, Any]] = {}
    cat_map: Dict[str, str] = {}
    st = config.load_settings()
    tmdb_cfg = (st.get('tmdb') or {})
    lang = tmdb_cfg.get('language') or 'it-IT'
    sr_fields = set((tmdb_cfg.get('series_fields') or []))
    for it in items:
        trip = try_extract_tv_triplet(it.url)
        if not (guess_is_series(it) or trip):
            continue
        if not trip:
            continue
        sid, season, episode = trip
        name = re.sub(r"\bS(\d{1,2})E(\d{1,2})\b", "", it.title, flags=re.I).strip() or f"Serie {sid}"
        cover = it.tvg_logo or ""
        # Try TMDB for series-level metadata
        try:
            with db.SessionLocal() as s:
                from app.routers.admin_tmdb import _norm_title_year, _sig_for
                t, _y = _norm_title_year(it.title, it.attrs or {})
                sig = _sig_for('series', t, None)
                mrow = s.get(db.TMDBMap, sig)
                if mrow:
                    row = s.get(db.TMDBSeries, {"tmdb_id": mrow.tmdb_id, "language": lang})
                    if row:
                        if 'name' in sr_fields and (row.name or ''):
                            name = row.name
                        if 'poster' in sr_fields and (row.poster_path or ''):
                            cover = ("https://image.tmdb.org/t/p/w500" + row.poster_path)
        except Exception:
            pass
        cat_name = normalize_group_for_type(it.group or "Serie", "series")
        cat_id = get_category_id(cat_name, 3000)
        cat_map[cat_name] = cat_id
        s = series_map.setdefault(
            sid,
            {
                "series_id": sid,
                "name": name,
                "cover": cover,
                "plot": "",
                "rating": "",
                "category_id": cat_id,
                "episodes_by_season": defaultdict(list),
                "category_name": cat_name,
            },
        )
        ep_code = f"S{season:02d}E{episode:02d}"
        ep_id = str(crc32_num(f"{sid}:{season}:{episode}"))
        dur_secs = _extract_duration(it.attrs)
        # Calcola durata episodio: preferisci TMDB se selezionato
        ep_secs = _extract_duration(it.attrs)
        try:
            if 'duration' in sr_fields:
                with db.SessionLocal() as s2:
                    from app.routers.admin_tmdb import _norm_title_year, _sig_for
                    t2, _ = _norm_title_year(it.title, it.attrs or {})
                    sig2 = _sig_for('series', t2, None)
                    mrow2 = s2.get(db.TMDBMap, sig2)
                    if mrow2:
                        row2 = s2.get(db.TMDBSeries, {"tmdb_id": mrow2.tmdb_id, "language": lang})
                        if row2 and row2.episode_run_time_mins:
                            ep_secs = int(row2.episode_run_time_mins) * 60
        except Exception:
            pass
        s["episodes_by_season"][str(season)].append(
            {
                "id": ep_id,
                "title": ep_code,
                "episode_num": int(episode),
                "season": int(season),
                "container_extension": "mp4",
                "info": {
                    "movie_image": cover,
                    "plot": "",
                    "duration": str(ep_secs),
                    "duration_secs": str(ep_secs),
                    "duration_fmt": _fmt_hhmmss(ep_secs),
                },
                "direct_source": make_direct_video(base_url, it.url),
            }
        )

    ep_re = re.compile(r"E(\d+)$", re.I)
    
    def _episode_num(title: str) -> int:
        m = ep_re.search(title or "")
        return int(m.group(1)) if m else 0

    for sm in series_map.values():
        for k, eps in sm.get("episodes_by_season", {}).items():
            eps.sort(key=lambda e: _episode_num(str(e.get("title", ""))))
    return series_map, cat_map


def items_for_xtream_selection(sel_ids: List[str]) -> List[M3UItem]:
    items: List[M3UItem] = []
    for pid in sel_ids or []:
        items.extend(_read_playlist(pid))
    return items


# ====== CACHE STATUS + BUILD ======
BUILDING_LOCK = threading.Lock()
BUILDING_IDS: set[str] = set()


def get_xtream_cache_status(xt: Dict[str, Any]) -> str:
    xt_id = xt.get("id")
    if not xt_id:
        return "sconosciuto"
    with BUILDING_LOCK:
        if xt_id in BUILDING_IDS:
            return "in costruzione"
    cache_file = os.path.join(XTREAM_CACHE_DIR, f"{xt_id}.json")
    if not os.path.exists(cache_file):
        return "scaduta"
    every_hours = int(xt.get("every_hours", 12) or 12)
    last_refresh = int(xt.get("last_refresh", 0) or 0)
    if now_ts() - last_refresh > every_hours * 3600:
        return "scaduta"
    return "pronta"


def build_xtream_cache(base_url: str, xt_config: Dict[str, Any]) -> Dict[str, Any]:
    has_valid_lists = (
        xt_config.get("live_list_ids")
        or xt_config.get("movie_list_ids")
        or xt_config.get("series_list_ids")
        or xt_config.get("mixed_list_ids")
    )
    if not has_valid_lists:
        # Scrivi comunque una cache minima su disco per evitare "scaduta" permanente
        cache = {
            "live_streams": [],
            "live_categories": {},
            "vod_streams": [],
            "vod_categories": {},
            "series_map": {},
            "series_categories": {},
            "movie_items": [],
            "counts": {},
        }
        cache_file = os.path.join(XTREAM_CACHE_DIR, f"{xt_config.get('id')}.json")
        config.write_json(cache_file, cache)
        return cache

    # Raccogli elementi espliciti
    live_items = items_for_xtream_selection(xt_config.get("live_list_ids", []))
    movie_items = items_for_xtream_selection(xt_config.get("movie_list_ids", []))
    series_items = items_for_xtream_selection(xt_config.get("series_list_ids", []))
    # Smista i "mixed" automaticamente
    mixed_all = items_for_xtream_selection(xt_config.get("mixed_list_ids", []))
    m_live, m_movies, m_series = split_mixed_items(mixed_all)
    live_items += m_live
    movie_items += m_movies
    series_items += m_series

    live_streams, live_cats = build_live_streams(base_url, live_items)
    vod_streams, vod_cats = build_vod_streams(base_url, movie_items)
    series_map, series_cats = build_series_collections(base_url, series_items)

    cache = {
        "live_streams": live_streams,
        "live_categories": live_cats,
        "vod_streams": vod_streams,
        "vod_categories": vod_cats,
        "series_map": series_map,
        "series_categories": series_cats,
        "movie_items": [asdict(m) for m in movie_items],
        "counts": {
            "available_channels": len(live_items),
            "available_movies": len(movie_items),
            "available_series": len(series_items),
        },
    }

    cache_file = os.path.join(XTREAM_CACHE_DIR, f"{xt_config.get('id')}.json")
    config.write_json(cache_file, cache)
    return cache


def spawn_build(base_url: str, xt: Dict[str, Any]):
    xid = xt.get("id") if isinstance(xt, dict) else None
    if not xid:
        return

    def _job():
        try:
            build_xtream_cache(base_url, xt)
            # aggiorna last_refresh e persisti
            try:
                xt["last_refresh"] = now_ts()
                items = xtreams()
                for i, it in enumerate(items):
                    if it.get("id") == xid:
                        items[i]["last_refresh"] = xt["last_refresh"]
                        break
                save_xtreams(items, overwrite=True)
            except Exception:
                # non bloccare in caso di errori di IO
                pass
        finally:
            with BUILDING_LOCK:
                BUILDING_IDS.discard(xid)

    with BUILDING_LOCK:
        if xid in BUILDING_IDS:
            return
        BUILDING_IDS.add(xid)

    t = threading.Thread(target=_job, daemon=True)
    t.start()


# ====== BASE URL RISOLVER ======
def stream_resolver_base(request) -> str:
    """Base URL da usare per costruire i link diretti /tv e /video.

    Usa il primo preset configurato in settings.resolvers (se presente),
    altrimenti fallback al campo legacy stream_resolver_url oppure all'URL della richiesta.
    """
    base = (config.get_stream_resolver_base(None) or "").strip()
    if base:
        if not re.match(r"^https?://", base, re.I):
            base = "http://" + base
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


# ====== AUTH XTREAM ======
def require_xtream(xt_id: str, username: str, password: str) -> Dict[str, Any]:
    """Trova una config Xtream per id + credenziali oppure 401."""
    from fastapi import HTTPException
    username = (username or "").strip()
    password = (password or "").strip()
    for row in xtreams():
        if row.get("id") == xt_id and row.get("username") == username and row.get("password") == password:
            return row
    raise HTTPException(401, "Unauthorized")


def find_xtream_by_creds(username: str, password: str) -> Optional[Dict[str, Any]]:
    username = (username or "").strip()
    password = (password or "").strip()
    for row in xtreams():
        if row.get("username") == username and row.get("password") == password:
            return row
    return None


def get_and_validate_xtream(
    username: Optional[str],
    password: Optional[str],
    xt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Valida e ritorna la config Xtream seguendo la stessa logica del manager."""
    from fastapi import HTTPException
    pass_masked = f"{(password or '')[:2]}****" if isinstance(password, str) and len(password) > 2 else "****"
    logger.info(
        "Validating Xtream access for user='%s', pass='%s', xt_id='%s'",
        username,
        pass_masked,
        xt_id,
    )
    if not username or not password:
        logger.warning("Auth failed: Username or password missing.")
        raise HTTPException(status_code=401, detail="Username and password are required")
    if xt_id:
        try:
            return require_xtream(xt_id, username, password)
        except HTTPException:
            pass
    xt = find_xtream_by_creds(username, password)
    if xt:
        return xt
    xs = xtreams()
    if len(xs) == 1:
        return xs[0]
    logger.warning("Auth failed for user='%s': Invalid credentials or no matching Xtream account found.", username)
    raise HTTPException(status_code=401, detail="Unauthorized: Invalid credentials or no matching Xtream account found.")


def require_xt_id(xt: Dict[str, Any]) -> str:
    from fastapi import HTTPException
    xid = xt.get("id")
    if not isinstance(xid, str) or not xid:
        raise HTTPException(500, "Invalid Xtream configuration: missing id")
    return xid


def require_xt_creds(xt: Dict[str, Any]) -> Tuple[str, str]:
    from fastapi import HTTPException
    u = xt.get("username")
    p = xt.get("password")
    if not isinstance(u, str) or not u or not isinstance(p, str) or not p:
        raise HTTPException(500, "Invalid Xtream configuration: missing credentials")
    return u, p


# ====== XMLTV BUILDER ======
def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def xmltv_from_cache(cache: Optional[Dict[str, Any]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv generator-info-name="stream-resolver">']
    if cache:
        for s in cache.get("live_streams", []):
            ch_id = str(s.get("epg_channel_id") or s.get("stream_id") or "ch")
            name = _xml_escape(str(s.get("name") or ch_id))
            logo = str(s.get("stream_icon") or "").strip()
            lines.append(f'  <channel id="{_xml_escape(ch_id)}">')
            lines.append(f'    <display-name>{name}</display-name>')
            if logo:
                lines.append(f'    <icon src="{_xml_escape(logo)}"/>')
            lines.append('  </channel>')
    lines.append('</tv>')
    return "\n".join(lines)


# ====== VOD INFO ======
def build_vod_info(base_url: str, vod_id: str, all_items: Iterable[M3UItem]) -> Dict[str, Any]:
    chosen: Optional[M3UItem] = None
    for it in all_items:
        mid = try_extract_movie_id(it.url)
        if str(mid) == str(vod_id):
            chosen = it
            break
    if not chosen:
        for it in all_items:
            if str(crc32_num(it.url)) == str(vod_id):
                chosen = it
                break
    if not chosen:
        from fastapi import HTTPException
        raise HTTPException(404, "VOD non trovato")

    title = chosen.title.strip()
    year = ""
    m = re.search(r"(19|20)\d{2}", title)
    if m:
        year = m.group(0)
    else:
        for key in ("tvg-year", "tvg_year", "year", "releasedate", "release-date"):
            y = chosen.attrs.get(key, "").strip()
            m2 = re.search(r"(19|20)\d{2}", y)
            if m2:
                year = m2.group(0)
                break

    title_clean = re.sub(r"\s*\([^()]*\)\s*", " ", title).strip()
    title_clean = re.sub(r"\s+", " ", title_clean)
    final_name = f"{title_clean} ({year})" if year else title_clean

    duration = _extract_duration(chosen.attrs)
    movie_image = chosen.tvg_logo or ""
    rating_val: Optional[float] = None
    try:
        r = chosen.attrs.get("tvg-rating") or chosen.attrs.get("rating")
        if r:
            rating_val = float(r)
    except Exception:
        rating_val = None

    info = {
        "imdb_id": "",
        "movie_image": movie_image,
        "genre": "",
        "plot": "",
        "cast": "",
        "director": "",
        "rating": rating_val,
        "releasedate": year,
        "duration_secs": str(duration),
        "duration": _fmt_hhmmss(duration),
        "bitrate": "",
        "kinopoisk_url": "",
        "episode_run_time": "",
        "youtube_trailer": "",
        "actors": "",
        "name": final_name,
        "name_o": final_name,
        "cover_big": movie_image,
        "description": "",
        "age": "",
        "rating_mpaa": "",
        "rating_count_kinopoisk": 0,
        "country": "",
        "backdrop_path": [],
        "audio": [],
        "video": [],
    }
    movie_data = {
        "stream_id": str(vod_id),
        "name": final_name,
        "added": "",
        "category_id": "",
        "container_extension": "m3u8",
        "custom_sid": "",
        "direct_source": "",
    }
    return {"info": info, "movie_data": movie_data}
