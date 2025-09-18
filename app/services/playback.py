# -*- coding: utf-8 -*-
from __future__ import annotations

import ipaddress
import os
import urllib.parse
from typing import Dict, Optional

import httpx
from fastapi import Request, HTTPException

from app.config import url_encode, get_mediaflow_preset
from app.services.policies import apply_policy

MEDIAFLOW_PROXY = os.environ.get("MEDIAFLOW_PROXY", "")
PYTHON_CMD = os.environ.get("RESOLVER_COMMAND", "python3")
RESOLVERS_DIR = os.environ.get("RESOLVERS_DIR", "/opt/external-resolvers")

VIX_HOSTS = set()  # spostato in policy configurabile
VAVOO_HOSTS = set()  # spostato in policy configurabile


def parse_host(u: str) -> str:
    try:
        return urllib.parse.urlparse(u).hostname or ""
    except Exception:
        return ""


def build_vixcloud_redirect(original_url: str) -> str:
    mflow, pwd = get_mediaflow_preset(None)
    if not mflow or not pwd:
        raise HTTPException(status_code=400, detail="Config mancante: imposta mediaflow_url e api_password in /admin.")
    return (
        f"{mflow}/extractor/video"
        f"?host=VixCloud&redirect_stream=true"
        f"&api_password={url_encode(pwd)}&d={url_encode(original_url)}"
    )


def wrap_proxy(url: str, enabled: bool) -> str:
    if enabled and MEDIAFLOW_PROXY:
        base = MEDIAFLOW_PROXY.rstrip("/")
        return f"{base}/fetch?target={urllib.parse.quote(url, safe='')}"
    return url


def handle_generic(url: str, kind: str, headers: Optional[Dict[str, str]], use_proxy: bool):
    """Policy-only fallback: no legacy domains.json resolver lookup.

    If no policy matched, just passthrough the original URL (optionally via proxy)
    and mark the type as unknown.
    """
    return {
        "ok": True,
        "type": "unknown",
        "resolvedUrl": wrap_proxy(url, use_proxy),
        "headers": headers or {},
        "meta": {"resolver": None, "note": "no_policy_matched"},
    }


def vix_fastpath(url: str) -> str:
    host = (parse_host(url) or "").lower()
    if host in VIX_HOSTS:
        return build_vixcloud_redirect(url)
    return ""


def _client_ip(request: Request) -> str:
    try:
        xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        cand = xff or (request.headers.get("x-real-ip") or "").strip() or (request.client.host if request.client else "")
        return cand or ""
    except Exception:
        return ""


def _is_private_ip(ip: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    except Exception:
        return False


def is_local_request(request: Request) -> bool:
    return _is_private_ip(_client_ip(request))


def handle_tv(request: Request, url: str, headers: Optional[Dict[str, str]], use_proxy: bool):
    try:
        # 1) prova policy configurabili (preferito)
        pol = apply_policy(request, url, "tv", headers=headers, use_proxy=use_proxy)
        if pol:
            return pol
        # 2) fallback storico: percorso generico/registry
        return handle_generic(url, "tv", headers, use_proxy)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"tv_handler_error: {e}")


def handle_video(request: Optional[Request], url: str, headers: Optional[Dict[str, str]], use_proxy: bool):
    # 1) policy (preferito): passa la request per decidere locale/remoto
    pol = apply_policy(request, url, "video", headers=headers, use_proxy=use_proxy)
    if pol:
        return pol
    # 2) fallback storico
    return handle_generic(url, "video", headers, use_proxy)
