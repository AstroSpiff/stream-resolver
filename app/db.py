from __future__ import annotations

import logging
from typing import Optional, List, Dict

from sqlalchemy import create_engine, String, Integer, ForeignKey, JSON, UniqueConstraint, text
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
    attrs: Mapped[dict] = mapped_column(JSON, default={})
    duration_secs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="live")  # live|movie|series|episode
    series_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    season: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    playlist: Mapped[Playlist] = relationship(back_populates="items")
    __table_args__ = (
        UniqueConstraint("playlist_id", "original_url", name="uq_pl_url"),
    )


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
    overview: Mapped[str] = mapped_column(String(4000), default="")
    poster_path: Mapped[str] = mapped_column(String(500), default="")
    backdrop_path: Mapped[str] = mapped_column(String(500), default="")
    rating: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    rating_votes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    release_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    runtime_mins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    genres: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    countries: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cast: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    director: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    tagline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    release_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    collection: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    youtube_trailer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    images: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    production_companies: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    production_countries: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    keywords: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    spoken_languages: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    writers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    revenue: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    budget: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    popularity: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    certification: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class TMDBSeries(Base):
    __tablename__ = "tmdb_series"
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    overview: Mapped[str] = mapped_column(String(4000), default="")
    poster_path: Mapped[str] = mapped_column(String(500), default="")
    backdrop_path: Mapped[str] = mapped_column(String(500), default="")
    rating: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    rating_votes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode_run_time_mins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    genres: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    countries: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cast: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    seasons_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episodes_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    original_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    tagline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    first_air_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_air_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    in_production: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    networks: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    origin_country: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    youtube_trailer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    images: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    keywords: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    seasons_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_episode: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    next_episode: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class TMDBEpisode(Base):
    __tablename__ = "tmdb_episodes"
    episode_tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    tmdb_series_id: Mapped[int] = mapped_column(Integer)
    season: Mapped[int] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500), default="")
    overview: Mapped[str] = mapped_column(String(4000), default="")
    air_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    still_path: Mapped[str] = mapped_column(String(500), default="")
    duration_mins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guest_stars: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    production_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    crew: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    vote_average: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)


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
    stmts = [
        # Xtream export fields
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_live_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_movie_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_series_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_season_fields JSON",
        "ALTER TABLE xtreams ADD COLUMN IF NOT EXISTS export_episode_fields JSON",
        # TMDB movies extended fields
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS original_title VARCHAR(500)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS original_language VARCHAR(16)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS tagline VARCHAR(500)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS release_date VARCHAR(20)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS status VARCHAR(64)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS collection JSON",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS youtube_trailer VARCHAR(64)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS images JSON",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS logo_path VARCHAR(500)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS production_companies JSON",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS production_countries JSON",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS keywords JSON",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS spoken_languages JSON",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS revenue INTEGER",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS budget INTEGER",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS popularity DOUBLE PRECISION",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS certification VARCHAR(16)",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS rating_votes INTEGER",
        "ALTER TABLE tmdb_movies ADD COLUMN IF NOT EXISTS writers JSON",
        # TMDB series extended fields
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS original_name VARCHAR(500)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS original_language VARCHAR(16)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS tagline VARCHAR(500)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS first_air_date VARCHAR(20)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS last_air_date VARCHAR(20)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS status VARCHAR(64)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS in_production INTEGER",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS created_by JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS networks JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS origin_country JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS youtube_trailer VARCHAR(64)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS images JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS logo_path VARCHAR(500)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS keywords JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS seasons_json JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS type VARCHAR(64)",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS last_episode JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS next_episode JSON",
        "ALTER TABLE tmdb_series ADD COLUMN IF NOT EXISTS rating_votes INTEGER",
        # TMDB episode extended fields
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS production_code VARCHAR(64)",
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS crew JSON",
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS vote_average DOUBLE PRECISION",
        "ALTER TABLE tmdb_episodes ADD COLUMN IF NOT EXISTS imdb_id VARCHAR(32)",
    ]
    try:
        with Engine.begin() as conn:
            for sql in stmts:
                try:
                    conn.execute(text(sql))
                except Exception:
                    # Non-fatal: skip if table not present yet
                    pass
    except Exception:
        logger.exception("Failed ensuring new columns")


# --- Helper repository functions (minimal) ---
def list_playlists(session: Session) -> List[Dict]:
    rows = session.query(Playlist).all()
    out: List[Dict] = []
    for p in rows:
        out.append({
            "id": p.id,
            "name": p.name,
            "url": p.url,
            "mode": p.mode,
            "every_hours": p.every_hours,
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
            row = Playlist(id=pid, name=it.get("name") or "", url=it.get("url") or "")
            session.add(row)
        row.name = it.get("name") or row.name
        row.url = it.get("url") or row.url
        row.mode = it.get("mode") or row.mode
        row.every_hours = int(it.get("every_hours") or row.every_hours or 12)
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
