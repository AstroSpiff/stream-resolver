# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from app import config
from app import db
from app.services.xtream import (
    xtreams,
    save_xtreams,
    get_xtream_cache_status,
    spawn_build,
    build_xtream_cache,
    now_ts,
    crc32_num,
    require_xt_id,
    require_xtream,
    require_xt_creds,
    stream_resolver_base,
)

router = APIRouter()


@router.get("/admin/xtreams.json")
def admin_xtreams_list():
    items = xtreams()
    for item in items:
        item["cache_status"] = get_xtream_cache_status(item)
    return {"items": items}


@router.post("/admin/xtreams")
def admin_xtreams_add(payload: Dict[str, Any]):
    it = {
        "id": f"xt_{hex(crc32_num((payload.get('name') or '') + str(now_ts())))[2:][:8]}",
        "name": payload.get("name") or "Xtream",
        "username": (payload.get("username") or "").strip(),
        "password": (payload.get("password") or "").strip(),
        "resolver_url": (payload.get("resolver_url") or "").strip(),
        "live_list_ids": payload.get("live_list_ids") or [],
        "movie_list_ids": payload.get("movie_list_ids") or [],
        "series_list_ids": payload.get("series_list_ids") or [],
        "mixed_list_ids": payload.get("mixed_list_ids") or [],
        "every_hours": int(payload.get("every_hours") or 12),
        "last_refresh": now_ts(),
        "dedupe_policy": (payload.get("dedupe_policy") or "m3u_order"),
        "export_live_fields": payload.get("export_live_fields") or [],
        "export_movie_fields": payload.get("export_movie_fields") or [],
        "export_series_fields": payload.get("export_series_fields") or [],
        "export_season_fields": payload.get("export_season_fields") or [],
        "export_episode_fields": payload.get("export_episode_fields") or [],
    }
    items = xtreams()
    items.append({k: it[k] for k in ("id","name","username","password","resolver_url","every_hours","last_refresh","dedupe_policy","export_live_fields","export_movie_fields","export_series_fields","export_season_fields","export_episode_fields")})
    save_xtreams(items)
    from app import db as _db
    with _db.SessionLocal() as s:
        _db.set_xtream_links(s, it["id"], it["live_list_ids"], it["movie_list_ids"], it["series_list_ids"], it["mixed_list_ids"])
        s.commit()
    return {"ok": True, "item": it}


@router.delete("/admin/xtreams/{xt_id}")
def admin_xtreams_delete(xt_id: str):
    # Persist (DB only)
    with db.SessionLocal() as s:
        db.delete_xtream(s, xt_id)
        s.commit()
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    try:
        os.remove(cache_file)
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.post("/admin/xtreams/{xt_id}/update")
async def admin_xtreams_update(xt_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    items = xtreams()
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
        found["username"] = (payload.get("username") or "").strip()
    if "password" in payload:
        found["password"] = (payload.get("password") or "").strip()
    if "resolver_url" in payload:
        found["resolver_url"] = (payload.get("resolver_url") or "").strip()
    if "every_hours" in payload:
        try:
            ehours = int(payload["every_hours"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Invalid every_hours")
        found["every_hours"] = max(1, ehours)
    if "dedupe_policy" in payload:
        val = (payload.get("dedupe_policy") or "m3u_order").strip()
        if val not in ("m3u_order","random","exclude_low"):
            raise HTTPException(400, "Invalid dedupe_policy")
        found["dedupe_policy"] = val
    # export field selections
    if "export_live_fields" in payload:
        v = payload.get("export_live_fields") or []
        if not isinstance(v, list):
            raise HTTPException(400, "export_live_fields must be a list")
        found["export_live_fields"] = v
    if "export_movie_fields" in payload:
        v = payload.get("export_movie_fields") or []
        if not isinstance(v, list):
            raise HTTPException(400, "export_movie_fields must be a list")
        found["export_movie_fields"] = v
    if "export_series_fields" in payload:
        v = payload.get("export_series_fields") or []
        if not isinstance(v, list):
            raise HTTPException(400, "export_series_fields must be a list")
        found["export_series_fields"] = v
    if "export_season_fields" in payload:
        v = payload.get("export_season_fields") or []
        if not isinstance(v, list):
            raise HTTPException(400, "export_season_fields must be a list")
        found["export_season_fields"] = v
    if "export_episode_fields" in payload:
        v = payload.get("export_episode_fields") or []
        if not isinstance(v, list):
            raise HTTPException(400, "export_episode_fields must be a list")
        found["export_episode_fields"] = v
    # lists of playlist ids
    touch_links = False
    live_ids = found.get("live_list_ids") or []
    movie_ids = found.get("movie_list_ids") or []
    series_ids = found.get("series_list_ids") or []
    mixed_ids = found.get("mixed_list_ids") or []
    for key in ("live_list_ids", "movie_list_ids", "series_list_ids", "mixed_list_ids"):
        if key in payload:
            val = payload[key]
            if not isinstance(val, list):
                raise HTTPException(400, f"{key} must be a list")
            vals = [str(x) for x in val]
            if key=="live_list_ids": live_ids=vals
            if key=="movie_list_ids": movie_ids=vals
            if key=="series_list_ids": series_ids=vals
            if key=="mixed_list_ids": mixed_ids=vals
            found[key] = vals
            touch_links = True

    if touch_links:
        from app import db as _db
        with _db.SessionLocal() as s:
            _db.set_xtream_links(s, xt_id, live_ids, movie_ids, series_ids, mixed_ids)
            s.commit()

    if payload.get("refresh"):
        base_url = stream_resolver_base(request)
        build_xtream_cache(base_url, found)
        found["last_refresh"] = now_ts()

    save_xtreams(items)
    return {"ok": True, "item": found}


@router.post("/admin/xtreams/{xt_id}/clear_cache")
async def admin_xtreams_clear_cache(xt_id: str):
    cache_file = os.path.join(config.XTREAM_CACHE_DIR, f"{xt_id}.json")
    try:
        os.remove(cache_file)
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.post("/admin/xtreams/{xt_id}/refresh")
async def admin_xtreams_refresh(xt_id: str, request: Request):
    items = xtreams()
    target = next((x for x in items if x.get("id") == xt_id), None)
    if not target:
        raise HTTPException(404, "Not Found")
    # Avvia rigenerazione in background per mostrare "in costruzione" e permettere polling UI
    base_url = (target.get("resolver_url") or "").strip() or stream_resolver_base(request)
    spawn_build(base_url, target)
    return {"ok": True, "item": target, "status": "started"}
