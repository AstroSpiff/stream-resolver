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

from app.services import policies as pol

logger = logging.getLogger(__name__)


TV_ENDPOINTS = {"/tv", "/tv.m3u8", "/tv.mp4"}
VIDEO_ENDPOINTS = {"/video", "/video.m3u8", "/video.mp4"}
_POLICY_EXT_CACHE: Dict[Tuple[str, str], Optional[str]] = {}


def normalize_endpoint(path: Optional[str]) -> str:
    return (path or "").strip().lower().rstrip('/')


def is_tv_endpoint(path: Optional[str]) -> bool:
    return normalize_endpoint(path) in TV_ENDPOINTS


def is_video_endpoint(path: Optional[str]) -> bool:
    return normalize_endpoint(path) in VIDEO_ENDPOINTS


def unwrap_internal_url(url: str, base_url: str, max_depth: int = 5) -> str:
    """Estrae l'URL originale da catene annidate /tv?u=/video?u=... limitando la profondità."""
    current = url
    seen = set()
    try:
        base = urllib.parse.urlparse(base_url)
    except Exception:
        return current
    for _ in range(max_depth):
        try:
            parsed = urllib.parse.urlparse(current)
        except Exception:
            break
        if parsed.netloc != base.netloc:
            break
        qs = urllib.parse.parse_qs(parsed.query)
        if "u" not in qs:
            break
        endpoint = normalize_endpoint(parsed.path)
        if endpoint not in TV_ENDPOINTS and endpoint not in VIDEO_ENDPOINTS:
            break
        candidate = (qs.get("u") or [""])[0]
        if not candidate or candidate in seen:
            break
        seen.add(candidate)
        current = candidate
    return current


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
    attrs: Dict[str, Any]
    group: str
    tvg_id: str
    tvg_logo: str
    raw: str
    source_playlist_id: Optional[str] = None
    source_order: Optional[int] = None


def parse_m3u(text: str) -> List[M3UItem]:
    items: List[M3UItem] = []
    lines = [l.rstrip("\n") for l in text.splitlines()]
    last_inf: Optional[Tuple[Dict[str, Any], str]] = None
    # Buffer per righe speciali (KODIPROP/EXTVLCOPT) da associare alla prossima URL
    special_headers: Dict[str, str] = {}
    special_license: Dict[str, Any] = {}
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            m = M3U_LINE.match(line)
            if not m:
                continue
            attrs_str = m.group("attrs") or ""
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(attrs_str)}
            title = m.group("title").strip()
            last_inf = (attrs, title)
        elif line.startswith('#KODIPROP:'):
            try:
                keyval = line.split(':', 1)[1]
                if '=' not in keyval:
                    continue
                k, v = keyval.split('=', 1)
                k = (k or '').strip().lower()
                v = (v or '').strip()
                # Headers
                if k == 'inputstream.adaptive.stream_headers':
                    # Esempi: "User-Agent=Foo" oppure "Header1=V1&Header2=V2"
                    parts = re.split(r'&|&amp;', v)
                    for p in parts:
                        if not p:
                            continue
                        if '=' in p:
                            hk, hv = p.split('=', 1)
                            hk = hk.strip()
                            hv = hv.strip()
                            if hk:
                                special_headers[hk] = hv
                elif k == 'inputstream.adaptive.license_type':
                    special_license['type'] = v.lower()
                elif k == 'inputstream.adaptive.license_key':
                    # Formato tipico clearkey: "kid:key" (hex)
                    if ':' in v:
                        kid, key = v.split(':', 1)
                        special_license['key_id'] = kid.strip()
                        special_license['key'] = key.strip()
                    else:
                        # fallback: tutto in key
                        special_license['key'] = v
            except Exception:
                # ignora errori parse KODIPROP
                pass
        elif line.startswith('#EXTVLCOPT:'):
            try:
                keyval = line.split(':', 1)[1]
                if '=' not in keyval:
                    continue
                k, v = keyval.split('=', 1)
                k = (k or '').strip().lower()
                v = (v or '').strip()
                if k == 'http-user-agent':
                    special_headers['User-Agent'] = v
            except Exception:
                pass
        elif line and not line.startswith("#"):
            if last_inf:
                attrs, title = last_inf
                group = attrs.get("group-title", "").strip()
                tvg_id = attrs.get("tvg-id", "").strip()
                tvg_logo = attrs.get("tvg-logo", "").strip()
                # Costruisci attrs.special se abbiamo raccolto info
                if special_headers or special_license:
                    try:
                        sp: Dict[str, Any] = {}
                        if special_headers:
                            sp['headers'] = dict(special_headers)
                        if special_license:
                            sp['license'] = dict(special_license)
                        # Format dal suffisso URL
                        u_lower = line.strip().lower()
                        if u_lower.endswith('.mpd'):
                            sp['format'] = 'dash'
                        elif u_lower.endswith('.m3u8'):
                            sp['format'] = 'hls'
                        # Flag requires_proxy se presenti headers o licenza
                        sp['requires_proxy'] = True
                        attrs = dict(attrs)
                        attrs['special'] = sp
                    except Exception:
                        pass
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
                # Reset buffer per prossima entry
                special_headers = {}
                special_license = {}
    return items


