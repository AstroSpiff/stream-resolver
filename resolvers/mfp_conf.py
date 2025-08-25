#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mfp_conf.py
Legge le impostazioni condivise per MediaFlow-Proxy:
1) file /app/config/mfp_settings.json scritto dalla GUI,
2) fallback ENV: MEDIAFLOW_PROXY, MEDIAFLOW_PASSWORD/MFP_PASSWORD.
Ritorna (base_url, api_password) normalizzati (schema incluso, niente slash finale).
"""
import os, json

SETTINGS_FILE = os.environ.get("MFP_SETTINGS_FILE", "/app/config/mfp_settings.json")

def load_mediaflow():
    base = (os.environ.get("MEDIAFLOW_PROXY") or "").strip()
    pwd  = (os.environ.get("MEDIAFLOW_PASSWORD") or os.environ.get("MFP_PASSWORD") or "").strip()

    if (not base or not pwd) and os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                base = base or (data.get("mediaflow_url") or "").strip()
                pwd  = pwd  or (data.get("api_password") or "").strip()
        except Exception:
            pass

    # normalizza
    if base:
        base = base.rstrip("/")
        if not base.startswith(("http://","https://")):
            # per sicurezza, MFP ↑ https
            base = "https://" + base
    return base, pwd
