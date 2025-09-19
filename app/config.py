# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Directories
APP_DIR = os.environ.get("APP_DIR", "/app")
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(APP_DIR, "app", "static"))
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/app/config")
USER_RESOLVERS_DIR = os.path.join(CONFIG_DIR, "resolvers")
XTREAMS_JSON = os.path.join(CONFIG_DIR, "xtreams.json")
XTREAM_CACHE_DIR = os.path.join(CONFIG_DIR, "xtream_cache")
CATEGORY_IDS_JSON = os.path.join(CONFIG_DIR, "category_ids.json")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(XTREAM_CACHE_DIR, exist_ok=True)
os.makedirs(USER_RESOLVERS_DIR, exist_ok=True)

# Files
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "mediaflow_url": "",
    "api_password": "",
    "stream_resolver_url": "",
    # Nuove strutture multi-preset
    "mediaflows": [],  # [{name,url,api_password}]
    "resolvers": [],   # [{name,url}]
    # Storage/TMDB
    "storage_backend": "db",  # fixed to db
    "database_url": "",         # legacy compat; preferire db_profiles
    "db_profiles": [],           # [{name,url}]
    "active_db": "default",
    "tmdb": { "api_key": "", "language": "it-IT", "movie_fields": [], "series_fields": [], "season_fields": [], "episode_fields": [], "tmdb_id_extractors": [] },
}


def now_ts() -> int:
    return int(time.time())


def read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # no stacktrace for common case
        return default
    except Exception:
        logger.exception("Error reading JSON from %s", path)
        return default


def write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        logger.exception("Error writing JSON to %s", path)


