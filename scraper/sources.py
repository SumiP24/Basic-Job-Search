"""Job source fetchers. Each source fails independently; failures show in dashboard health."""
import html
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 JobRadar/1.0"}
S = requests.Session()
S.headers.update(UA)

EU = {"NL", "DE", "DK", "AT", "BE", "FR", "SE", "FI", "NO", "IE", "ES", "PT", "IT", "PL",
      "CZ", "CH", "LU", "EE", "LV", "LT", "HU", "RO", "BG", "HR", "SI", "SK", "GR", "MT",
      "CY", "IS", "EU"}

COUNTRY_NAMES = {
    "netherlands": "NL", "nederland": "NL", "germany": "DE", "deutschland": "DE",
    "denmark": "DK", "danmark": "DK", "austria": "AT", "belgium": "BE", "france": "FR",
    "sweden": "SE", "finland": "FI", "norway": "NO", "ireland": "IE", "spain": "ES",
    "portugal": "PT", "italy": "IT", "poland": "PL", "czech": "CZ", "switzerland": "CH",
    "luxembourg": "LU", "estonia": "EE", "latvia": "LV", "lithuania": "LT", "hungary": "HU",
    "romania": "RO", "bulgaria": "BG", "croatia": "HR", "slovenia": "SI", "slovakia": "SK",
    "greece": "GR", "iceland": "IS",
}

CITY_TO_CC = {
    "amsterdam": "NL", "rotterdam": "NL", "utrecht": "NL", "eindhoven": "NL",
    "the hague": "NL", "den haag": "NL", "delft": "NL", "groningen": "NL",
    "berlin": "DE", "munich": "DE", "münchen": "DE", "hamburg": "DE", "frankfurt": "DE",
    "cologne": "DE", "köln": "DE", "stuttgart": "DE", "düsseldorf": "DE", "leipzig": "DE",
    "karlsruhe": "DE", "dresden": "DE",
    "copenhagen": "DK", "københavn": "DK", "aarhus": "DK", "odense": "DK", "aalborg": "DK",
    "vienna": "AT", "wien": "AT", "brussels": "BE", "antwerp": "BE", "ghent": "BE",
    "paris": "FR", "lyon": "FR", "stockholm": "SE", "gothenburg": "SE", "malmö": "SE",
    "helsinki": "FI", "oslo": "NO", "dublin": "IE", "madrid": "ES", "barcelona": "ES",
    "lisbon": "PT", "porto": "PT", "milan": "IT", "warsaw": "PL", "krakow": "PL",
    "prague": "CZ", "zurich": "CH", "zürich": "CH", "geneva": "CH", "luxembourg": "LU",
    "tallinn": "EE", "riga": "LV", "vilnius": "LT", "budapest": "HU", "bucharest": "RO",
    "athens": "GR", "reykjavik": "IS",
}


def detect_country(location, hint=""):
    """Return an EU country code, 'EU' for EU-wide remote, or '' (drop)."""
    loc = (location or "").lower()
    for name, cc in COUNTRY_NAMES.items():
        if name in loc:
            return cc
    for city, cc in CITY_TO_CC.items():
        if city in loc:
            return cc
    if "remote" in loc and any(k in loc for k in ("europe", "emea", " eu", "eu ")):
        return "EU"
    hint = (hint or "").upper()
    if hint in EU and not loc:
        return hint
    if hint in EU and loc:
        return hint  # source is country-specific; trust it
    return ""


