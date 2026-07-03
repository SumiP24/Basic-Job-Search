"""Verify apply URLs. Only confirmed-dead links (404/410) are dropped;
timeouts and bot-blocks (403/405/999) are treated as alive."""
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) JobRadar/1.0"}
DEAD = {404, 410}


def _is_dead(url):
    try:
        r = requests.head(url, timeout=12, allow_redirects=True, headers=UA)
        if r.status_code in DEAD:
            r = requests.get(url, timeout=12, headers=UA, stream=True)
            return r.status_code in DEAD
        return False
    except requests.RequestException:
        return False


def dead_urls(urls):
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls:
        return set()
    with ThreadPoolExecutor(max_workers=12) as ex:
        flags = list(ex.map(_is_dead, urls))
    return {u for u, d in zip(urls, flags) if d}
