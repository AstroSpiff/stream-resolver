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
