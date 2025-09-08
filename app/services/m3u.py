# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import httpx

from app.config import (
    PLAYLISTS_DIR,
    PLAYLISTS_INDEX,
    ensure_http,
    load_settings,
    get_stream_resolver_base,
    read_json,
    write_json,
    url_encode,
)
from app import config
from app import db
from sqlalchemy.exc import OperationalError
from app.services.xtream import (
    try_extract_movie_id,
    try_extract_tv_triplet,
)

M3U_HEADER_RE = re.compile(r"^#EXTM3U", re.IGNORECASE)


def resolver_link_for(url: str, settings: Dict[str, str], mode: str) -> str:
    # Prefer resolvers preset from provided settings, else global default preset
    base = ""
    try:
        presets = settings.get("resolvers") or []
        if isinstance(presets, list) and presets:
            base = ensure_http((presets[0].get("url") or "").strip())
    except Exception:
        base = ""
    if not base:
        base = get_stream_resolver_base(None)
    if not base:
        return url
    endpoint = "tv" if (mode or "").lower() in ("tv", "live") else "video"
    return f"{base.rstrip('/')}/{endpoint}?u={url_encode(url)}"


def _norm_mode(mode: str) -> str:
    m = (mode or "").strip().lower()
    if m in ("tv", "live"): return "live"
    if m in ("video", "vod", "film", "movie"): return "film"
    if m in ("series", "serie", "serietv"): return "series"
    if m in ("mixed", "misto", "mix"): return "mixed"
    return "film"


def convert_playlist_text(src_text: str, mode: str, settings: Dict[str, str]) -> str:
    lines = src_text.splitlines()
    out: List[str] = []
    saw_header = False
    seen_urls: set[str] = set()
    pending_extinf: Optional[str] = None
    mode = _norm_mode(mode)
    s_re = re.compile(r"\bS\d{1,2}E\d{1,2}\b", re.I)
    for line in lines:
        stripped = line.strip()
        if not saw_header and M3U_HEADER_RE.match(stripped):
            saw_header = True
        if stripped.startswith("#EXTINF"):
            if mode in ("film", "series"):
                line = re.sub(r'\s*group-title="[^"]*"', "", line)
            pending_extinf = line
            continue
        if stripped.startswith("#"):
            if mode in ("film", "series") and not stripped.startswith("#EXT"):
                continue
            out.append(line)
            continue
        if stripped.lower().startswith(("http://", "https://")):
            if stripped in seen_urls:
                pending_extinf = None
                continue
            seen_urls.add(stripped)
            # Decide endpoint
            item_mode = mode
            if mode == "mixed":
                ext = (pending_extinf or "").lower()
                is_series = bool(try_extract_tv_triplet(stripped)) or bool(s_re.search(ext)) or ("serie" in ext or "series" in ext or "stagione" in ext)
                is_movie = bool(try_extract_movie_id(stripped)) or ("film" in ext or "movie" in ext)
                item_mode = "live" if not (is_series or is_movie) else "film"  # series e film su /video
            # Output
            if pending_extinf is not None:
                out.append(pending_extinf)
            out.append(resolver_link_for(stripped, settings, item_mode))
            pending_extinf = None
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
        headers={"User-Agent": "StreamResolver/1.2 (+httpx)"},
    ) as s:
        r = await s.get(url)
        r.raise_for_status()
        return r.text


def read_playlists_index() -> List[Dict]:
    with db.SessionLocal() as s:
        return db.list_playlists(s)


def write_playlists_index(items: List[Dict]) -> None:
    with db.SessionLocal() as s:
        db.upsert_playlists(s, items)
        s.commit()


def find_playlist(items: List[Dict], pid: str) -> Optional[Dict]:
    for it in items:
        if it.get("id") == pid:
            return it
    return None
