import os, json
from pathlib import Path

RESOLVERS_DIR = os.environ.get("RESOLVERS_DIR", "/opt/external-resolvers")
DOMAINS_JSON  = os.environ.get("DOMAINS_JSON", "/opt/external-resolvers/config/domains.json")

if os.path.exists(DOMAINS_JSON):
    with open(DOMAINS_JSON, "r", encoding="utf-8") as f:
        DOMAIN_MAP = json.load(f)
else:
    DOMAIN_MAP = {}

def pick_script_for(hostname: str) -> str | None:
    for tag, domain in DOMAIN_MAP.items():
        if domain in hostname:
            candidate = Path(RESOLVERS_DIR) / f"{tag}_resolver.py"
            if candidate.exists():
                return str(candidate)
    return None
