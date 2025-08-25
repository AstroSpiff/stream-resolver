import json
import subprocess
from typing import Optional

class ResolverError(Exception):
    pass

def _run(cmd, *, cwd=None, timeout=30, input_text: Optional[str] = None):
    try:
        return subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
    except Exception as e:
        raise ResolverError(f"launch_error: {e}")

def _as_json_or_url(stdout: str):
    out = (stdout or "").strip()
    if not out:
        return None
    # JSON?
    try:
        return json.loads(out)
    except Exception:
        pass
    # URL semplice?
    if out.startswith(("http://", "https://")):
        return {"ok": True, "resolvedUrl": out}
    return None

def _err_detail(proc: subprocess.CompletedProcess) -> str:
    err = (proc.stderr or "").strip().replace("\r", "")
    err = "\n".join(err.splitlines()[-6:])  # ultime 6 righe
    return f"rc={proc.returncode}; stderr_last_lines=\n{err}" if err else f"rc={proc.returncode}"

def run_resolver(
    script_path: str,
    url: str,
    kind: str,
    headers: dict | None = None,
    python_command: str = "python3",
    cwd: str | None = None,
    timeout: int = 30,
) -> dict:
    """
    Lancia lo script resolver come processo esterno.
    Tenta in ordine:
      1) python script.py <URL>
      2) python script.py --json <URL>
      3) echo '{"url":"<URL>","headers":{...},"kind":"tv|video"}' | python script.py
    Accetta stdout come JSON o URL semplice.
    """
    payload = {"url": url, "headers": headers or {}, "kind": kind}

    # 1) argv semplice
    proc = _run([python_command, script_path, url], cwd=cwd, timeout=timeout)
    parsed = _as_json_or_url(proc.stdout)
    if parsed:
        parsed.setdefault("ok", True)
        return parsed

    # 2) prova flag --json (se lo script lo supporta)
    proc2 = _run([python_command, script_path, "--json", url], cwd=cwd, timeout=timeout)
    parsed2 = _as_json_or_url(proc2.stdout)
    if parsed2:
        parsed2.setdefault("ok", True)
        return parsed2

    # 3) stdin JSON
    proc3 = _run([python_command, script_path], cwd=cwd, timeout=timeout, input_text=json.dumps(payload))
    parsed3 = _as_json_or_url(proc3.stdout)
    if parsed3:
        parsed3.setdefault("ok", True)
        return parsed3

    # Nessuna modalità ha funzionato → errore parlante
    detail = " | ".join([_err_detail(proc), _err_detail(proc2), _err_detail(proc3)])
    raise ResolverError(f"no_usable_output ({detail})")