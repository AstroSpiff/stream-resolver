# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import uuid
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

from app import config
from app.adapter import ResolverError, run_resolver
import logging
from app.logutil import redact_url

POLICIES_FILE = os.path.join(config.CONFIG_DIR, "resolver_policies.json")


def _default_policies() -> List[Dict[str, Any]]:
    return [
        # VixSrc → MediaFlow extractor (redirect_stream=true) su /video
        {
            "id": uuid.uuid4().hex[:8],
            "enabled": True,
            "match": "vixsrc.to|vixsrl.to",
            "match_type": "regex",
            "kind": "video",
            "local_mode": "mediaflow",
            "remote_mode": "mediaflow",
            "internal": {},
            "mediaflow": {"host": "VixCloud", "redirect_stream": True},
            "proxy": False,
            "priority": 100,
        },
        # Vavoo → interno (resolver esterno) in LAN, MediaFlow da remoto su /tv
        {
            "id": uuid.uuid4().hex[:8],
            "enabled": True,
            "match": "vavoo.to",
            "match_type": "substr",
            "kind": "tv",
            "local_mode": "internal",
            "remote_mode": "mediaflow",
            "internal": {"path": os.path.join(config.USER_RESOLVERS_DIR, "vavoo_resolver.py")},
            "mediaflow": {"host": "VixCloud", "redirect_stream": True},
            "proxy": False,
            "priority": 100,
        },
    ]


def load_policies() -> List[Dict[str, Any]]:
    pols = config.read_json(POLICIES_FILE, None)
    if pols is None:
        pols = _default_policies()
        config.write_json(POLICIES_FILE, pols)
        return pols
    changed = False
    # migrate: fix internal.path pointing to /opt when file moved under config/resolvers
    for p in pols:
        internal = p.get("internal") or {}
        path = internal.get("path")
        if path and not os.path.exists(path):
            base = os.path.basename(path)
            cand = os.path.join(config.USER_RESOLVERS_DIR, base)
            if os.path.exists(cand):
                internal["path"] = cand
                p["internal"] = internal
                changed = True
    if changed:
        config.write_json(POLICIES_FILE, pols)
    # sort by priority asc (lower first)
    try:
        pols = sorted(pols, key=lambda x: int(x.get("priority", 100)))
    except Exception:
        pass
    return pols


def save_policies(items: List[Dict[str, Any]]):
    config.write_json(POLICIES_FILE, items)


def _parse_host(u: str) -> str:
    try:
        return urllib.parse.urlparse(u).hostname or ""
    except Exception:
        return ""


def pick_policy(url: str, kind: str, is_local: bool) -> Optional[Dict[str, Any]]:
    kind = (kind or "").lower()
    host = _parse_host(url).lower()
    for p in load_policies():
        if not p.get("enabled", True):
            continue
        pkind = (p.get("kind") or "any").lower()
        if pkind not in ("any", kind):
            continue
        mt = (p.get("match_type") or "substr").lower()
        pat = p.get("match") or ""
        ok = False
        try:
            if mt == "regex":
                ok = bool(re.search(pat, host, re.I))
            else:
                ok = pat.lower() in host
        except Exception:
            ok = False
        if ok:
            return p
    return None


def _wrap_proxy(url: str, enabled: bool) -> str:
    proxy = os.environ.get("MEDIAFLOW_PROXY", "")
    if enabled and proxy:
        base = proxy.rstrip("/")
        return f"{base}/fetch?target={urllib.parse.quote(url, safe='')}"
    return url


