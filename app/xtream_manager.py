# app/xtream_manager.py
from __future__ import annotations
import os
import re
import json
import zlib
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Iterable
from collections import defaultdict
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse

# ====== PATHS & ENV ======
APP_DIR = os.environ.get("APP_DIR", os.getcwd())
CONFIG_DIR = os.environ.get("CONFIG_DIR", os.path.join(APP_DIR, "config"))
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(APP_DIR, "app", "static"))

PLAYLISTS_JSON = os.path.join(CONFIG_DIR, "playlists.json")
XTREAMS_JSON   = os.path.join(CONFIG_DIR, "xtreams.json")
SETTINGS_JSON  = os.path.join(CONFIG_DIR, "settings.json")
PLAYLISTS_DIR  = os.path.join(CONFIG_DIR, "playlists")
CATEGORY_IDS_JSON = os.path.join(CONFIG_DIR, "category_ids.json")

os.makedirs(PLAYLISTS_DIR, exist_ok=True)

router = APIRouter()

# ====== SMALL UTILS ======
def now_ts() -> int:
    return int(time.time())

def load_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Lock to guard access to CATEGORY_IDS and its JSON file
CATEGORY_IDS_LOCK = threading.Lock()
with CATEGORY_IDS_LOCK:
    CATEGORY_IDS: Dict[str, str] = load_json(CATEGORY_IDS_JSON, {})

