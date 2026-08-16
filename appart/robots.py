"""Garde-fou robots.txt.

La recommandation CNIL de juin 2026 sur le scraping fait du respect des
directives Disallow un élément lourd d'appréciation de la légalité.
Toute requête sortante passe par ici — pas d'exception.
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser
from threading import Lock

from curl_cffi import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Sites dont les CGU/robots interdisent explicitement tout accès automatisé.
BLOCKLIST = {
    "leboncoin.fr": "robots.txt: « It's forbidden to use search robots or other automatic methods »",
    "www.leboncoin.fr": "robots.txt: interdiction explicite des robots",
}

_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
_last_hit: dict[str, float] = {}
_lock = Lock()
MIN_DELAY = 1.5  # s entre deux requêtes sur un même hôte


class RobotsDenied(Exception):
    pass


def _parser_for(host: str) -> urllib.robotparser.RobotFileParser:
    if host in _cache:
        return _cache[host]
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = requests.get(f"https://{host}/robots.txt", impersonate="chrome", timeout=15)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except Exception:
        rp.parse([])  # inaccessible => on n'invente pas d'interdiction
    _cache[host] = rp
    return rp


def check(url: str) -> None:
    """Lève RobotsDenied si l'URL est interdite. Sinon ne fait rien."""
    host = urllib.parse.urlparse(url).netloc
    if host in BLOCKLIST:
        raise RobotsDenied(f"{host} exclu — {BLOCKLIST[host]}")
    if not _parser_for(host).can_fetch(UA, url):
        raise RobotsDenied(f"robots.txt de {host} interdit {url}")


def polite_get(url: str, **kw):
    """GET conforme robots.txt, rythmé, avec empreinte TLS de navigateur réel."""
    check(url)
    host = urllib.parse.urlparse(url).netloc
    with _lock:
        delta = time.monotonic() - _last_hit.get(host, 0.0)
        if delta < MIN_DELAY:
            time.sleep(MIN_DELAY - delta)
        _last_hit[host] = time.monotonic()
    kw.setdefault("impersonate", "chrome")
    kw.setdefault("timeout", 30)
    return requests.get(url, **kw)