def _build_mediaflow_url(original_url: str, mf: Dict[str, Any]) -> str:
    logger = logging.getLogger(__name__)
    # pick preset if specified, else default
    preset = (mf.get("preset") or "").strip() or None
    mflow, pwd = config.get_mediaflow_preset(preset)
    if not mflow or not pwd:
        raise HTTPException(status_code=400, detail="Config mancante: imposta mediaflow_url e api_password in /admin.")
    # Optional: per-field enrichment from DB
    dbf = mf.get("db_fields") or {}
    legacy = bool(mf.get("use_db_metadata"))
    wants_any = legacy or any(bool(v) for v in dbf.values())
    if wants_any:
        try:
            # Lookup PlaylistItem by original_url and inject headers/clearkey from attrs.special
            from app import db as _db
            from sqlalchemy import select
            with _db.SessionLocal() as s:
                cand = (
                    s.execute(
                        select(_db.PlaylistItem)
                        .where(_db.PlaylistItem.original_url == original_url)
                        .order_by(_db.PlaylistItem.requires_proxy.desc().nullslast(), _db.PlaylistItem.id.desc())
                    ).scalars().first()
                )
                if cand:
                    hmap = mf.setdefault('headers', {})
                    if legacy or dbf.get('h_user-agent'):
                        if getattr(cand, 'headers_user_agent', None):
                            hmap['h_user-agent'] = str(cand.headers_user_agent)
                    if legacy or dbf.get('h_referer'):
                        if getattr(cand, 'headers_referer', None):
                            hmap['h_referer'] = str(cand.headers_referer)
                    if legacy or dbf.get('h_origin'):
                        if getattr(cand, 'headers_origin', None):
                            hmap['h_origin'] = str(cand.headers_origin)
                    if legacy or dbf.get('h_cookie'):
                        if getattr(cand, 'headers_cookie', None):
                            hmap['h_cookie'] = str(cand.headers_cookie)
                    if legacy or dbf.get('key_id') or dbf.get('key'):
                        if str(getattr(cand, 'license_type', '') or '').lower() == 'clearkey':
                            kid = (getattr(cand, 'clearkey_kid', '') or '').strip()
                            key = (getattr(cand, 'clearkey_key', '') or '').strip()
                            if (legacy or dbf.get('key_id')) and kid:
                                mf.setdefault('clearkey', {})['key_id'] = kid
                            if (legacy or dbf.get('key')) and key:
                                mf.setdefault('clearkey', {})['key'] = key
                    if isinstance(cand.attrs, dict):
                        sp = (cand.attrs or {}).get('special') or {}
                        if isinstance(sp, dict):
                            hdrs_in = (sp.get('headers') or {}) if isinstance(sp.get('headers'), dict) else {}
                            for hk, hv in hdrs_in.items():
                                nm = (hk or '').strip().lower()
                                if not hv:
                                    continue
                                if (legacy or dbf.get('h_user-agent')) and nm == 'user-agent':
                                    hmap.setdefault('h_user-agent', str(hv))
                                elif (legacy or dbf.get('h_referer')) and nm in ('referer', 'referrer'):
                                    hmap.setdefault('h_referer', str(hv))
                                elif (legacy or dbf.get('h_origin')) and nm == 'origin':
                                    hmap.setdefault('h_origin', str(hv))
                                elif (legacy or dbf.get('h_cookie')) and nm in ('cookie', 'cookies'):
                                    hmap.setdefault('h_cookie', str(hv))
                            lic = sp.get('license') or {}
                            if (legacy or dbf.get('key_id') or dbf.get('key')) and isinstance(lic, dict) and (str(lic.get('type') or '').lower() == 'clearkey'):
                                kid2 = str(lic.get('key_id') or lic.get('kid') or '').strip()
                                key2 = str(lic.get('key') or '').strip()
                                if (legacy or dbf.get('key_id')) and kid2:
                                    mf.setdefault('clearkey', {})['key_id'] = kid2
                                if (legacy or dbf.get('key')) and key2:
                                    mf.setdefault('clearkey', {})['key'] = key2
        except Exception:
            # Non-fatal: fallback to policy-provided values
            pass
    try:
        # Log sintetico della build MF (redatto)
        logger.debug(
            "MF build: endpoint=%s path=%s headers=%s url=%s",
            (mf.get("endpoint") or ""),
            (mf.get("path") or ""),
            {k: ("****" if k in ("h_cookie",) else v) for k, v in (mf.get("headers") or {}).items()},
            redact_url(original_url),
        )
    except Exception:
        pass
    endpoint = (mf.get("endpoint") or "extractor_video").lower()
    if endpoint == "proxy":
        path = (mf.get("path") or "").strip().strip("/") or "hls/manifest.m3u8"
        base = f"{mflow}/proxy/{path}"
        params: List[Tuple[str, str]] = [("d", original_url), ("api_password", pwd)]
        headers = (mf.get("headers") or {})
        for hkey in ("h_referer", "h_origin", "h_user-agent", "h_cookie"):
            hv = (headers.get(hkey) or "").strip()
            if hv:
                params.append((hkey, hv))
        if mf.get("force_playlist_proxy"):
            params.append(("force_playlist_proxy", "true"))
        ck = mf.get("clearkey") or {}
        # Ensure values are strings for typing safety
        kid = str(ck.get("key_id") or "").strip()
        key = str(ck.get("key") or "").strip()
        if kid and key:
            params.append(("key_id", kid))
            params.append(("key", key))
        qs = "&".join(f"{k}={config.url_encode(v)}" for k, v in params)
        return f"{base}?{qs}"
    # default: extractor/video
    host = mf.get("host") or ""
    redirect_stream = bool(mf.get("redirect_stream", True))
    q = [
        ("host", host),
        ("redirect_stream", "true" if redirect_stream else "false"),
        ("api_password", pwd),
        ("d", original_url),
    ]
    qs = "&".join(f"{k}={config.url_encode(v)}" for k, v in q if v != "")
    return f"{mflow}/extractor/video?{qs}"


