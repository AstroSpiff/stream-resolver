# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
import logging
from typing import Dict

from app import config
from app.services import m3u
from app.services.xtream import xtreams, get_xtream_cache_status, spawn_build, parse_m3u, guess_is_series, guess_is_movie, try_extract_movie_id, try_extract_tv_triplet, _extract_duration
from app import db

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 600  # 10 minuti

# Evita avvii doppi dei worker in ambienti con reloader/debug
_WORKERS_STARTED = False
_WORKERS_LOCK = threading.Lock()


def _refresh_playlist_sync(it: Dict, pid: str) -> None:
    try:
        import httpx as _httpx
        with _httpx.Client(follow_redirects=True, timeout=40.0, headers={"User-Agent": "StreamResolver/1.2 (+httpx)"}) as s:
            r = s.get(it["url"])  # può sollevare
            r.raise_for_status()
            src = r.text
        it["last_refresh"] = config.now_ts()
        try:
            parsed_items = parse_m3u(src)
            with db.SessionLocal() as s:
                # assicurati che la playlist esista
                p = s.get(db.Playlist, pid)
                if not p:
                    p = db.Playlist(id=pid, name=it.get('name') or '', url=it.get('url') or '', mode=it.get('mode') or 'film')
                    s.add(p)
                    s.flush()
                # cancella items precedenti
                s.query(db.PlaylistItem).filter(db.PlaylistItem.playlist_id == pid).delete(synchronize_session=False)
                # inserisci nuovi (NO dedupe: alcune voci condividono la stessa URL ma hanno metadati diversi)
                for mi in parsed_items:
                    u = (mi.url or '').strip()
                    if not u:
                        continue
                    # Classificazione e TV triplet
                    kind = 'live'
                    series_id = None; season = None; episode = None
                    tv_triplet = try_extract_tv_triplet(u)
                    if tv_triplet:
                        kind = 'episode'
                        series_id, season, episode = tv_triplet
                    elif guess_is_series(mi):
                        kind = 'series'
                    elif try_extract_movie_id(u) or guess_is_movie(mi):
                        kind = 'movie'
                    # Normalizza attributi
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
                    h = (special.get('headers') if isinstance(special, dict) else {}) or {}
                    lic = (special.get('license') if isinstance(special, dict) else {}) or {}
                    fmt = (special.get('format') if isinstance(special, dict) else None) or None
                    reqp = 1 if (isinstance(special, dict) and special.get('requires_proxy')) else 0
                    # Pulisci attrs dai campi mappati in colonne
                    cleaned_attrs = {}
                    try:
                        cleaned_attrs = dict(a)
                        for k in ['tvg-chno','tvg-id','tvg-name','group-title','radio','karaoke']:
                            if k in cleaned_attrs:
                                cleaned_attrs.pop(k, None)
                        sp = cleaned_attrs.get('special') if isinstance(cleaned_attrs.get('special'), dict) else None
                        if sp:
                            for sk in ['headers','license','format','requires_proxy']:
                                sp.pop(sk, None)
                            if not sp:
                                cleaned_attrs.pop('special', None)
                    except Exception:
                        cleaned_attrs = a or {}

                    # Duration: only for VOD/episodes; live should have empty duration
                    dur = None if kind == 'live' else _extract_duration(mi.attrs)
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
                        duration_secs=dur,
                        kind=kind,
                        series_id=series_id,
                        season=season,
                        episode=episode,
                    ))
                s.commit()
        except Exception:
            logger.exception("DB non raggiungibile o errore nella scrittura durante il refresh della playlist %s", pid)
        logger.info("✅ Playlist %s rigenerata correttamente", pid)
    except Exception:
        logger.exception("❌ Errore durante il refresh della playlist %s", pid)


def _periodic_cache_refresher():
    logger.info("✅ Avvio del worker di refresh automatico della cache Xtream.")
    while True:
        try:
            base_url_default = config.get_stream_resolver_base(None)

            logger.info("⚙️ Esecuzione controllo cache Xtream...")
            all_xtreams = xtreams()
            for xt in all_xtreams:
                status = get_xtream_cache_status(xt)
                if status == "scaduta":
                    logger.info(f"🔥 La cache per Xtream '{xt.get('name')}' (ID: {xt.get('id')}) è scaduta. Avvio rigenerazione...")
                    base_url = (xt.get('resolver_url') or '').strip() or base_url_default
                    spawn_build(base_url, xt)
                time.sleep(1)

        except Exception:
            logger.exception("❌ Errore critico nel worker di refresh della cache. Riprovo tra 10 minuti.")

        time.sleep(REFRESH_INTERVAL_SECONDS)


def _periodic_playlists_refresher():
    logger.info("✅ Avvio del worker di refresh automatico delle Playlist salvate.")
    while True:
        try:
            items = m3u.read_playlists_index()
            changed = False
            now = config.now_ts()
            for it in items:
                pid = it.get("id")
                url = (it.get("url") or "").strip()
                if not pid or not url or not url.lower().startswith(("http://", "https://")):
                    continue
                try:
                    every_hours = max(1, int(it.get("every_hours", 12) or 12))
                except Exception:
                    every_hours = 12
                last_refresh = int(it.get("last_refresh", 0) or 0)
                due = (now - last_refresh) > (every_hours * 3600)
                if due:
                    logger.info("⏳ Playlist %s scaduta (last=%s, every=%sh). Rigenero...", pid, last_refresh, every_hours)
                    _refresh_playlist_sync(it, pid)
                    changed = True
                    time.sleep(1)
            if changed:
                m3u.write_playlists_index(items)
        except Exception:
            logger.exception("❌ Errore critico nel worker di refresh playlist. Riprovo tra 10 minuti.")
        time.sleep(REFRESH_INTERVAL_SECONDS)


def start_workers():
    global _WORKERS_STARTED
    with _WORKERS_LOCK:
        if _WORKERS_STARTED:
            return
        _WORKERS_STARTED = True
        t1 = threading.Thread(target=_periodic_cache_refresher, daemon=True)
        t2 = threading.Thread(target=_periodic_playlists_refresher, daemon=True)
        t1.start()
        t2.start()