def _read_playlist(pl_id: str) -> List[M3UItem]:
    try:
        with db.SessionLocal() as s:
            prow = s.get(db.Playlist, pl_id)
            porder = getattr(prow, 'order_num', None) if prow else None
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
                    source_playlist_id=pl_id,
                    source_order=porder,
                ))
            return out
    except Exception:
        logger.exception("Errore nella lettura della playlist %s dal database", pl_id)
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
    """Heuristics to detect TV series episodes.

    Rules (to avoid false positives on live channels):
    - If URL contains explicit /tv/.../<sid>/<season>/<episode> → series.
    - Otherwise, detect explicit episode patterns in the EXTINF context (title, tvg-id), NOT by words like 'serie'/'series'.
      Accepted patterns:
        - SNNENN with optional spaces (e.g., S1E2, S01E12, S01 E12)
        - NxN (e.g., 1x2, 01x12)
    """
    if try_extract_tv_triplet(item.url):
        return True
    # Build a context string from title and tvg-id only (avoid group-title words like 'serie')
    ctx = f"{item.title} {item.tvg_id}".strip()
    if not ctx:
        return False
    # SNNENN (with optional spaces) — allow larger episode numbers, keep season reasonable
    if re.search(r"\bS\d{1,3}\s*E\d{1,4}\b", ctx, re.I):
        return True
    # Varianti: "S01 Ep12", "S01 Episodio 12", "Stagione 1 Episodio 2"
    if re.search(r"\bS\d{1,3}\s*(?:Ep|Episodio|Epis\.)\s*\d{1,4}\b", ctx, re.I):
        return True
    if re.search(r"\bStagione\s*\d{1,3}\s*(?:Episodio|Ep|Epis\.)\s*\d{1,4}\b", ctx, re.I):
        return True
    # NxN pattern (1–4 digits) with filter to avoid common resolutions like 1920x1080
    m = re.search(r"\b(\d{1,4})x(\d{1,4})\b", ctx, re.I)
    if m:
        try:
            a = int(m.group(1)); b = int(m.group(2))
            # Exclude if both sides look like resolution (>=1000x>=1000)
            if not (a >= 1000 and b >= 1000):
                return True
        except Exception:
            # If parsing fails, treat as non-series to stay safe
            pass
    return False


