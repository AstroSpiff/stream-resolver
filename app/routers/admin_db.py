# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
import os

from app import config
from app import db

router = APIRouter()


def _redact_url(u: str) -> str:
    try:
        # Nascondi la password senza introdurre sequenze \1 letterali
        return re.sub(r"://([^:]+):([^@]+)@", lambda m: f"://{m.group(1)}:****@", u)
    except Exception:
        return u


@router.get("/admin/db/ping")
def admin_db_ping() -> dict[str, Any]:
    """Test di connessione al DB corrente. Non solleva errori: ritorna ok=false con messaggio."""
    backend = config.get_storage_backend()
    url = config.get_database_url()
    source = 'env' if os.environ.get('DATABASE_URL', '').strip() else 'settings'
    if backend != "db":
        return {"ok": False, "backend": backend, "url": _redact_url(url), "source": source, "error": "Storage backend non è 'db'"}
    try:
        # Usa un engine temporaneo con connect_timeout breve per evitare pendings lunghi
        from sqlalchemy import create_engine
        tmp = create_engine(url, future=True, pool_pre_ping=False, connect_args={"connect_timeout": 2})
        with tmp.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"ok": True, "backend": backend, "url": _redact_url(url), "source": source}
    except Exception as e:
        return {"ok": False, "backend": backend, "url": _redact_url(url), "source": source, "error": str(e)}


@router.get("/admin/db/tables")
def admin_db_tables() -> dict[str, Any]:
    """Elenca le tabelle presenti nel DB."""
    try:
        table_names = list(db.Base.metadata.tables.keys())
        return {"ok": True, "tables": table_names}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/admin/db/tables/{table_name}")
def admin_db_table_content(table_name: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
    """Ritorna il contenuto di una tabella, con paginazione."""
    try:
        if table_name not in db.Base.metadata.tables:
            return {"ok": False, "error": "Table not found"}

        table = db.Base.metadata.tables[table_name]
        with db.Engine.connect() as connection:
            # Use SQLAlchemy's count function for portability
            import sqlalchemy
            count_query = sqlalchemy.select(sqlalchemy.func.count()).select_from(table)
            total_rows = connection.execute(count_query).scalar()

            query = table.select().offset((page - 1) * page_size).limit(page_size)
            result = connection.execute(query)
            rows = [dict(row) for row in result.mappings()]

        return {
            "ok": True,
            "table_name": table_name,
            "rows": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_rows": total_rows,
                "total_pages": (total_rows + page_size - 1) // page_size if total_rows is not None else 0,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/admin/db/playlist_item_counts")
def admin_db_playlist_item_counts() -> dict[str, Any]:
    """Ritorna il conteggio degli elementi PlaylistItem raggruppati per 'kind'."""
    try:
        from sqlalchemy import func
        with db.SessionLocal() as session:
            counts = session.query(db.PlaylistItem.kind, func.count(db.PlaylistItem.kind)).group_by(db.PlaylistItem.kind).all()
            result = {kind: count for kind, count in counts}
        return {"ok": True, "counts": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