def crc32_num(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF

def enc(url: str) -> str:
    return urllib.parse.quote(url, safe="")

def read_settings() -> Dict[str, Any]:
    return load_json(SETTINGS_JSON, {})

def stream_resolver_base(request: Request) -> str:
    st = read_settings()
    base = (st.get("stream_resolver_url") or "").strip()
    if base:
        if not re.match(r"^https?://", base, re.I):
            base = "http://" + base
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")

# ====== M3U PARSER ======
M3U_LINE = re.compile(
    r'#EXTINF:(?P<duration>-?\d+)\s*(?P<attrs>(?:\s+[a-z0-9\-]+="[^"]*")*)\s*,\s*(?P<title>.*)$',
    re.IGNORECASE
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
                items.append(M3UItem(
                    title=title, url=line.strip(),
                    attrs=attrs, group=group, tvg_id=tvg_id, tvg_logo=tvg_logo, raw=""
                ))
                last_inf = None
    return items

# ====== MODELLO CONFIG XTREAM ======
def _xtreams() -> List[Dict[str, Any]]:
    return load_json(XTREAMS_JSON, [])

def _save_xtreams(items: List[Dict[str, Any]]):
    """Persist xtream configs merging with existing ones.

    Items are matched by their ``id``; when an item with the same id already
    exists on disk, values from ``items`` override the stored ones. This allows
    partial updates without having to load and rewrite the whole list
    externally.
    """
    existing = {x.get("id"): x for x in load_json(XTREAMS_JSON, [])}
    for it in items:
        iid = it.get("id")
        if not iid:
            continue
        if iid in existing:
            # override existing values
            existing[iid].update(it)
        else:
            existing[iid] = it
    save_json(XTREAMS_JSON, list(existing.values()))

# ====== ADMIN ENDPOINTS ======
@router.get("/admin/xtreams.json")
def admin_xtreams_list():
    return {"items": _xtreams()}

@router.post("/admin/xtreams")
def admin_xtreams_add(payload: Dict[str, Any]):
    it = {
        "id": f"xt_{hex(crc32_num((payload.get('name') or '') + str(now_ts())))[2:][:8]}",
        "name": payload.get("name") or "Xtream",
        "username": payload.get("username", "").strip(),
        "password": payload.get("password", "").strip(),
        "live_list_ids": payload.get("live_list_ids") or [],
        "movie_list_ids": payload.get("movie_list_ids") or [],
        "series_list_ids": payload.get("series_list_ids") or [],
        "mixed_list_ids": payload.get("mixed_list_ids") or [],
        "every_hours": int(payload.get("every_hours") or 12),
        "last_refresh": now_ts(),
    }
    items = _xtreams()
    items.append(it)
    _save_xtreams(items)
    return {"ok": True, "item": it}

@router.delete("/admin/xtreams/{xt_id}")
def admin_xtreams_delete(xt_id: str):
    items = [x for x in _xtreams() if x.get("id") != xt_id]
    _save_xtreams(items)
    return {"ok": True}

@router.post("/admin/xtreams/{xt_id}/update")
def admin_xtreams_update(xt_id: str, payload: Dict[str, Any]):
    items = _xtreams()
    found = None
    for x in items:
        if x.get("id") == xt_id:
            found = x
            break
    if not found:
        raise HTTPException(404, "Not Found")
    # simple scalar fields
    if "name" in payload:
        found["name"] = payload["name"]
    if "username" in payload:
        found["username"] = payload.get("username", "").strip()
    if "password" in payload:
        found["password"] = payload.get("password", "").strip()
    if "every_hours" in payload:
        try:
            ehours = int(payload["every_hours"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Invalid every_hours")
        found["every_hours"] = max(1, ehours)
    # lists of playlist ids
    for key in ("live_list_ids", "movie_list_ids", "series_list_ids", "mixed_list_ids"):
        if key in payload:
            val = payload[key]
            if not isinstance(val, list):
                raise HTTPException(400, f"{key} must be a list")
            found[key] = [str(x) for x in val]
    if payload.get("refresh"):
        found["last_refresh"] = now_ts()
    _save_xtreams(items)
    return {"ok": True, "item": found}

# ====== CARICAMENTO PLAYLISTS SALVATE ======
def _playlists_index() -> List[Dict[str, Any]]:
    return load_json(PLAYLISTS_JSON, [])

def _playlist_file(pl_id: str) -> str:
    return os.path.join(PLAYLISTS_DIR, f"{pl_id}.m3u")

def _read_playlist(pl_id: str) -> List[M3UItem]:
    path = _playlist_file(pl_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_m3u(f.read())
    except FileNotFoundError:
        return []

# ====== CLASSIFICAZIONE ======
MOVIE_RE = re.compile(r"/movie/(\d+)", re.I)
TV_RE    = re.compile(r"/(?:tv|series)/(\d+)/(?:season/)?(\d+)/(\d+)", re.I)
TV_RE_SHORT = re.compile(r"/(?:tv|series)/(\d+)/(\d+)/(\d+)", re.I)

def try_extract_movie_id(url: str) -> Optional[str]:
    m = MOVIE_RE.search(url)
    return m.group(1) if m else None

def try_extract_tv_triplet(url: str) -> Optional[Tuple[str, int, int]]:
    for rgx in (TV_RE, TV_RE_SHORT):
        m = rgx.search(url)
        if m:
            sid, season, episode = m.group(1), int(m.group(2)), int(m.group(3))
            return sid, season, episode
    return None

def guess_is_series(item: M3UItem) -> bool:
    if try_extract_tv_triplet(item.url): return True
    g = item.group.lower()
    t = item.title.lower()
    if "serie" in g or "series" in g or "stagione" in t or re.search(r"\bs\d{1,2}e\d{1,2}\b", t, re.I):
        return True
    return False

def guess_is_movie(item: M3UItem) -> bool:
    if try_extract_movie_id(item.url): return True
    g = item.group.lower()
    if "film" in g or "movie" in g:
        return True
    return False

# ====== CATEGORIE STABILI ======
def stable_category_id(name: str, base: int) -> str:
    return str(base + (crc32_num(name) % 8999))

def get_category_id(name: str, base: int) -> str:
    with CATEGORY_IDS_LOCK:
        cid = CATEGORY_IDS.get(name)
        if cid:
            return cid
        cid = stable_category_id(name, base)
        CATEGORY_IDS[name] = cid
        save_json(CATEGORY_IDS_JSON, CATEGORY_IDS)
        return cid

def normalize_group_for_type(group: str, typ: str) -> str:
    g = group.strip()
    if typ == "vod":
        g = re.sub(r"^(film|movies?)\s*-\s*", "", g, flags=re.I)
    elif typ == "series":
        g = re.sub(r"^(serietv|serie)\s*-\s*", "", g, flags=re.I)
    elif typ == "live":
        g = re.sub(r"^(live|tv)\s*-\s*", "", g, flags=re.I)
    return g or "Generale"

# ====== DIRECT SOURCE ======
def make_direct_video(request: Request, original_url: str) -> str:
    base = stream_resolver_base(request)
    return f"{base}/video?u={enc(original_url)}"

def make_direct_live(request: Request, original_url: str) -> str:
    base = stream_resolver_base(request)
    return f"{base}/tv?u={enc(original_url)}"

# ====== DURATE ======
def _extract_duration(attrs: Dict[str, str]) -> int:
    """Return a positive duration in seconds from playlist attributes.

    Several providers expose the duration using different attribute names; we
    try a few common ones and fall back to ``1`` when the value is missing or
    invalid.  Returning ``1`` avoids the ``-1`` placeholder that some clients
    interpret as "live" content.
    """

    for key in ("tvg-duration", "tvg-duration-secs", "duration", "duration_secs"):
        val = attrs.get(key) or ""
        if not val:
            continue
        try:
            secs = int(float(val))
            if secs > 0:
                return secs
        except ValueError:
            continue
    return 1

# ====== COSTRUZIONE STRUTTURE ======
def build_vod_streams(request: Request, m3us: Iterable[M3UItem]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    out: List[Dict[str, Any]] = []
    cat_map: Dict[str, str] = {}
    num = 1
    for it in m3us:
        if not (guess_is_movie(it) or try_extract_movie_id(it.url)):
            continue
        mid = try_extract_movie_id(it.url) or str(crc32_num(it.url))
        cat_name = normalize_group_for_type(it.group or "Film", "vod")
        cat_id = get_category_id(cat_name, 2000)
        cat_map[cat_name] = cat_id
        name = it.title.strip()
        stream_icon = it.tvg_logo or ""
        out.append({
            "num": num,
            "name": name,
            "stream_id": str(mid),
            "stream_type": "movie",
            "stream_icon": stream_icon,
            "rating": "",
            "added": "",
            "duration": str(_extract_duration(it.attrs)),
            "category_id": cat_id,
            "category_name": cat_name,
            "container_extension": "m3u8",
            "direct_source": make_direct_video(request, it.url)
        })
        num += 1
    return out, cat_map

def build_vod_info(request: Request, vod_id: str, all_items: Iterable[M3UItem]) -> Dict[str, Any]:
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

    return {
        "info": {
            "name": final_name,
            "movie_image": chosen.tvg_logo or "",
            "plot": "",
            "releasedate": year,
            "rating": "",
            "duration_secs": str(duration)
        }
    }

def build_series_collections(request: Request, items: Iterable[M3UItem]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    series_map: Dict[str, Dict[str, Any]] = {}
    cat_map: Dict[str, str] = {}

    for it in items:
        trip = try_extract_tv_triplet(it.url)
        if not (guess_is_series(it) or trip):
            continue
        if not trip:
            continue
        sid, season, episode = trip
        name = re.sub(r"\bS(\d{1,2})E(\d{1,2})\b", "", it.title, flags=re.I).strip() or f"Serie {sid}"
        cover = it.tvg_logo or ""
        cat_name = normalize_group_for_type(it.group or "Serie", "series")
        cat_id = get_category_id(cat_name, 3000)
        cat_map[cat_name] = cat_id

        s = series_map.setdefault(sid, {
            "series_id": sid,
            "name": name,
            "cover": cover,
            "plot": "",
            "rating": "",
            "category_id": cat_id,
            "episodes_by_season": defaultdict(list)
        })

        ep_code = f"S{season:02d}E{episode:02d}"
        ep_id = f"{sid}-{ep_code}"
        s["episodes_by_season"][str(season)].append({
            "id": ep_id,
            "title": ep_code,
            "container_extension": "m3u8",
            "info": {
                "movie_image": cover,
                "plot": "",
                "duration": str(_extract_duration(it.attrs))
            },
            "direct_source": make_direct_video(request, it.url)
        })

    # ordina gli episodi per numero all'interno di ogni stagione
    ep_re = re.compile(r"E(\d+)$", re.I)
    for sm in series_map.values():
        ordered: Dict[str, List[Dict[str, Any]]] = {}
        for season in sorted(sm["episodes_by_season"], key=lambda s: int(s)):
            eps = sm["episodes_by_season"][season]
            eps_sorted = sorted(
                eps,
                key=lambda e: int(ep_re.search(e["title"]).group(1)) if ep_re.search(e["title"]) else e["title"],
            )
            ordered[season] = eps_sorted
        sm["episodes_by_season"] = ordered

    return series_map, cat_map

def build_live_streams(request: Request, items: Iterable[M3UItem]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    out: List[Dict[str, Any]] = []
    cat_map: Dict[str, str] = {}
    num = 1
    for it in items:
        cat_name = normalize_group_for_type(it.group or "Live", "live")
        cat_id = get_category_id(cat_name, 1000)
        cat_map[cat_name] = cat_id
        token = ""
        try:
            p = urllib.parse.urlparse(it.url)
            token = p.path.strip("/").split("/")[-1] or ""
        except Exception:
            token = ""
        if not token or len(token) < 6:
            token = hex(crc32_num(it.url))[2:]
        stream_id = f"lv_{token[:16]}"

        out.append({
            "num": num,
            "name": it.title.strip(),
            "stream_type": "live",
            "stream_id": stream_id,
            "stream_icon": it.tvg_logo or "",
            "epg_channel_id": it.tvg_id or "",
            "category_id": cat_id,
            "category_name": cat_name,
            "added": "",
            "custom_sid": "",
            "container_extension": "m3u8",
            "direct_source": make_direct_live(request, it.url)
        })
        num += 1
    return out, cat_map

# ====== AUTH XTREAM ======
def require_xtream(xt_id: str, username: str, password: str) -> Dict[str, Any]:
    username = username.strip()
    password = password.strip()
    xs = _xtreams()
    for row in xs:
        if row.get("id") == xt_id and row.get("username") == username and row.get("password") == password:
            return row
    raise HTTPException(401, "Unauthorized")

# ====== HELPERS CARICAMENTO ======
def items_for_xtream_selection(sel_ids: List[str]) -> List[M3UItem]:
    items: List[M3UItem] = []
    for pid in sel_ids or []:
        items.extend(_read_playlist(pid))
    return items

# ====== XTREAM: PLAYER API ======
@router.get("/xtream/{xt_id}/player_api.php")
def xt_player_api(request: Request,
                  xt_id: str,
                  action: Optional[str] = None,
                  username: Optional[str] = None,
                  password: Optional[str] = None,
                  vod_id: Optional[str] = None,
                  series_id: Optional[str] = None):
    if not username or not password:
        raise HTTPException(401, "Unauthorized")
    xt = require_xtream(xt_id, username, password)

    live_items  = items_for_xtream_selection(xt.get("live_list_ids", []))
    movie_items = items_for_xtream_selection(xt.get("movie_list_ids", []) + xt.get("mixed_list_ids", []))
    series_items= items_for_xtream_selection(xt.get("series_list_ids", []) + xt.get("mixed_list_ids", []))

    if action is None:
        return {
            "user_info": {
                "auth": 1, "status": "Active",
                "username": username, "password": password, "active_cons": "1",
            },
            "server_info": {
                "url": str(request.base_url).rstrip("/"),
                "port": "",
                "https_port": "",
                "server_protocol": "http",
                "timezone": "UTC"
            }
        }

    if action == "get_live_categories":
        _, cat_map = build_live_streams(request, live_items)
        cats = [{"category_id": cid, "category_name": name} for name, cid in sorted(cat_map.items(), key=lambda x: x[1])]
        return cats

    if action == "get_live_streams":
        streams, _ = build_live_streams(request, live_items)
        return streams

    if action == "get_vod_categories":
        _, cat_map = build_vod_streams(request, movie_items)
        cats = [{"category_id": cid, "category_name": name} for name, cid in sorted(cat_map.items(), key=lambda x: x[1])]
        return cats

    if action == "get_vod_streams":
        streams, _ = build_vod_streams(request, movie_items)
        return streams

    if action == "get_vod_info":
        if not vod_id:
            raise HTTPException(400, "vod_id mancante")
        return build_vod_info(request, vod_id, movie_items)

    if action == "get_series_categories":
        series_map, cat_map = build_series_collections(request, series_items)
        cats = [{"category_id": cid, "category_name": name} for name, cid in sorted(cat_map.items(), key=lambda x: x[1])]
        return cats

    if action == "get_series":
        series_map, _ = build_series_collections(request, series_items)
        out = []
        for sid, s in series_map.items():
            out.append({
                "series_id": s["series_id"],
                "name": s["name"],
                "cover": s["cover"],
                "plot": s["plot"],
                "rating": s["rating"],
                "category_id": s["category_id"],
            })
        return out

    if action == "get_series_info":
        if not series_id:
            raise HTTPException(400, "series_id mancante")
        series_map, _ = build_series_collections(request, series_items)
        s = series_map.get(str(series_id))
        if not s:
            raise HTTPException(404, "Serie non trovata")
        info = {
            "name": s["name"],
            "cover": s["cover"],
            "plot": s["plot"],
            "rating": s["rating"],
            "releaseDate": "",
            "stream_type": "series",
            "series_id": s["series_id"]
        }
        return {
            "info": info,
            "episodes": s["episodes_by_season"],
            "seasons": []
        }

    raise HTTPException(400, f"action non supportata: {action}")

# ====== XTREAM: GET.PHP (playlist M3U) ======
@router.get("/xtream/{xt_id}/get.php")
def xt_get_php(request: Request,
               xt_id: str,
               username: Optional[str] = None,
               password: Optional[str] = None,
               playlist_type: str = "m3u",
               output: str = "ts"):
    if not username or not password:
        raise HTTPException(401, "Unauthorized")
    xt = require_xtream(xt_id, username, password)

    live_items  = items_for_xtream_selection(xt.get("live_list_ids", []))
    movie_items = items_for_xtream_selection(xt.get("movie_list_ids", []) + xt.get("mixed_list_ids", []))
    series_items= items_for_xtream_selection(xt.get("series_list_ids", []) + xt.get("mixed_list_ids", []))

    live_streams, _  = build_live_streams(request, live_items)
    vod_streams, _   = build_vod_streams(request, movie_items)
    series_map, _    = build_series_collections(request, series_items)

    lines = ["#EXTM3U"]

    for s in live_streams:
        name = s["name"]
        logo = s.get("stream_icon", "")
        grp  = s.get("category_name") or s.get("category_id", "")
        tvgid = s.get("epg_channel_id", "")
        url = s["direct_source"]
        lines.append(f'#EXTINF:-1 tvg-id="{tvgid}" tvg-logo="{logo}" group-title="{grp}",{name}')
        lines.append(url)

    for s in vod_streams:
        name = s["name"]
        logo = s.get("stream_icon", "")
        grp  = s.get("category_name") or s.get("category_id", "")
        url = s["direct_source"]
        dur = int(s.get("duration") or 0)
        lines.append(f'#EXTINF:{dur} tvg-logo="{logo}" group-title="{grp}",{name}')
        lines.append(url)

    for sid, sm in series_map.items():
        cover = sm["cover"]
        grp   = sm.get("category_name") or sm.get("category_id", "")
        for season, eps in sm["episodes_by_season"].items():
            for ep in eps:
                title = f'{sm["name"]} {ep["title"]}'
                url = ep["direct_source"]
                dur = int(ep.get("info", {}).get("duration") or 0)
                lines.append(f'#EXTINF:{dur} tvg-logo="{cover}" group-title="{grp}",{title}')
                lines.append(url)

    txt = "\n".join(lines) + "\n"
    return PlainTextResponse(txt, media_type="audio/mpegurl")

# ====== XTREAM WRAPPERS (disabilitati: 404 guidato) ======
@router.get("/xtream/{xt_id}/live/{u}/{p}/{stream_id}.{ext}")
def xt_live_redirect(request: Request, xt_id: str, u: str, p: str, stream_id: str, ext: str):
    raise HTTPException(404, "Stream mapping non abilitato (usa i link diretti della playlist)")

@router.get("/xtream/{xt_id}/movie/{u}/{p}/{stream_id}.{ext}")
def xt_movie_redirect(request: Request, xt_id: str, u: str, p: str, stream_id: str, ext: str):
    raise HTTPException(404, "Stream mapping non abilitato (usa i link diretti della playlist)")

@router.get("/xtream/{xt_id}/series/{u}/{p}/{series_id}/{season}/{episode}.{ext}")
def xt_series_redirect(request: Request, xt_id: str, u: str, p: str, series_id: str, season: int, episode: int, ext: str):
    raise HTTPException(404, "Stream mapping non abilitato (usa i link diretti della playlist)")

# ====== SHIM per compatibilità col tuo main.py ======
def setup_xtream(app):
    """Hook compatibile col vecchio main.py: include il router Xtream."""
    app.include_router(router)