def guess_is_movie(item: M3UItem) -> bool:
    # 1) URL esplicita /movie/<id>
    if try_extract_movie_id(item.url):
        return True
    # 2) Evita falsi positivi: se sembra una serie, non è un film
    if guess_is_series(item):
        return False
    # 3) Heuristics: richiedi SEMPRE un anno (1900-2099) nel titolo
    #    e usa il group-title (film/movie) come ulteriore segnale.
    title = (item.title or "").strip()
    if not title:
        return False
    # Evita match su risoluzioni tipo 1920x1080
    if re.search(r"\b(19\d{2}|20\d{2})x\d{3,4}\b", title):
        return False
    has_year = bool(
        re.search(r"(\(|\[|\b)(19\d{2}|20\d{2})(\)|\]|\b)", title)
        or re.search(r"(?:\s|\-|\.|\/)\b(19\d{2}|20\d{2})\b\s*$", title)
    )
    if not has_year:
        return False
    g = (item.group or "").lower()
    if ("film" in g) or ("movie" in g):
        return True
    # Nessun indicatore di gruppo: per prudenza NON classificare come film
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


def _ext_from_url(url: str) -> Optional[str]:
    try:
        path = urllib.parse.urlparse(url).path
        ext = os.path.splitext(path)[1]
        if ext:
            return ext[1:].lower()
    except Exception:
        return None
    return None


def _preferred_extension(original_url: str, kind: str) -> Optional[str]:
    host = ""
    try:
        host = (urllib.parse.urlparse(original_url).hostname or "").lower()
    except Exception:
        host = ""
    key = (host, kind.lower())
    if key in _POLICY_EXT_CACHE:
        return _POLICY_EXT_CACHE[key]
    ext: Optional[str] = None
    try:
        policy = pol.pick_policy(original_url, kind, is_local=False)
        if policy:
            mode = (policy.get("remote_mode") or policy.get("local_mode") or "").lower()
            if mode == "mediaflow":
                mf = policy.get("mediaflow") or {}
                endpoint = (mf.get("endpoint") or "").strip().lower()
                path = (mf.get("path") or "").strip()
                if endpoint == "proxy" and path:
                    tail = path.split("/")[-1]
                    if "." in tail:
                        ext = tail.rsplit(".", 1)[-1].lower()
                if not ext:
                    ext = "m3u8"
            elif mode == "direct":
                ext = _ext_from_url(original_url)
            else:
                ext = None
    except Exception:
        ext = None
    _POLICY_EXT_CACHE[key] = ext
    return ext


def _prefer_or_default(ext: Optional[str], fallback: str) -> str:
    if not ext:
        return fallback
    ext = ext.lower().lstrip('.')
    if not ext or ext == 'ts':
        return fallback
    return ext


def make_direct_video(base_url: str, original_url: str) -> str:
    inner = unwrap_internal_url(original_url, base_url)
    ext = _prefer_or_default(_preferred_extension(inner, "video"), "m3u8")
    endpoint = "video" if ext in ("", "ts") else f"video.{ext}"
    return f"{base_url}/{endpoint}?u={enc(inner)}"


def make_direct_live(base_url: str, original_url: str) -> str:
    inner = unwrap_internal_url(original_url, base_url)
    ext = _prefer_or_default(_preferred_extension(inner, "tv"), "m3u8")
    endpoint = "tv" if ext in ("", "ts") else f"tv.{ext}"
    return f"{base_url}/{endpoint}?u={enc(inner)}"