def apply_policy(
    request: Optional[Request],
    url: str,
    kind: str,
    headers: Optional[Dict[str, str]] = None,
    use_proxy: bool = False,
) -> Optional[Dict[str, Any]]:
    # Decide local/remote
    from app.services.playback import is_local_request  # avoid cycle
    is_local = is_local_request(request) if request is not None else True

    p = pick_policy(url, kind, is_local)
    if not p:
        return None

    mode = (p.get("local_mode") if is_local else p.get("remote_mode")) or "direct"
    mode = mode.lower()

    if mode == "direct":
        return {
            "ok": True,
            "type": "direct",
            "resolvedUrl": _wrap_proxy(url, p.get("proxy", False) or use_proxy),
            "headers": headers or {},
            "meta": {"policy": p.get("id")},
        }

    if mode == "mediaflow":
        mf = p.get("mediaflow") or {}
        mf_url = _build_mediaflow_url(url, mf)
        return {
            "ok": True,
            "type": "mediaflow_extractor",
            "resolvedUrl": mf_url,
            "headers": headers or {},
            "meta": {"policy": p.get("id"), "mediaflow": mf},
        }

    if mode == "internal":
        internal = p.get("internal") or {}
        path = internal.get("path")
        if path and not os.path.exists(path):
            # try same filename under USER_RESOLVERS_DIR
            base = os.path.basename(path)
            cand = os.path.join(config.USER_RESOLVERS_DIR, base)
            if os.path.exists(cand):
                path = cand
        if not path:
            tag = internal.get("tag")
            if tag:
                cand1 = os.path.join(config.USER_RESOLVERS_DIR, f"{tag}_resolver.py")
                cand2 = os.path.join(os.environ.get("RESOLVERS_DIR", "/opt/external-resolvers"), f"{tag}_resolver.py")
                if os.path.exists(cand1):
                    path = cand1
                elif os.path.exists(cand2):
                    path = cand2
        if not path or not os.path.exists(path):
            raise HTTPException(500, f"Resolver interno non trovato: {path}")
        try:
            out = run_resolver(path, url, kind, headers=headers, cwd=os.path.dirname(path))
            out["resolvedUrl"] = _wrap_proxy(out.get("resolvedUrl", ""), p.get("proxy", False) or use_proxy)
            out.setdefault("meta", {})["policy"] = p.get("id")
            out.setdefault("meta", {})["resolver_path"] = os.path.basename(path)
            return out
        except ResolverError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"resolver_internal_error: {e}")

    # Unknown mode
    raise HTTPException(500, f"Modo policy non supportato: {mode}")
