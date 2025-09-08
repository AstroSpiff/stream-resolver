# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app import config
from app.routers.playback import router as playback_router
from app.routers.admin_playlists import router as admin_router
from app.routers.admin_xtream import router as admin_xtream_router
from app.routers.xtream import router as xtream_router
from app.routers.admin_tmdb import router as admin_tmdb_router
from app.routers.admin_db import router as admin_db_router
from app.routers.admin_resolvers import router as admin_resolvers_router
from app.workers import start_workers
from app import config as _cfg
from app import db as _db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP = FastAPI(title="Stream Resolver", version="1.2.0")


@APP.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("HTTP %s %s headers=%s", request.method, str(request.url), dict(request.headers))
    return await call_next(request)


APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

APP.add_middleware(GZipMiddleware, minimum_size=1000)

if os.path.isdir(config.STATIC_DIR):
    APP.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@APP.get("/", response_class=HTMLResponse)
def home():
    index_path = os.path.join(config.STATIC_DIR, "admin", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Stream Resolver</h1><p>GUI non trovata.</p>")


@APP.get("/health")
def health():
    mflow, pwd = config.get_mediaflow_preset(None)
    configured = bool((mflow or "").strip() and (pwd or "").strip())
    return {
        "ok": True,
        "ts": config.now_ts(),
        "resolvers_dir": os.environ.get("RESOLVERS_DIR", "/opt/external-resolvers"),
        "proxy": os.environ.get("MEDIAFLOW_PROXY", "") or None,
        "configured": configured,
    }


# Routers
APP.include_router(playback_router)
APP.include_router(admin_router)
APP.include_router(admin_xtream_router)
APP.include_router(admin_resolvers_router)
APP.include_router(xtream_router)
APP.include_router(admin_tmdb_router)
APP.include_router(admin_db_router)


@APP.on_event("startup")
def _startup():
    # Init DB if backend set to 'db'
    try:
        if _cfg.get_storage_backend() == 'db':
            _db.init_db()
    except Exception:
        logger.exception("DB initialization failed")
    start_workers()
