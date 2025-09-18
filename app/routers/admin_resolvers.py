# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from app.services import policies as pol
from app import config
import os
import re
from fastapi import UploadFile, File
from app import db as _db
from sqlalchemy import select
import urllib.parse

router = APIRouter()


@router.get("/admin/resolvers/policies.json")
def list_policies():
    return {"items": pol.load_policies()}


@router.post("/admin/resolvers/policies")
def add_policy(data: Dict[str, Any] = Body(...)):
    items = pol.load_policies()
    item = {
        "id": data.get("id") or uuid.uuid4().hex[:8],
        "enabled": bool(data.get("enabled", True)),
        "match": (data.get("match") or "").strip(),
        "match_type": (data.get("match_type") or "substr").lower(),
        "kind": (data.get("kind") or "any").lower(),
        "local_mode": (data.get("local_mode") or "direct").lower(),
        "remote_mode": (data.get("remote_mode") or "direct").lower(),
        "internal": data.get("internal") or {},
        "mediaflow": data.get("mediaflow") or {},
        "proxy": bool(data.get("proxy", False)),
        "priority": int(data.get("priority") or 100),
    }
    items.append(item)
    pol.save_policies(items)
    return {"ok": True, "item": item}


@router.post("/admin/resolvers/policies/{pid}")
def update_policy(pid: str, data: Dict[str, Any] = Body(...)):
    items = pol.load_policies()
    found = None
    for it in items:
        if it.get("id") == pid:
            found = it
            break
    if not found:
        raise HTTPException(404, "Not Found")
    found.update(data or {})
    pol.save_policies(items)
    return {"ok": True, "item": found}


@router.delete("/admin/resolvers/policies/{pid}")
def delete_policy(pid: str):
    items = [x for x in pol.load_policies() if x.get("id") != pid]
    pol.save_policies(items)
    return {"ok": True}


class TestIn:
    url: str
    kind: str = "tv"
    execute: bool = False


@router.post("/admin/resolvers/test")
def test_policy(request: Request, data: Dict[str, Any] = Body(...)):
    url = (data.get("url") or "").strip()
    kind = (data.get("kind") or "tv").lower()
    if not url:
        raise HTTPException(400, "url mancante")
    p = pol.pick_policy(url, kind, True)
    if not p:
        return {"match": None, "note": "no_policy_matched"}
    if not data.get("execute"):
        return {"match": p}
    # Esegue realmente la policy (attenzione: può fare rete)
    out = pol.apply_policy(request, url, kind)
    return {"match": p, "result": out}


@router.post("/admin/resolvers/policies/reorder")
def reorder_policies(payload: Dict[str, Any] = Body(...)):
    order = payload.get("order") or []
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise HTTPException(400, "order must be a list of ids")
    items = pol.load_policies()
    # build mapping id->item
    mapping = {it.get("id"): it for it in items}
    new_items: list[dict] = []
    # add in provided order first
    for idx, pid in enumerate(order):
        it = mapping.get(pid)
        if it:
            it["priority"] = (idx + 1) * 10
            new_items.append(it)
    # append remaining preserving relative order
    for it in items:
        if it not in new_items:
            it["priority"] = (len(new_items) + 1) * 10
            new_items.append(it)
    pol.save_policies(new_items)
    return {"ok": True}


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


@router.post("/admin/resolvers/upload")
async def upload_resolver(file: UploadFile = File(...)):
    # size limit ~ 512 KiB
    MAX_SIZE = 512 * 1024
    if not file.filename or not file.filename.lower().endswith(".py"):
        raise HTTPException(400, "Solo file .py consentiti")
    # sanitize filename
    base = os.path.basename(file.filename)
    base = _SAFE_NAME.sub("_", base)
    if not base.endswith(".py"):
        base += ".py"
    # read content
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, "File troppo grande (max 512 KiB)")
    # ensure dir
    os.makedirs(config.USER_RESOLVERS_DIR, exist_ok=True)
    dest = os.path.join(config.USER_RESOLVERS_DIR, base)
    # avoid overwrite by appending suffix
    name, ext = os.path.splitext(base)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(config.USER_RESOLVERS_DIR, f"{name}_{i}{ext}")
        i += 1
    with open(dest, "wb") as f:
        f.write(content)
    return {"ok": True, "path": dest}


@router.get("/admin/resolvers/list_files")
def list_resolver_files():
    items = []
    try:
        for fn in os.listdir(config.USER_RESOLVERS_DIR):
            if fn.lower().endswith('.py'):
                items.append({
                    "name": os.path.splitext(fn)[0],
                    "filename": fn,
                    "path": os.path.join(config.USER_RESOLVERS_DIR, fn),
                })
    except FileNotFoundError:
        pass
    return {"items": sorted(items, key=lambda x: x["name"]) }


