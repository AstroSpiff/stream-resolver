#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vavoo_resolver.py (sample, user-space)

Questo resolver risolve link Vavoo utilizzando l'API ufficiale mediahubmx.
Non dipende da file adiacenti: legge il dominio da env `DOMAINS_JSON` opzionale
oppure usa di default "vavoo.to".

Output atteso: URL finale riproducibile o JSON {"ok":true,"resolvedUrl":"..."}.
Supporta gli stessi contratti dell'adapter: argv <url>, --json <url>, stdin JSON.
"""
import os
import sys
import json
import re
import requests


def _vavoo_domain() -> str:
    dom = "vavoo.to"
    cfg = os.environ.get("DOMAINS_JSON")
    if cfg and os.path.exists(cfg):
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                m = json.load(f)
            dom = m.get("vavoo") or dom
        except Exception:
            pass
    return dom


def _get_signature() -> str:
    headers = {
        "user-agent": "okhttp/4.11.0",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
    }
    data = {
        "token": "tosFwQCJMS8qrW_AjLoHPQ41646J5dRNha6ZWHnijoYQQQoADQoXYSo7ki7O5-CsgN4CH0uRk6EEoJ0728ar9scCRQW3ZkbfrPfeCXW2VgopSW2FWDqPOoVYIuVPAOnXCZ5g",
        "reason": "app-blur",
        "locale": "de",
        "theme": "dark",
        "metadata": {"device": {"type": "Handset", "brand": "google", "model": "Nexus", "name": "21081111RG", "uniqueId": "d10e5d99ab665233"}, "os": {"name": "android", "version": "7.1.2", "abis": ["arm64-v8a", "armeabi-v7a", "armeabi"], "host": "android"}, "app": {"platform": "android", "version": "3.1.20", "buildId": "289515000", "engine": "hbc85", "signatures": ["6e8a975e3cbf07d5de823a760d4c2547f86c1403105020adee5de67ac510999e"], "installer": "app.revanced.manager.flutter"}, "version": {"package": "tv.vavoo.app", "binary": "3.1.20", "js": "3.1.20"}},
        "appFocusTime": 0,
        "playerActive": False,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": True,
        "castConnected": False,
        "package": "tv.vavoo.app",
        "version": "3.1.20",
        "process": "app",
        "firstAppStart": 1743962904623,
        "lastAppStart": 1743962904623,
        "ipLocation": "",
        "adblockEnabled": True,
        "proxy": {"supported": ["ss", "openvpn"], "engine": "ss", "ssVersion": 1, "enabled": True, "autoServer": True, "id": "pl-waw"},
        "iap": {"supported": False},
    }
    try:
        r = requests.post("https://www.vavoo.tv/api/app/ping", json=data, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get("addonSig") or ""
    except Exception:
        return ""


def _resolve_vavoo(link: str) -> str:
    sig = _get_signature()
    if not sig:
        return ""
    headers = {
        "user-agent": "MediaHubMX/2",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
        "mediahubmx-signature": sig,
    }
    data = {"language": "de", "region": "AT", "url": link, "clientVersion": "3.0.2"}
    dom = _vavoo_domain()
    try:
        r = requests.post(f"https://{dom}/mediahubmx-resolve.json", json=data, headers=headers, timeout=10)
        r.raise_for_status()
        result = r.json()
        if isinstance(result, list) and result and result[0].get("url"):
            return result[0]["url"]
        if isinstance(result, dict) and result.get("url"):
            return result["url"]
    except Exception:
        return ""
    return ""


def _read_payload(argv):
    if len(argv) >= 2 and argv[1] != "--json":
        return {"url": argv[1]}
    if len(argv) >= 3 and argv[1] == "--json":
        return {"url": argv[2]}
    data = sys.stdin.read().strip()
    if data:
        try:
            return json.loads(data)
        except Exception:
            pass
    return {}


def main():
    p = _read_payload(sys.argv)
    url = (p.get("url") or "").strip()
    if not url:
        print("", end=""); sys.exit(1)
    out = _resolve_vavoo(url)
    if out:
        print(out)
        return
    print("", end=""); sys.exit(2)


if __name__ == "__main__":
    main()

