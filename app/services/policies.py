# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import uuid
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple, cast

from fastapi import HTTPException, Request

from app import config
from app.adapter import ResolverError, run_resolver
import logging
from app.logutil import redact_url
from functools import lru_cache

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


_DEFAULT_DB_FIELDS = ("h_user-agent", "h_referer", "h_origin", "h_cookie", "key_id", "key")


def _resolve_db_fields_config(mf: Dict[str, Any]) -> Dict[str, bool]:
    raw = mf.get("db_fields")
    fields: Dict[str, bool] = {}
    if isinstance(raw, dict):
        fields = {str(k): bool(v) for k, v in raw.items()}
    if mf.pop("use_db_metadata", False):
        if not fields:
            fields = {name: True for name in _DEFAULT_DB_FIELDS}
        else:
            for name in _DEFAULT_DB_FIELDS:
                fields.setdefault(name, True)
    mf["db_fields"] = fields
    return fields


@lru_cache(maxsize=512)
def _playlist_metadata(original_url: str) -> Optional[Dict[str, Any]]:
    try:
        from app import db as _db
        from sqlalchemy import select

        with _db.SessionLocal() as session:
            stmt = (
                select(_db.PlaylistItem)
                .where(_db.PlaylistItem.original_url == original_url)
                .order_by(_db.PlaylistItem.requires_proxy.desc().nullslast(), _db.PlaylistItem.id.desc())
            )
            row = session.execute(stmt).scalars().first()
            if not row:
                return None

            attrs = row.attrs if isinstance(row.attrs, dict) else {}
            special_raw = attrs.get('special')
            special = cast(Dict[str, Any], special_raw) if isinstance(special_raw, dict) else {}
            raw_headers = special.get('headers')
            raw_license = special.get('license')
            special_headers = cast(Dict[str, Any], raw_headers) if isinstance(raw_headers, dict) else {}
            special_license = cast(Dict[str, Any], raw_license) if isinstance(raw_license, dict) else {}

            return {
                "headers": {
                    "h_user-agent": getattr(row, 'headers_user_agent', None),
                    "h_referer": getattr(row, 'headers_referer', None),
                    "h_origin": getattr(row, 'headers_origin', None),
                    "h_cookie": getattr(row, 'headers_cookie', None),
                },
                "license_type": str(getattr(row, 'license_type', '') or '').lower(),
                "clearkey_kid": getattr(row, 'clearkey_kid', None),
                "clearkey_key": getattr(row, 'clearkey_key', None),
                "special_headers": {k.lower(): v for k, v in special_headers.items() if v},
                "special_license": {k.lower(): v for k, v in special_license.items() if v},
            }
    except Exception:
        return None


def _merge_mediaflow_metadata(mf: Dict[str, Any], original_url: str, db_fields: Dict[str, bool]) -> None:
    if not db_fields:
        return

    meta = _playlist_metadata(original_url)
    if not meta:
        return

    headers = mf.setdefault('headers', {})
    meta_headers = cast(Dict[str, Any], meta.get('headers') or {})
    specials = cast(Dict[str, Any], meta.get('special_headers') or {})

    def maybe_set_header(field: str, candidates: List[Any]) -> None:
        if not db_fields.get(field):
            return
        if headers.get(field):
            return
        for candidate in candidates:
            if candidate:
                headers[field] = str(candidate)
                return

    maybe_set_header('h_user-agent', [meta_headers.get('h_user-agent'), specials.get('user-agent')])
    maybe_set_header('h_referer', [meta_headers.get('h_referer'), specials.get('referer'), specials.get('referrer')])
    maybe_set_header('h_origin', [meta_headers.get('h_origin'), specials.get('origin')])
    maybe_set_header('h_cookie', [meta_headers.get('h_cookie'), specials.get('cookie'), specials.get('cookies')])

    if meta.get('license_type') == 'clearkey':
        clearkey = mf.setdefault('clearkey', {})
        special_license = cast(Dict[str, Any], meta.get('special_license') or {})
        if db_fields.get('key_id') and not clearkey.get('key_id'):
            kid = meta.get('clearkey_kid') or special_license.get('key_id') or special_license.get('kid')
            if kid:
                clearkey['key_id'] = str(kid).strip()
        if db_fields.get('key') and not clearkey.get('key'):
            key_val = meta.get('clearkey_key') or special_license.get('key')
            if key_val:
                clearkey['key'] = str(key_val).strip()
def _build_mediaflow_url(original_url: str, mf: Dict[str, Any]) -> str:
    logger = logging.getLogger(__name__)
    preset = (mf.get("preset") or "").strip() or None
    mflow, pwd = config.get_mediaflow_preset(preset)
    if not mflow or not pwd:
        raise HTTPException(status_code=400, detail="Config mancante: imposta mediaflow_url e api_password in /admin.")
    db_fields = _resolve_db_fields_config(mf)
    try:
        _merge_mediaflow_metadata(mf, original_url, db_fields)
    except Exception:
        logger.exception("MF metadata merge failed for %s", redact_url(original_url))

    headers_log = {}
    for k, v in (mf.get("headers") or {}).items():
        headers_log[k] = "****" if k == "h_cookie" else v
    clearkey_log = {}
    for k, v in (mf.get("clearkey") or {}).items():
        clearkey_log[k] = "****" if k == "key" else v
    logger.debug(
        "MF build: endpoint=%s path=%s headers=%s clearkey=%s url=%s",
        (mf.get("endpoint") or ""),
        (mf.get("path") or ""),
        headers_log,
        clearkey_log,
        redact_url(original_url),
    )

    def append_common(params: List[Tuple[str, str]]) -> None:
        headers = mf.get("headers") or {}
        for hkey in ("h_referer", "h_origin", "h_user-agent", "h_cookie"):
            hv = str(headers.get(hkey) or "").strip()
            if hv:
                params.append((hkey, hv))
        ck = mf.get("clearkey") or {}
        kid = str(ck.get("key_id") or ck.get("kid") or "").strip()
        key = str(ck.get("key") or "").strip()
        if kid:
            params.append(("key_id", kid))
        if key:
            params.append(("key", key))

    endpoint = (mf.get("endpoint") or "extractor_video").strip().lower()
    if endpoint == "proxy":
        path = (mf.get("path") or "").strip().strip("/") or "hls/manifest.m3u8"
        base = f"{mflow}/proxy/{path}"
        params: List[Tuple[str, str]] = [("d", original_url), ("api_password", pwd)]
        append_common(params)
        if mf.get("force_playlist_proxy"):
            params.append(("force_playlist_proxy", "true"))
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
    append_common(q)
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