# ====== DURATE ======
def _extract_duration(attrs: Dict[str, Any]) -> int:
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
def build_live_streams(base_url: str, items: Iterable[M3UItem], xt_config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    out: List[Dict[str, Any]] = []
    cat_map: Dict[str, str] = {}
    used_epg_ids: set[str] = set()
    base_counts: Dict[str, int] = defaultdict(int)
    used_stream_ids: set[int] = set()
    SAFE_MAX = 1_000_000_000
    num = 1
    live_fields = set(xt_config.get('export_live_fields') or [])

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

        stream_data = {
            "num": num,
            "name": it.title.strip(),
            "stream_type": "live",
            "stream_id": stream_id,
            "stream_icon": it.tvg_logo or "",
            "epg_channel_id": epg_id,
            "added": str(now_ts()),
            "category_id": cat_id,
            "custom_sid": "",
            "tv_archive": 0,
            "direct_source": make_direct_live(base_url, it.url),
            "tv_archive_duration": 0,
        }

        # Conditionally add fields based on export settings
        if 'type' in live_fields:
            stream_data['type'] = "live"
        if 'type_name' in live_fields:
            stream_data['type_name'] = "Live"
        if 'type_key' in live_fields:
            stream_data['type_key'] = "live"
        if 'tvg_id' in live_fields:
            stream_data['tvg_id'] = epg_id
        if 'category_id_int' in live_fields:
            stream_data['category_id_int'] = int(cat_id)
        if 'category_name' in live_fields:
            stream_data['category_name'] = cat_name
        if 'is_adult' in live_fields:
            stream_data['is_adult'] = "0"
        if 'bitrate' in live_fields:
            stream_data['bitrate'] = "0"
        if 'stream_status' in live_fields:
            stream_data['stream_status'] = 1
        if 'container_extension' in live_fields:
            stream_data['container_extension'] = "m3u8"

        out.append(stream_data)
        num += 1
    return out, cat_map


def build_vod_streams(base_url: str, m3us: Iterable[M3UItem], xt_config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    out: List[Dict[str, Any]] = []
    cat_map: Dict[str, str] = {}
    num = 1
    st = config.load_settings()
    tmdb_cfg = (st.get('tmdb') or {})
    lang = tmdb_cfg.get('language') or 'it-IT'
    mv_fields = set(xt_config.get('export_movie_fields') or [])
    policy = (xt_config.get('dedupe_policy') or 'm3u_order').strip()

    # Raggruppa per chiave contenuto (titolo normalizzato + anno)
    groups: Dict[str, List[M3UItem]] = defaultdict(list)
    from app.routers.admin_tmdb import _norm_title_year, _sig_for
    for it in m3us:
        if not (guess_is_movie(it) or try_extract_movie_id(it.url)):
            continue
        t, y = _norm_title_year(it.title, it.attrs or {})
        key = _sig_for('movie', t, y)
        groups[key].append(it)

    def pick(items: List[M3UItem], key: str) -> M3UItem:
        if not items:
            raise ValueError('empty items')
        if policy == 'random':
            idx = crc32_num(key) % len(items)
            return items[idx]
        # m3u_order / exclude_low: scegli quello con order_num più basso (priorità alta)
        def ordv(x: M3UItem) -> int:
            o = x.source_order
            try:
                return int(o) if o is not None else 10**9
            except Exception:
                return 10**9
        return sorted(items, key=lambda x: (ordv(x)))[0]

    for key, items in groups.items():
        it = pick(items, key)
        mid = try_extract_movie_id(it.url) or str(crc32_num(it.url))
        cat_name = normalize_group_for_type(it.group or "Film", "vod")
        cat_id = get_category_id(cat_name, 2000)
        cat_map[cat_name] = cat_id
        name = it.title.strip()
        stream_icon = it.tvg_logo or ""
        rating_val = None
        tmdb_movie = None
        try:
            with db.SessionLocal() as s:
                mrow = s.get(db.TMDBMap, key)
                if mrow:
                    tmdb_movie = s.get(db.TMDBMovie, (mrow.tmdb_id, lang))
        except Exception:
            tmdb_movie = None

        if tmdb_movie:
            if 'name' in mv_fields and (tmdb_movie.title or ''):
                name = tmdb_movie.title
            if 'poster' in mv_fields and (tmdb_movie.poster_path or ''):
                stream_icon = "https://image.tmdb.org/t/p/w500" + tmdb_movie.poster_path
            if 'rating' in mv_fields and tmdb_movie.rating is not None:
                try:
                    rating_val = float(tmdb_movie.rating)
                except Exception:
                    rating_val = None

        # Durata: preferisci TMDB runtime se selezionato, poi EXTINF
        base_duration = _extract_duration(it.attrs)
        dur_secs = base_duration
        if 'duration' in mv_fields and tmdb_movie and tmdb_movie.runtime_mins:
            try:
                dur_secs = int(tmdb_movie.runtime_mins) * 60
            except Exception:
                dur_secs = base_duration
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
                "num": num,
                "name": name,
                "stream_id": str(mid),
                "stream_type": "movie",
                "stream_icon": stream_icon,
                "rating": rating_val if rating_val is not None else 0.0,
                "rating_5based": rating_5,
                "added": str(now_ts()),
                "duration": str(dur_secs),
                "duration_secs": str(dur_secs),
                "duration_fmt": _fmt_hhmmss(dur_secs),
                "category_id": cat_id,
                "category_name": cat_name,
                "bitrate": "0",
                "epg_channel_id": _slug_id(name),
                "container_extension": "mp4",
                "direct_source": make_direct_video(base_url, it.url),
            }
        )
        num += 1
    return out, cat_map


