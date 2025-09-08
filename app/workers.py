# -*- coding: utf-8 -*-
from __future__ import annotations

import os
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
        if config.get_storage_backend() != 'db':
            settings = config.load_settings()
            if it.get("resolver_url"):
                settings = {**settings, "resolvers": [{"name": "override", "url": it["resolver_url"]}]}
            out = m3u.convert_playlist_text(src, it["mode"], settings)
            out_path = os.path.join(config.PLAYLISTS_DIR, f"{pid}.m3u")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(out)
        it["last_refresh"] = config.now_ts()
        # Aggiorna anche il DB con gli items originali (se backend=db)
        if config.get_storage_backend() == 'db':
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
                    # inserisci nuovi (deduplica per URL)
                    seen_urls: set[str] = set()
                    for mi in parsed_items:
                        u = (mi.url or '').strip()
                        if not u or u in seen_urls:
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
                            duration_secs=_extract_duration(mi.attrs),
                            kind=kind,
                        ))
                    s.commit()
            except Exception:
                logger.exception("DB non raggiungibile o errore nella scrittura: salvo solo file .m3u")
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
