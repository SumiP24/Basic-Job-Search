"""Visa sponsorship probability.

Signals, strongest first:
1. Source-level flag (e.g. Arbeitnow visa_sponsorship, Relocate.me board).
2. Official registries: NL IND recognised sponsors, DK certified fast-track companies.
   Fetched live; bundled fallback lists are used if the fetch fails.
3. Positive / negative keywords in title + description.
Output is a probability estimate, never a guarantee.
"""
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 JobRadar/1.0"}

NL_URL = "https://ind.nl/en/public-register-recognised-sponsors"
DK_URL = "https://www.nyidanmark.dk/en-GB/Words-and-Concepts-Front-Page/SIRI/Certified-companies"

POSITIVE = [
    "visa sponsorship", "sponsorship available", "we sponsor", "sponsor your visa",
    "visa support", "work permit", "work visa", "relocation package", "relocation support",
    "relocation assistance", "relocation bonus", "relocation budget", "blue card",
    "bluecard", "kennismigrant", "highly skilled migrant", "30% ruling", "30% facility",
    "international candidates", "candidates from abroad", "hire internationally",
]
NEGATIVE = [
    "no visa", "cannot sponsor", "unable to sponsor", "not able to sponsor",
    "no sponsorship", "without sponsorship", "no relocation", "not offer relocation",
    "must be eligible to work", "right to work in", "valid work permit required",
    "eu citizens only", "eu work permit", "already based in", "must be located in",
    "must reside in",
]

_SUFFIX = re.compile(
    r"\b(b\.?v\.?|n\.?v\.?|gmbh|ag|se|a/s|aps|inc|llc|ltd|holding|group|international"
    r"|nederland|netherlands|deutschland|europe)\b\.?", re.I)


def _norm(name):
    n = _SUFFIX.sub("", (name or "").lower())
    return re.sub(r"[^a-z0-9 ]+", " ", n).strip()


def _fetch_registry(url, fallback: Path):
    names = set()
    try:
        r = requests.get(url, timeout=40, headers=UA)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for el in soup.select("td, li"):
            t = el.get_text(" ", strip=True)
            if 3 < len(t) < 80 and not t.lower().startswith(("http", "www", "read", "more")):
                n = _norm(t)
                if len(n) > 3:
                    names.add(n)
    except Exception:
        pass
    if len(names) < 50 and fallback.exists():  # fetch failed or page too thin
        for line in fallback.read_text(encoding="utf-8").splitlines():
            n = _norm(line)
            if len(n) > 3:
                names.add(n)
    return names


def load_registries(data_dir: Path):
    return {
        "NL": _fetch_registry(NL_URL, data_dir / "nl_sponsors_fallback.txt"),
        "DK": _fetch_registry(DK_URL, data_dir / "dk_certified_fallback.txt"),
    }


def _in_registry(company, rset):
    c = _norm(company)
    if not c or not rset:
        return False
    if c in rset:
        return True
    return any(len(n) > 4 and (n in c or c in n) for n in rset)


def score(job, registries):
    text = f"{job.get('title', '')} {job.get('desc', '')}".lower()
    pts, reasons = 0, []

    if job.pop("visa_flag", False):
        pts += 60
        reasons.append("Job board explicitly flags visa sponsorship / relocation")

    cc = job.get("country", "")
    if _in_registry(job.get("company", ""), registries.get(cc, set())):
        pts += 60
        reasons.append({"NL": "Company is on the NL IND recognised-sponsor register",
                        "DK": "Company is on the DK certified fast-track list"}[cc])

    hits = [k for k in POSITIVE if k in text]
    if hits:
        pts += min(3, len(hits)) * 15
        reasons.append("Posting mentions: " + ", ".join(hits[:3]))

    neg = [k for k in NEGATIVE if k in text]
    if neg:
        pts = min(pts, 8)
        reasons = ["Posting indicates no sponsorship / local right-to-work required "
                   f"(\u201c{neg[0]}\u201d)"]

    if not reasons:
        pts = 10
        reasons = ["No sponsorship information in the posting"]

    pts = min(pts, 98)
    if neg:
        level = "Unlikely"
    elif pts >= 60:
        level = "High"
    elif pts >= 30:
        level = "Medium"
    elif pts > 10:
        level = "Low"
    else:
        level = "Unknown"
    return {"score": pts, "level": level, "reasons": reasons}