def ensure_http(url_or_host: str) -> str:
    u = (url_or_host or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "http://" + u


def url_encode(u: str) -> str:
    import urllib.parse
    return urllib.parse.quote(u, safe="")


def load_settings() -> Dict[str, Any]:
    s1 = read_json(SETTINGS_FILE, {})
    st: Dict[str, Any] = {**DEFAULT_SETTINGS, **s1}
    # Migrazione: se esistono i campi legacy, crea i preset se mancanti
    if st.get("mediaflow_url") and not st.get("mediaflows"):
        st["mediaflows"] = [{
            "name": "default",
            "url": st.get("mediaflow_url"),
            "api_password": st.get("api_password", ""),
        }]
    if st.get("stream_resolver_url") and not st.get("resolvers"):
        st["resolvers"] = [{
            "name": "default",
            "url": st.get("stream_resolver_url"),
        }]
    # Migrazione DB profiles: se non presenti ma c'è database_url, crea profilo default
    dbps = st.get("db_profiles") or []
    if (not dbps) and (st.get("database_url") or "").strip():
        dbps = [{"name": "default", "url": (st.get("database_url") or "").strip()}]
        st["db_profiles"] = dbps
        st["active_db"] = "default"
    return st


def save_settings(data: Dict[str, Any]) -> None:
    """Persist only preset arrays; stop writing legacy fields.

    The legacy keys (mediaflow_url, api_password, stream_resolver_url) are no longer
    written to disk. Callers should use get_mediaflow_preset/get_stream_resolver_base
    to read effective values.
    """
    # Se DATABASE_URL è impostato via env, non permettere modifiche da UI
    if os.environ.get("DATABASE_URL", "").strip():
        # Rimuovi i campi relativi al DB dal payload in arrivo
        data.pop("database_url", None)
        data.pop("db_profiles", None)
        data.pop("active_db", None)
        
    st = load_settings()
    out: Dict[str, Any] = {}
    # Preserve arrays, falling back to current ones if not provided
    out["mediaflows"] = data.get("mediaflows") if isinstance(data.get("mediaflows"), list) else (st.get("mediaflows") or [])
    out["resolvers"] = data.get("resolvers") if isinstance(data.get("resolvers"), list) else (st.get("resolvers") or [])
    # Persist optional fields for DB/TMDB
    out["storage_backend"] = "db"
    out["database_url"] = data.get("database_url") or load_settings().get("database_url") or ""
    tmdb_in = data.get("tmdb") or {}
    cur_tmdb = (load_settings().get("tmdb") or {})
    # Mantieni liste vuote se fornite esplicitamente; fallback solo se chiave assente
    if isinstance(tmdb_in, dict):
        if "movie_fields" in tmdb_in:
            movie_fields = tmdb_in.get("movie_fields") or []
        else:
            movie_fields = cur_tmdb.get("movie_fields") or []
        if "series_fields" in tmdb_in:
            series_fields = tmdb_in.get("series_fields") or []
        else:
            series_fields = cur_tmdb.get("series_fields") or []
        if "season_fields" in tmdb_in:
            season_fields = tmdb_in.get("season_fields") or []
        else:
            season_fields = cur_tmdb.get("season_fields") or []
        if "episode_fields" in tmdb_in:
            episode_fields = tmdb_in.get("episode_fields") or []
        else:
            episode_fields = (cur_tmdb.get("episode_fields") or [])
    else:
        movie_fields = cur_tmdb.get("movie_fields") or []
        series_fields = cur_tmdb.get("series_fields") or []
        season_fields = cur_tmdb.get("season_fields") or []
        episode_fields = cur_tmdb.get("episode_fields") or []
    out["tmdb"] = {
        "api_key": (tmdb_in.get("api_key") if isinstance(tmdb_in, dict) else None) or cur_tmdb.get("api_key") or "",
        "language": (tmdb_in.get("language") if isinstance(tmdb_in, dict) else None) or cur_tmdb.get("language") or "it-IT",
        "movie_fields": movie_fields,
        "series_fields": series_fields,
        "season_fields": season_fields,
        "episode_fields": episode_fields,
        "tmdb_id_extractors": (tmdb_in.get("tmdb_id_extractors") if isinstance(tmdb_in.get("tmdb_id_extractors"), list) else cur_tmdb.get("tmdb_id_extractors") or []),
    }
    # Forza backend a DB
    out["storage_backend"] = "db"
    if data.get("database_url") is not None:
        out["database_url"] = (data.get("database_url") or "").strip()
    else:
        out["database_url"] = st.get("database_url") or ""
    # Salva database_url legacy
    if data.get("database_url") is not None:
        out["database_url"] = (data.get("database_url") or "").strip()
    else:
        out["database_url"] = st.get("database_url") or ""
    # db_profiles / active_db
    if isinstance(data.get("db_profiles"), list):
        cleaned=[]
        for it in data.get("db_profiles"):
            if isinstance(it, dict):
                name=(it.get("name") or "").strip(); url=(it.get("url") or "").strip()
                if name and url: cleaned.append({"name":name, "url":url})
        out["db_profiles"]=cleaned
    else:
        out["db_profiles"]=st.get("db_profiles") or []
    if isinstance(data.get("active_db"), str) and data.get("active_db"):
        out["active_db"]=data.get("active_db")
    else:
        out["active_db"]=st.get("active_db") or "default"
    write_json(SETTINGS_FILE, out)


def get_storage_backend() -> str:
    # backend fisso: database
    return "db"


def get_database_url() -> str:
    env = os.environ.get("DATABASE_URL", "").strip()
    if env:
        return env
    st = load_settings()
    profiles = st.get("db_profiles") or []
    active = (st.get("active_db") or "").strip()
    if profiles and active:
        for it in profiles:
            if (it.get("name") or "") == active:
                url=(it.get("url") or "").strip()
                if url: return url
    if st.get("database_url"):
        return st["database_url"].strip()
    # Default locale: prova host Docker "db", altrimenti localhost
    try:
        import socket
        socket.getaddrinfo("db", 5432)
        host = "db"
    except Exception:
        host = "127.0.0.1"
    return f"postgresql+psycopg://resolver:resolver@{host}:5432/streamresolver"


def get_mediaflow_preset(name: Optional[str] = None) -> Tuple[str, str]:
    st = load_settings()
    arr = st.get("mediaflows") or []
    if name:
        for it in arr:
            if (it.get("name") or "") == name:
                return ensure_http((it.get("url") or "").rstrip("/")), (it.get("api_password") or "")
    if arr:
        it = arr[0]
        return ensure_http((it.get("url") or "").rstrip("/")), (it.get("api_password") or "")
    # fallback legacy
    return ensure_http((st.get("mediaflow_url") or "").rstrip("/")), (st.get("api_password") or "")


def get_stream_resolver_base(name: Optional[str] = None) -> str:
    st = load_settings()
    arr = st.get("resolvers") or []
    if name:
        for it in arr:
            if (it.get("name") or "") == name:
                return ensure_http(it.get("url") or "")
    if arr:
        return ensure_http(arr[0].get("url") or "")
    return ensure_http(st.get("stream_resolver_url") or "")