def strip_html(s):
    if not s:
        return ""
    text = BeautifulSoup(html.unescape(s), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _job(title, company, location, url, desc, source, posted="", country=""):
    return {
        "title": (title or "").strip()[:160],
        "company": (company or "").strip()[:120],
        "location": (location or "").strip()[:120],
        "url": (url or "").strip(),
        "desc": strip_html(desc)[:1200],
        "source": source,
        "posted": posted or "",
        "country": country,
    }


def _queries(profile, config):
    q = [t for t in profile.get("titles", []) if t][:3]
    return q or config.get("fallback_titles", ["software engineer"])[:3]


def _title_match(profile, title):
    words = set()
    for t in profile.get("titles", []) + profile.get("skills", []):
        words.update(w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 2)
    if not words:
        return True
    tl = set(re.findall(r"[a-z]+", title.lower()))
    return bool(words & tl)


# ---------------------------------------------------------------- sources

def arbeitnow():
    """Free API, Germany-focused, has an explicit visa_sponsorship flag."""
    out = []
    for page in range(1, 4):
        r = S.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, timeout=30)
        r.raise_for_status()
        for d in r.json().get("data", []):
            posted = ""
            if d.get("created_at"):
                posted = datetime.fromtimestamp(d["created_at"], tz=timezone.utc).date().isoformat()
            j = _job(d.get("title"), d.get("company_name"), d.get("location"), d.get("url"),
                     d.get("description"), "Arbeitnow", posted, "DE")
            j["visa_flag"] = bool(d.get("visa_sponsorship"))
            out.append(j)
        time.sleep(0.3)
    return out


def adzuna(profile, config):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY secrets not set (optional source)")
    out = []
    for cc in config.get("adzuna_countries", ["nl", "de"]):
        for q in _queries(profile, config):
            r = S.get(
                f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": 50,
                        "what": q, "max_days_old": 45, "sort_by": "date"},
                timeout=30,
            )
            if r.status_code != 200:
                continue
            for d in r.json().get("results", []):
                out.append(_job(d.get("title"), (d.get("company") or {}).get("display_name"),
                                (d.get("location") or {}).get("display_name"),
                                d.get("redirect_url"), d.get("description"), "Adzuna",
                                (d.get("created") or "")[:10], cc.upper()))
            time.sleep(0.3)
    return out


def jooble(profile, config):
    key = os.environ.get("JOOBLE_KEY")
    if not key:
        raise RuntimeError("JOOBLE_KEY secret not set (optional source)")
    out = []
    for loc in config.get("jooble_locations", ["Denmark", "Netherlands", "Germany"]):
        for q in _queries(profile, config)[:2]:
            r = S.post(f"https://jooble.org/api/{key}",
                       json={"keywords": q, "location": loc, "page": "1"}, timeout=30)
            if r.status_code != 200:
                continue
            for d in r.json().get("jobs", []):
                out.append(_job(d.get("title"), d.get("company"), d.get("location") or loc,
                                d.get("link"), d.get("snippet"), "Jooble",
                                (d.get("updated") or "")[:10]))
            time.sleep(0.3)
    return out


def themuse(config):
    locs = config.get("muse_locations", ["Amsterdam, Netherlands", "Berlin, Germany",
                                         "Copenhagen, Denmark"])
    out = []
    for page in range(0, 2):
        params = [("page", page)] + [("location", l) for l in locs]
        r = S.get("https://www.themuse.com/api/public/jobs", params=params, timeout=30)
        r.raise_for_status()
        for d in r.json().get("results", []):
            loc = (d.get("locations") or [{}])[0].get("name", "")
            out.append(_job(d.get("name"), (d.get("company") or {}).get("name"), loc,
                            (d.get("refs") or {}).get("landing_page"), d.get("contents"),
                            "The Muse", (d.get("publication_date") or "")[:10]))
    return out


def ats_boards(profile):
    """Direct company career boards (Greenhouse / Lever / Ashby public JSON).
    Companies listed in companies.yml; invalid slugs are skipped silently."""
    companies = yaml.safe_load((ROOT / "companies.yml").read_text(encoding="utf-8")) or []
    out = []
    for c in companies:
        try:
            got = _fetch_board(c)
        except Exception:
            continue
        kept = 0
        for j in got:
            if kept >= 40:
                break
            if _title_match(profile, j["title"]) and detect_country(j["location"], c.get("country", "")):
                j["country"] = j["country"] or c.get("country", "")
                out.append(j)
                kept += 1
        time.sleep(0.2)
    return out


