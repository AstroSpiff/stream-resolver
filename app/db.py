from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, String, Integer, ForeignKey, JSON, UniqueConstraint, text, inspect, func, Text, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy import select, delete

from app import config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# --- Models ---
class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2000))
    mode: Mapped[str] = mapped_column(String(16), default="film")
    every_hours: Mapped[int] = mapped_column(Integer, default=12)
    order_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolver_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_refresh: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[List["PlaylistItem"]] = relationship(back_populates="playlist", cascade="all, delete-orphan")


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), index=True)
    original_url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500), default="")
    group_title: Mapped[str] = mapped_column(String(200), default="")
    tvg_id: Mapped[str] = mapped_column(String(200), default="")
    tvg_logo: Mapped[str] = mapped_column(String(1000), default="")
    # Common M3U attributes normalized in columns (avoid JSON-only storage)
    tvg_chno: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tvg_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    radio: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0/1
    karaoke: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0/1
    # Per-item playback metadata (from KODIPROP/EXTVLCOPT)
    headers_user_agent: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    headers_referer: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    headers_origin: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    headers_cookie: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    license_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # eg. clearkey
    clearkey_kid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    clearkey_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stream_format: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # hls|dash
    requires_proxy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0/1
    attrs: Mapped[dict] = mapped_column(JSON, default={})
    duration_secs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="live")  # live|movie|series|episode
    series_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    season: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    playlist: Mapped[Playlist] = relationship(back_populates="items")
    __table_args__ = ()


class Xtream(Base):
    __tablename__ = "xtreams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(200))
    password: Mapped[str] = mapped_column(String(200))
    resolver_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    every_hours: Mapped[int] = mapped_column(Integer, default=12)
    last_refresh: Mapped[int] = mapped_column(Integer, default=0)
    links: Mapped[List["XtreamLink"]] = relationship(back_populates="xtream", cascade="all, delete-orphan")
    # Export field selections per type (JSON arrays of strings)
    export_live_fields: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    export_movie_fields: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    export_series_fields: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    export_season_fields: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    export_episode_fields: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    dedupe_policy: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # m3u_order|random|exclude_low


class XtreamLink(Base):
    __tablename__ = "xtream_playlist_links"
    xt_id: Mapped[str] = mapped_column(ForeignKey("xtreams.id", ondelete="CASCADE"), primary_key=True)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)  # live|film|series|mixed
    xtream: Mapped[Xtream] = relationship(back_populates="links")


# --- TMDB models and mappings ---
class TMDBMap(Base):
    __tablename__ = "tmdb_map"
    sig: Mapped[str] = mapped_column(String(256), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # movie|series
    tmdb_id: Mapped[int] = mapped_column(Integer)


class TMDBMovie(Base):
    __tablename__ = "tmdb_movies"
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    overview: Mapped[str] = mapped_column(Text, default="")
    poster_path: Mapped[str] = mapped_column(String(500), default="")
    backdrop_path: Mapped[str] = mapped_column(String(500), default="")
    rating: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    release_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    runtime_mins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    genres: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    cast: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    director: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tagline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    release_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    youtube_trailer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    production_companies: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    production_countries: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    writers: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    certification: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class TMDBSeries(Base):
    __tablename__ = "tmdb_series"
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    overview: Mapped[str] = mapped_column(Text, default="")
    poster_path: Mapped[str] = mapped_column(String(500), default="")
    backdrop_path: Mapped[str] = mapped_column(String(500), default="")
    rating: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    first_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode_run_time_mins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    genres: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    cast: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    original_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tagline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    first_air_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    networks: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    origin_country: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    youtube_trailer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class TMDBEpisode(Base):
    __tablename__ = "tmdb_episodes"
    episode_tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    tmdb_series_id: Mapped[int] = mapped_column(Integer)
    season: Mapped[int] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500), default="")
    overview: Mapped[str] = mapped_column(Text, default="")
    air_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    still_path: Mapped[str] = mapped_column(String(500), default="")
    duration_mins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guest_stars: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    crew: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    vote_average: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class TMDBSeason(Base):
    __tablename__ = "tmdb_seasons"
    season_tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    tmdb_series_id: Mapped[int] = mapped_column(Integer)
    season_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500), default="")
    overview: Mapped[str] = mapped_column(Text, default="")
    air_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    episode_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    poster_path: Mapped[str] = mapped_column(String(500), default="")
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class TMDBCollection(Base):
    __tablename__ = "tmdb_collections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    poster_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class TMDBCollectionMovie(Base):
    __tablename__ = "tmdb_collection_movies"
    collection_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class TMDBIngestStatus(Base):
    __tablename__ = "tmdb_ingest_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_type: Mapped[str] = mapped_column(String(16))  # movie|series|episode
    movie_sig: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    series_sig: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    season: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title_norm: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|processing|done|error
    first_seen_ts: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_ts: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_processed_ts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