def build_series_collections(base_url: str, items: Iterable[M3UItem], xt_config: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    series_map: Dict[str, Dict[str, Any]] = {}
    cat_map: Dict[str, str] = {}
    st = config.load_settings()
    tmdb_cfg = (st.get('tmdb') or {})
    lang = tmdb_cfg.get('language') or 'it-IT'
    sr_fields = set(xt_config.get('export_series_fields') or [])
    ep_fields = set(xt_config.get('export_episode_fields') or [])
    season_fields = set(xt_config.get('export_season_fields') or [])
    from app.routers.admin_tmdb import _norm_title_year, _sig_for

    policy = (xt_config.get('dedupe_policy') or 'm3u_order').strip()
    # Seleziona una sola variante per episodio in base alla policy
    ep_groups: Dict[str, M3UItem] = {}
    for it in items:
        trip = try_extract_tv_triplet(it.url)
        if not (guess_is_series(it) or trip):
            continue
        if not trip:
            continue
        sid, season, episode = trip
        k = f"{sid}:{season}:{episode}"
        prev = ep_groups.get(k)
        if not prev:
            ep_groups[k] = it
        else:
            if policy == 'random':
                # deterministico: scegli in base all'hash chiave
                idx = crc32_num(k) % 2
                ep_groups[k] = [prev, it][idx]
            else:
                def ordv(x: M3UItem) -> int:
                    o = x.source_order
                    try:
                        return int(o) if o is not None else 10**9
                    except Exception:
                        return 10**9
                # m3u_order / exclude_low: tieni la migliore priorità
                ep_groups[k] = prev if ordv(prev) <= ordv(it) else it

    for key, it in ep_groups.items():
        # Chiave nel formato "sid:season:episode" per evitare ambiguità di parse
        try:
            sid_str, season_str, episode_str = key.split(":", 2)
            sid = sid_str
            season = int(season_str)
            episode = int(episode_str)
        except Exception:
            # Fallback sicuro: prova a estrarre dalla URL; se fallisce, salta
            trip2 = try_extract_tv_triplet(it.url)
            if not trip2:
                continue
            sid, season, episode = trip2
        name = re.sub(r"\bS(\d{1,2})E(\d{1,2})\b", "", it.title, flags=re.I).strip() or f"Serie {sid}"
        cover = it.tvg_logo or ""
        plot = ""
        rating: Optional[float] = None
        seasons_data: Dict[int, Dict[str, Any]] = {}
        norm_title, _ = _norm_title_year(it.title, it.attrs or {})
        series_sig = _sig_for('series', norm_title, None)

        ep_code = f"S{season:02d}E{episode:02d}"
        ep_id = str(crc32_num(f"{sid}:{season}:{episode}"))
        ep_secs = _extract_duration(it.attrs)
        ep_plot = ""
        ep_name = ep_code
        ep_cover: Optional[str] = None
        ep_rating: Optional[float] = None
        ep_rating_5based: Optional[int] = None

        try:
            with db.SessionLocal() as s:
                mrow = s.get(db.TMDBMap, series_sig)
                if mrow:
                    series_row = s.get(db.TMDBSeries, (mrow.tmdb_id, lang))
                    if series_row:
                        if 'name' in sr_fields and (series_row.name or ''):
                            name = series_row.name
                        if 'poster' in sr_fields and (series_row.poster_path or ''):
                            cover = "https://image.tmdb.org/t/p/w500" + series_row.poster_path
                        if 'plot' in sr_fields and (series_row.overview or ''):
                            plot = series_row.overview
                        if 'rating' in sr_fields and series_row.rating is not None:
                            try:
                                rating = float(series_row.rating)
                            except Exception:
                                rating = None
                    if season_fields:
                        try:
                            ss = (
                                s.query(db.TMDBSeason)
                                .filter(
                                    db.TMDBSeason.tmdb_series_id == mrow.tmdb_id,
                                    db.TMDBSeason.language == lang,
                                )
                                .all()
                            )
                            for si in ss:
                                seasons_data[si.season_number] = {
                                    'season_number': si.season_number,
                                    'episode_count': si.episode_count,
                                    'name': si.name,
                                    'air_date': si.air_date,
                                    'poster_path': si.poster_path,
                                    'overview': si.overview,
                                    'backdrop_path': si.backdrop_path,
                                }
                        except Exception:
                            pass
                    if ep_fields:
                        need_ep = bool(ep_fields & {'duration', 'plot', 'name', 'poster', 'rating'})
                        if need_ep:
                            ep_row = (
                                s.query(db.TMDBEpisode)
                                .filter(
                                    db.TMDBEpisode.tmdb_series_id == mrow.tmdb_id,
                                    db.TMDBEpisode.language == lang,
                                    db.TMDBEpisode.season == season,
                                    db.TMDBEpisode.episode == episode,
                                )
                                .first()
                            )
                            if ep_row:
                                if 'duration' in ep_fields and ep_row.duration_mins:
                                    try:
                                        ep_secs = int(ep_row.duration_mins) * 60
                                    except Exception:
                                        pass
                                if 'plot' in ep_fields and ep_row.overview:
                                    ep_plot = ep_row.overview
                                if 'name' in ep_fields and ep_row.name:
                                    ep_name = ep_row.name
                                if 'poster' in ep_fields and ep_row.still_path:
                                    ep_cover = "https://image.tmdb.org/t/p/w500" + ep_row.still_path
                                if 'rating' in ep_fields and ep_row.vote_average is not None:
                                    try:
                                        ep_rating = float(ep_row.vote_average)
                                        ep_rating_5based = int(min(5, max(0, round(ep_rating / 2.0))))
                                    except Exception:
                                        ep_rating = None
                                        ep_rating_5based = 0
        except Exception:
            pass

        if ep_cover is None:
            ep_cover = cover
        if ep_rating is not None and ep_rating_5based is None:
            try:
                ep_rating_5based = int(min(5, max(0, round(ep_rating / 2.0))))
            except Exception:
                ep_rating_5based = 0

        cat_name = normalize_group_for_type(it.group or "Serie", "series")
        cat_id = get_category_id(cat_name, 3000)
        cat_map[cat_name] = cat_id
        s_series = series_map.setdefault(
            sid,
            {
                "series_id": sid,
                "name": name,
                "cover": cover,
                "plot": plot,
                "rating": rating,
                "category_id": cat_id,
                "episodes_by_season": defaultdict(list),
                "seasons": {},
                "category_name": cat_name,
            },
        )

        # Aggiorna i metadati della serie nel caso in cui esista già
        s_series["name"] = name
        s_series["cover"] = cover
        s_series["plot"] = plot
        s_series["rating"] = rating

        if season_fields and season in seasons_data:
            season_data = s_series['seasons'].setdefault(season, {})
            tmdb_season = seasons_data[season]
            if 'name' in season_fields and tmdb_season.get('name'):
                season_data['name'] = tmdb_season['name']
            if 'poster' in season_fields and tmdb_season.get('poster_path'):
                season_data['cover'] = "https://image.tmdb.org/t/p/w500" + tmdb_season['poster_path']
            if 'plot' in season_fields and tmdb_season.get('overview'):
                season_data['plot'] = tmdb_season['overview']
            if 'air_date' in season_fields and tmdb_season.get('air_date'):
                season_data['air_date'] = tmdb_season['air_date']

        s_series["episodes_by_season"][str(season)].append(
            {
                "id": ep_id,
                "title": ep_name,
                "episode_num": int(episode),
                "season": int(season),
                "container_extension": "mp4",
                "added": str(now_ts()),
                "info": {
                    "movie_image": ep_cover,
                    "plot": ep_plot,
                    "duration": str(ep_secs),
                    "duration_secs": str(ep_secs),
                    "duration_fmt": _fmt_hhmmss(ep_secs),
                    "rating": ep_rating,
                    "rating_5based": ep_rating_5based,
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

    live_streams, live_cats = build_live_streams(base_url, live_items, xt_config)
    vod_streams, vod_cats = build_vod_streams(base_url, movie_items, xt_config)
    series_map, series_cats = build_series_collections(base_url, series_items, xt_config)

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
def build_vod_info(base_url: str, vod_id: str, all_items: Iterable[M3UItem], xt_config: Dict[str, Any]) -> Dict[str, Any]:
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

    st = config.load_settings()
    tmdb_cfg = (st.get('tmdb') or {})
    lang = tmdb_cfg.get('language') or 'it-IT'
    mv_fields = set(xt_config.get('export_movie_fields') or [])

    title = chosen.title.strip()
    year = ""
    m = re.search(r"(19|20)\d{2}", title)
    if m:
        year = m.group(0)

    duration = _extract_duration(chosen.attrs)
    movie_image = chosen.tvg_logo or ""
    rating_val: Optional[float] = None
    plot = ""
    cast = ""
    director = ""
    genre = ""
    release_date = year

    # Get TMDB data
    try:
        with db.SessionLocal() as s:
            from app.routers.admin_tmdb import _norm_title_year, _sig_for
            t, y = _norm_title_year(chosen.title, chosen.attrs or {})
            sig = _sig_for('movie', t, y)
            mrow = s.get(db.TMDBMap, sig)
            if mrow:
                row = s.get(db.TMDBMovie, (mrow.tmdb_id, lang))
                if row:
                    if 'name' in mv_fields and (row.title or ''):
                        title = row.title
                    if 'poster' in mv_fields and (row.poster_path or ''):
                        movie_image = ("https://image.tmdb.org/t/p/w500" + row.poster_path)
                    if 'rating' in mv_fields and row.rating is not None:
                        rating_val = float(row.rating)
                    if 'duration' in mv_fields and row.runtime_mins:
                        duration = int(row.runtime_mins) * 60
                    if 'plot' in mv_fields and row.overview:
                        plot = row.overview
                    if 'cast' in mv_fields and row.cast:
                        cast = row.cast
                    if 'director' in mv_fields and row.director:
                        director = row.director
                    if 'genre' in mv_fields and (row.genres or ''):
                        genre = str(row.genres)
                    if 'releasedate' in mv_fields and row.release_date:
                        release_date = row.release_date
    except Exception:
        pass

    title_clean = re.sub(r"\s*\([^()]*\)\s*", " ", title).strip()
    title_clean = re.sub(r"\s+", " ", title_clean)
    final_name = f"{title_clean} ({year})" if year and not release_date else title_clean

    info = {
        "imdb_id": None,
        "movie_image": movie_image,
        "genre": genre,
        "plot": plot,
        "cast": cast,
        "director": director,
        "rating": rating_val,
        "releasedate": release_date,
        "duration_secs": str(duration),
        "duration": _fmt_hhmmss(duration),
        "bitrate": None,
        "kinopoisk_url": None,
        "episode_run_time": None,
        "youtube_trailer": None,
        "actors": None,
        "name": final_name,
        "name_o": final_name,
        "cover_big": movie_image,
        "description": plot,
        "age": None,
        "rating_mpaa": None,
        "rating_count_kinopoisk": 0,
        "country": None,
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
        "direct_source": make_direct_video(base_url, chosen.url),
    }
    return {"info": info, "movie_data": movie_data}
