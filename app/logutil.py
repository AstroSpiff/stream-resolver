# -*- coding: utf-8 -*-
from __future__ import annotations

import urllib.parse
from typing import Dict, Iterable


SENSITIVE_KEYS = {"api_password", "key", "token", "signature"}


def redact_url(url: str, extra_keys: Iterable[str] | None = None) -> str:
    try:
        keys = set(SENSITIVE_KEYS)
        if extra_keys:
            keys.update({str(k) for k in extra_keys})
        us = urllib.parse.urlsplit(url)
        if not us.query:
            return url
        q = urllib.parse.parse_qsl(us.query, keep_blank_values=True)
        q2 = []
        for k, v in q:
            if k in keys:
                q2.append((k, "****"))
            else:
                q2.append((k, v))
        new_query = urllib.parse.urlencode(q2)
        return urllib.parse.urlunsplit((us.scheme, us.netloc, us.path, new_query, us.fragment))
    except Exception:
        return url


def redact_headers(h: Dict[str, str] | None) -> Dict[str, str]:
    if not h:
        return {}
    out: Dict[str, str] = {}
    for k, v in h.items():
        kn = (k or "").lower()
        if kn in ("authorization", "cookie"):
            out[k] = "****"
        else:
            out[k] = v
    return out