class TMDBRegexRule(Base):
    __tablename__ = "tmdb_regex_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="Rule")
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    # Regex to match against the domain of the URL
    domain_regex: Mapped[str] = mapped_column(String(500))
    # Regex to extract the TMDB ID from the full URL (must have one capture group)
    extraction_regex: Mapped[str] = mapped_column(String(1000))
    # The media type of the ID being extracted
    media_type: Mapped[str] = mapped_column(String(16), default="movie") # movie|series


def _engine():
    url = config.get_database_url()
    eng = create_engine(url, pool_pre_ping=True, future=True)
    return eng


Engine = _engine()
SessionLocal = sessionmaker(bind=Engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def reset_engine():
    """Rebind global Engine/SessionLocal to current DATABASE_URL.
    Call after settings change to reflect new connection string.
    """
    global Engine, SessionLocal
    try:
        Engine.dispose()
    except Exception:
        pass
    Engine = _engine()
    try:
        SessionLocal.configure(bind=Engine)
    except Exception:
        # fallback rebuild if configure not available
        SessionLocal = sessionmaker(bind=Engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_db():
    """FastAPI dependency that yields a SQLAlchemy Session and ensures cleanup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:
            pass


def init_db():
    try:
        Base.metadata.create_all(Engine)
        logger.info("DB initialized and tables ensured.")
        _ensure_new_columns()
    except Exception:
        logger.exception("Failed to init DB")


def _ensure_new_columns():
    """Ensure newly added columns exist on existing databases (simple IF NOT EXISTS alters).
    This is a lightweight alternative to Alembic for incremental adoption.
    """
    # First, ensure critical columns via introspection to support DBs
    # that don't accept "IF NOT EXISTS" on ADD COLUMN (e.g., older Postgres/SQLite).
    try:
        with Engine.begin() as conn:
            insp = inspect(conn)
            def has_column(table: str, column: str) -> bool:
                try:
                    cols = insp.get_columns(table)
                except Exception:
                    return False
                return any(c.get('name') == column for c in cols)

            if not has_column('playlists', 'order_num'):
                try:
                    conn.execute(text("ALTER TABLE playlists ADD COLUMN order_num INTEGER"))
                except Exception:
                    # Non-fatal: another concurrent migrator may have added it
                    pass
            if not has_column('xtreams', 'dedupe_policy'):
                try:
                    conn.execute(text("ALTER TABLE xtreams ADD COLUMN dedupe_policy VARCHAR(32)"))
                except Exception:
                    # Non-fatal: another concurrent migrator may have added it
                    pass
            # Ensure newly introduced playlist_items columns exist
            def add_col_if_missing(table: str, col: str, ddl: str):
                if not has_column(table, col):
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                    except Exception:
                        pass
            add_col_if_missing('playlist_items', 'tvg_chno', 'tvg_chno INTEGER')
            add_col_if_missing('playlist_items', 'tvg_name', 'tvg_name VARCHAR(500)')
            add_col_if_missing('playlist_items', 'radio', 'radio INTEGER')
            add_col_if_missing('playlist_items', 'karaoke', 'karaoke INTEGER')
            add_col_if_missing('playlist_items', 'headers_user_agent', 'headers_user_agent VARCHAR(1000)')
            add_col_if_missing('playlist_items', 'headers_referer', 'headers_referer VARCHAR(1000)')
            add_col_if_missing('playlist_items', 'headers_origin', 'headers_origin VARCHAR(1000)')
            add_col_if_missing('playlist_items', 'headers_cookie', 'headers_cookie VARCHAR(2000)')
            add_col_if_missing('playlist_items', 'license_type', 'license_type VARCHAR(32)')
            add_col_if_missing('playlist_items', 'clearkey_kid', 'clearkey_kid VARCHAR(128)')
            add_col_if_missing('playlist_items', 'clearkey_key', 'clearkey_key VARCHAR(128)')
            add_col_if_missing('playlist_items', 'stream_format', 'stream_format VARCHAR(16)')
            add_col_if_missing('playlist_items', 'requires_proxy', 'requires_proxy INTEGER')
            # Drop legacy unique constraint on (playlist_id, original_url) to allow multiple entries per URL
            try:
                conn.execute(text("ALTER TABLE playlist_items DROP CONSTRAINT IF EXISTS uq_pl_url"))
            except Exception:
                # SQLite doesn't support dropping constraints this way; ignore
                pass
    except Exception:
        logger.exception("Failed ensuring critical columns")

    stmts = [
        # PlaylistItem normalized columns from M3U attributes and playback metadata
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS tvg_chno INTEGER",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS tvg_name VARCHAR(500)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS radio INTEGER",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS karaoke INTEGER",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS headers_user_agent VARCHAR(1000)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS headers_referer VARCHAR(1000)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS headers_origin VARCHAR(1000)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS headers_cookie VARCHAR(2000)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS license_type VARCHAR(32)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS clearkey_kid VARCHAR(128)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS clearkey_key VARCHAR(128)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS stream_format VARCHAR(16)",
        "ALTER TABLE playlist_items ADD COLUMN IF NOT EXISTS requires_proxy INTEGER",
        # Widen TMDB overviews to TEXT to avoid truncation in Postgres
        "ALTER TABLE tmdb_movies ALTER COLUMN overview TYPE TEXT",
        "ALTER TABLE tmdb_series ALTER COLUMN overview TYPE TEXT",
        "ALTER TABLE tmdb_seasons ALTER COLUMN overview TYPE TEXT",
        "ALTER TABLE tmdb_episodes ALTER COLUMN overview TYPE TEXT",
        # Ensure vote_average uses floating type
        "ALTER TABLE tmdb_episodes ALTER COLUMN vote_average TYPE DOUBLE PRECISION",
        # Xtream export fields
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_live_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_movie_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_series_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_season_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_episode_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS dedupe_policy VARCHAR(32)",
        # Playlist ordering
        "ALTER TABLE playlists ADD COLUMN IF NOT EXISTS order_num INTEGER",
        # TMDB movies extended fields
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS rating_votes",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS countries",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS original_language",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS status",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS images",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS keywords",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS spoken_languages",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS revenue",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS budget",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS popularity",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS original_title VARCHAR(500)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS tagline VARCHAR(500)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS release_date VARCHAR(20)",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS collection",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS youtube_trailer VARCHAR(64)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS logo_path VARCHAR(500)",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS production_companies",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS production_companies VARCHAR(2000)",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS production_countries",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS production_countries VARCHAR(2000)",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS writers",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS writers VARCHAR(2000)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS certification VARCHAR(16)",
        # TMDB series extended fields
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS rating_votes",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS countries",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS seasons_count",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS episodes_count",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS original_language",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS last_air_date",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS in_production",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS images",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS keywords",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS type",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS last_episode",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS next_episode",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS original_name VARCHAR(500)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS tagline VARCHAR(500)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS first_air_date VARCHAR(20)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS status VARCHAR(64)",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS created_by",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS created_by VARCHAR(2000)",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS networks",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS networks VARCHAR(2000)",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS origin_country",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS origin_country VARCHAR(200)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS youtube_trailer VARCHAR(64)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS logo_path VARCHAR(500)",
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS seasons_json",
        # Genres as CSV string
        "ALTER TABLE tmdb_series DROP COLUMN IF EXISTS genres",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS genres VARCHAR(2000)",
        "ALTER TABLE tmdb_movies DROP COLUMN IF EXISTS genres",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS genres VARCHAR(2000)",
        # TMDB episode extended fields
        "ALTER TABLE tmdb_episodes DROP COLUMN IF EXISTS production_code",
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS crew JSON",
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS vote_average DOUBLE PRECISION",
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS imdb_id VARCHAR(32)",
        # Add name to TMDBRegexRule if it doesn't exist
        "ALTER TABLE tmdb_regex_rules ADD COLUMN IF NOT EXISTS name VARCHAR(200) DEFAULT 'Rule'",
        # New tables for TMDB collections
        "CREATE TABLE IF NOT EXISTS tmdb_collections (\n            id INTEGER PRIMARY KEY,\n            name VARCHAR(500) DEFAULT '',\n            poster_path VARCHAR(500),\n            backdrop_path VARCHAR(500)\n        )",
        "CREATE TABLE IF NOT EXISTS tmdb_collection_movies (\n            collection_id INTEGER NOT NULL,\n            movie_tmdb_id INTEGER NOT NULL,\n            PRIMARY KEY (collection_id, movie_tmdb_id)\n        )",
        # Ingest status table and indexes
        "CREATE TABLE IF NOT EXISTS tmdb_ingest_status (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            key_type VARCHAR(16) NOT NULL,\n            movie_sig VARCHAR(256),\n            series_sig VARCHAR(256),\n            season INTEGER,\n            episode INTEGER,\n            title_norm VARCHAR(500),\n            year INTEGER,\n            tmdb_id INTEGER,\n            status VARCHAR(16) DEFAULT 'pending',\n            first_seen_ts INTEGER DEFAULT 0,\n            last_seen_ts INTEGER DEFAULT 0,\n            last_processed_ts INTEGER,\n            retries INTEGER DEFAULT 0,\n            last_error VARCHAR(1000)\n        )",
        "CREATE INDEX IF NOT EXISTS idx_ingest_status_status ON tmdb_ingest_status(status)",
        "CREATE INDEX IF NOT EXISTS idx_ingest_status_movie_sig ON tmdb_ingest_status(movie_sig)",
        "CREATE INDEX IF NOT EXISTS idx_ingest_status_series_sig ON tmdb_ingest_status(series_sig)",
    ]
    try:
        with Engine.begin() as conn:
            for sql in stmts:
                try:
                    conn.execute(text(sql))
                except Exception:
                    # Non-fatal: skip if table not present yet or column exists
                    pass
    except Exception:
        logger.exception("Failed ensuring new columns")


# --- Helper repository functions (minimal) ---
def list_playlists(session: Session) -> List[Dict]:
    rows = (
        session.query(Playlist)
        .order_by(Playlist.order_num.is_(None), Playlist.order_num.asc(), Playlist.name.asc())
        .all()
    )
    out: List[Dict] = []
    for p in rows:
        out.append({
            "id": p.id,
            "name": p.name,
            "url": p.url,
            "mode": p.mode,
            "every_hours": p.every_hours,
            "order_num": p.order_num or 0,
            "resolver_url": p.resolver_url or "",
            "last_refresh": p.last_refresh or 0,
        })
    return out


def upsert_playlists(session: Session, items: List[Dict]):
    keep_ids = set()
    for it in items:
        pid = it.get("id")
        if not pid:
            continue
        keep_ids.add(pid)
        row = session.get(Playlist, pid)
        if not row:
            # assign default order at the end
            try:
                max_ord = session.query(func.max(Playlist.order_num)).scalar() or 0
            except Exception:
                max_ord = 0
            row = Playlist(id=pid, name=it.get("name") or "", url=it.get("url") or "", order_num=(max_ord + 1))
            session.add(row)
        row.name = it.get("name") or row.name
        row.url = it.get("url") or row.url
        row.mode = it.get("mode") or row.mode
        row.every_hours = int(it.get("every_hours") or row.every_hours or 12)
        if it.get("order_num") is not None:
            try:
                row.order_num = int(it.get("order_num") or 0) or None
            except Exception:
                pass
        row.resolver_url = it.get("resolver_url") or ""
        row.last_refresh = int(it.get("last_refresh") or row.last_refresh or 0)
    # delete rows not present
    if keep_ids:
        session.query(Playlist).filter(~Playlist.id.in_(keep_ids)).delete(synchronize_session=False)


def list_xtreams(session: Session) -> List[Dict]:
    xs = session.query(Xtream).all()
    out: List[Dict] = []
    for x in xs:
        # raccogli links per ruolo
        links = session.execute(select(XtreamLink).where(XtreamLink.xt_id == x.id)).scalars().all()
        live = [l.playlist_id for l in links if l.role == 'live']
        movie = [l.playlist_id for l in links if l.role == 'film']
        series = [l.playlist_id for l in links if l.role == 'series']
        mixed = [l.playlist_id for l in links if l.role == 'mixed']
        out.append({
            "id": x.id,
            "name": x.name,
            "username": x.username,
            "password": x.password,
            "resolver_url": x.resolver_url or "",
            "every_hours": x.every_hours,
            "last_refresh": x.last_refresh,
            "dedupe_policy": x.dedupe_policy or "m3u_order",
            "live_list_ids": live,
            "movie_list_ids": movie,
            "series_list_ids": series,
            "mixed_list_ids": mixed,
            "export_live_fields": x.export_live_fields or [],
            "export_movie_fields": x.export_movie_fields or [],
            "export_series_fields": x.export_series_fields or [],
            "export_season_fields": x.export_season_fields or [],
            "export_episode_fields": x.export_episode_fields or [],
        })
    return out


def upsert_xtreams(session: Session, items: List[Dict]):
    keep_ids = set()
    for it in items:
        xid = it.get("id")
        if not xid:
            continue
        keep_ids.add(xid)
        row = session.get(Xtream, xid)
        if not row:
            row = Xtream(id=xid, name=it.get("name") or "Xtream", username=it.get("username") or "", password=it.get("password") or "")
            session.add(row)
        row.name = it.get("name") or row.name
        row.username = it.get("username") or row.username
        row.password = it.get("password") or row.password
        row.resolver_url = it.get("resolver_url") or row.resolver_url
        row.every_hours = int(it.get("every_hours") or row.every_hours or 12)
        row.last_refresh = int(it.get("last_refresh") or row.last_refresh or 0)
        # optional export field selections (JSON lists)
        if "export_live_fields" in it:
            row.export_live_fields = it.get("export_live_fields") or []
        if "export_movie_fields" in it:
            row.export_movie_fields = it.get("export_movie_fields") or []
        if "export_series_fields" in it:
            row.export_series_fields = it.get("export_series_fields") or []
        if "export_season_fields" in it:
            row.export_season_fields = it.get("export_season_fields") or []
        if "export_episode_fields" in it:
            row.export_episode_fields = it.get("export_episode_fields") or []
    if keep_ids:
        session.query(Xtream).filter(~Xtream.id.in_(keep_ids)).delete(synchronize_session=False)


def set_xtream_links(session: Session, xt_id: str, live_ids: List[str], movie_ids: List[str], series_ids: List[str], mixed_ids: List[str]):
    # pulisci esistenti
    session.execute(delete(XtreamLink).where(XtreamLink.xt_id == xt_id))
    def add_many(ids, role):
        for pid in (ids or []):
            session.add(XtreamLink(xt_id=xt_id, playlist_id=str(pid), role=role))
    add_many(live_ids, 'live')
    add_many(movie_ids, 'film')
    add_many(series_ids, 'series')
    add_many(mixed_ids, 'mixed')


def delete_xtream(session: Session, xt_id: str):
    session.query(Xtream).filter(Xtream.id == xt_id).delete(synchronize_session=False)