@router.get("/admin/links/roots")
def admin_list_link_roots():
    """Aggrega domini sorgente e gruppi dai PlaylistItem per facilitare la configurazione senza regex.

    Ritorna:
    - live_protected: [{host, count}]
    - live_plain: [{host, count}]
    - vod: [{host, count}]
    - groups: [{name, count, kinds}]
    """
    def host_of(url: str) -> str:
        try:
            return (urllib.parse.urlparse(url).hostname or '').lower()
        except Exception:
            return ''

    live_prot: dict[str, int] = {}
    live_plain: dict[str, int] = {}
    vod: dict[str, int] = {}
    groups: dict[str, dict] = {}
    with _db.SessionLocal() as s:
        rows = s.execute(select(_db.PlaylistItem)).scalars().all()
        for r in rows:
            url = (r.original_url or '').strip()
            if not url:
                continue
            h = host_of(url)
            kind = (r.kind or 'live').lower()
            # groups agg
            gname = (r.group_title or '').strip()
            if gname:
                g = groups.setdefault(gname, {"name": gname, "count": 0, "kinds": set()})
                g["count"] += 1
                g["kinds"].add(kind)
            # requires_proxy: prefer column, fallback to attrs.special
            rp_col = getattr(r, 'requires_proxy', None)
            if rp_col is None:
                attrs = r.attrs or {}
                special = attrs.get('special') if isinstance(attrs, dict) else None
                rp = bool(special.get('requires_proxy')) if isinstance(special, dict) else False
            else:
                rp = bool(rp_col)
            if kind == 'live':
                if rp:
                    live_prot[h] = live_prot.get(h, 0) + 1
                else:
                    live_plain[h] = live_plain.get(h, 0) + 1
            else:
                # movie/series/episode considerati VOD
                vod[h] = vod.get(h, 0) + 1

    # serialize groups kinds as list
    groups_out = [
        {"name": k, "count": v["count"], "kinds": sorted(list(v["kinds"]))}
        for k, v in groups.items()
    ]
    # sort outputs by count desc then host/name
    def sort_map(m: dict[str, int]):
        return [
            {"host": k, "count": m[k]} for k in sorted(m.keys(), key=lambda x: (-m[x], x or ''))
        ]
    return {
        "ok": True,
        "live_protected": sort_map(live_prot),
        "live_plain": sort_map(live_plain),
        "vod": sort_map(vod),
        "groups": sorted(groups_out, key=lambda x: (-x["count"], x["name"]))
    }


@router.get("/admin/resolvers/diagnose")
def diagnose_policy(request: Request, url: str, kind: str = "tv"):
    """Diagnosi dettagliata della policy applicata a un URL.

    Ritorna:
    - host, is_local
    - policy (se trovata), local_mode/remote_mode
    - chosen_mode (direct/internal/mediaflow)
    - result da apply_policy (type, resolvedUrl, headers)
    - hints comuni per DASH/HLS
    """
    try:
        from app.services.playback import is_local_request
        host = urllib.parse.urlparse(url).hostname or ""
        is_local = is_local_request(request)
        p = pol.pick_policy(url, (kind or "tv"), is_local)
        mode = None
        if p:
            mode = (p.get("local_mode") if is_local else p.get("remote_mode")) or "direct"
        out = pol.apply_policy(request, url, kind)
        data: dict[str, any] = {
            "ok": True,
            "host": host,
            "is_local": is_local,
            "policy": p,
            "chosen_mode": (mode or "unknown"),
            "result": out,
            "hints": [],
        }
        # Hints per DASH e Xtream
        if out and out.get("type") == "direct" and str(url).lower().endswith(".mpd"):
            data["hints"].append("URL DASH (.mpd) diretto: configurare flow=mediaflow e endpoint=proxy con path mpd/segment.mp4 oppure hls/manifest.m3u8")
        # Verifica headers/clearkey
        try:
            mf = (p or {}).get("mediaflow") or {}
            dbf = mf.get("db_fields") or {}
            needs = []
            for k in ("h_user-agent","h_referer","key_id","key"):
                if dbf.get(k):
                    needs.append(k)
            if needs:
                data["hints"].append(f"La policy richiede campi da DB: {', '.join(needs)}. Verificare che playlist_items li abbia popolati per questo URL.")
        except Exception:
            pass
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}