def _fetch_board(c):
    name, ats, slug = c["name"], c["ats"], c["slug"]
    src = f"{name} careers"
    out = []
    if ats == "greenhouse":
        r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                  params={"content": "true"}, timeout=30)
        r.raise_for_status()
        for d in r.json().get("jobs", []):
            out.append(_job(d.get("title"), name, (d.get("location") or {}).get("name"),
                            d.get("absolute_url"), d.get("content"), src,
                            (d.get("updated_at") or "")[:10]))
    elif ats == "lever":
        r = S.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=30)
        r.raise_for_status()
        for d in r.json():
            posted = ""
            if d.get("createdAt"):
                posted = datetime.fromtimestamp(d["createdAt"] / 1000, tz=timezone.utc).date().isoformat()
            out.append(_job(d.get("text"), name, (d.get("categories") or {}).get("location"),
                            d.get("hostedUrl"), d.get("descriptionPlain"), src, posted))
    elif ats == "ashby":
        r = S.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=30)
        r.raise_for_status()
        for d in r.json().get("jobs", []):
            out.append(_job(d.get("title"), name, d.get("location"), d.get("jobUrl"),
                            d.get("descriptionPlain") or d.get("descriptionHtml"), src))
    return out


def relocate_me():
    """Gray-area scrape: relocation/visa-focused job board. Best effort."""
    r = S.get("https://relocate.me/search", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()
    for a in soup.select('a[href^="/jobs/"]'):
        href = a.get("href", "")
        title = a.get_text(" ", strip=True)
        if href in seen or len(title) < 6:
            continue
        seen.add(href)
        card = a.find_parent("li") or a.find_parent("div") or a
        ctx = card.get_text(" ", strip=True)[:200]
        j = _job(title, "via Relocate.me", ctx, "https://relocate.me" + href, "",
                 "Relocate.me")
        j["visa_flag"] = True  # entire board is relocation/visa-focused
        out.append(j)
        if len(out) >= 60:
            break
    if not out:
        raise RuntimeError("no listings parsed (layout changed or blocked)")
    return out


def iamexpat():
    """Gray-area scrape: expat job boards for NL and DE. Best effort."""
    out = []
    for base, path, cc in [("https://www.iamexpat.nl", "/career/jobs-netherlands", "NL"),
                           ("https://www.iamexpat.de", "/career/jobs-germany", "DE")]:
        try:
            r = S.get(base + path, timeout=30)
            r.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.select(f'a[href*="{path}/"]'):
            href = a.get("href", "")
            title = a.get_text(" ", strip=True)
            if href in seen or len(title) < 6 or href.rstrip("/") == path:
                continue
            seen.add(href)
            url = href if href.startswith("http") else base + href
            out.append(_job(title, "via IamExpat", cc, url, "", "IamExpat", country=cc))
            if len(seen) >= 60:
                break
    if not out:
        raise RuntimeError("no listings parsed (layout changed or blocked)")
    return out


def fetch_all(profile, config):
    fetchers = [
        ("company_boards", lambda: ats_boards(profile)),
        ("arbeitnow", arbeitnow),
        ("adzuna", lambda: adzuna(profile, config)),
        ("jooble", lambda: jooble(profile, config)),
        ("themuse", lambda: themuse(config)),
        ("relocate_me", relocate_me),
        ("iamexpat", iamexpat),
    ]
    jobs, health = [], {}
    for name, fn in fetchers:
        try:
            got = fn()
            jobs.extend(got)
            health[name] = {"ok": True, "count": len(got)}
        except Exception as e:
            health[name] = {"ok": False, "count": 0, "error": str(e)[:200]}
        print(name, health[name])
    return jobs, health
