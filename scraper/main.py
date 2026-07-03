"""Orchestrator: fetch -> EU filter -> dedupe -> visa -> relevance -> link check -> publish."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import linkcheck, relevance, sources, visa

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
OUT = DOCS / "jobs.json"
CACHE = DATA / "score_cache.json"


def _load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _job_id(j):
    key = f"{j['title']}|{j['company']}|{j.get('country', '')}".lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def run():
    DOCS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    config = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8")) or {}
    cv_text = os.environ.get("CV_TEXT", "").strip()
    cv_hash = hashlib.sha256(cv_text.encode()).hexdigest()[:12] if cv_text else ""

    profile = relevance.extract_profile(cv_text) if cv_text else None
    if not profile:
        profile = {"titles": config.get("fallback_titles", []), "skills": [], "seniority": ""}
    print("Profile titles:", profile.get("titles"))

    raw, health = sources.fetch_all(profile, config)
    print(f"Fetched {len(raw)} raw postings")

    # EU filter + dedupe (title|company|country).
    seen = {}
    for j in raw:
        j["country"] = sources.detect_country(j.get("location", ""), j.get("country", ""))
        if not j["country"] or not j.get("title") or not j.get("url"):
            continue
            if j["source"] in {"Arbeitnow", "The Muse", "Relocate.me", "IamExpat"} \
                and not sources._title_match(profile, j["title"]):
            continue
        j["id"] = _job_id(j)
        seen.setdefault(j["id"], j)
    jobs = list(seen.values())
    print(f"{len(jobs)} EU jobs after dedupe")

    registries = visa.load_registries(DATA)
    for j in jobs:
        j["visa"] = visa.score(j, registries)

    prev = _load_json(OUT, {})
    prev_jobs = {p["id"]: p for p in prev.get("jobs", [])}
    cache = _load_json(CACHE, {})
    if prev.get("meta", {}).get("cv_hash") != cv_hash:
        cache = {}  # CV changed -> rescore everything

    today = datetime.now(timezone.utc).date().isoformat()
    to_score, to_check = [], []
    for j in jobs:
        old = prev_jobs.get(j["id"])
        j["first_seen"] = old.get("first_seen", today) if old else today
        cached = cache.get(j["id"])
        if cached:
            j["relevance"] = {"score": cached["score"], "why": cached["why"]}
        else:
            to_score.append(j)
        if not old:
            to_check.append(j)

    if cv_text and to_score:
        print(f"Scoring {len(to_score)} new jobs against CV")
        scored = relevance.score_jobs(cv_text, to_score)
        for j in to_score:
            j["relevance"] = scored.get(j["id"], {"score": 0, "why": "not scored"})
    else:
        for j in to_score:
            j["relevance"] = {"score": 0, "why": "no CV configured"}

    dead = linkcheck.dead_urls([j["url"] for j in to_check])
    jobs = [j for j in jobs if j["url"] not in dead]
    print(f"Dropped {len(dead)} dead links")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    for j in jobs:
        cache[j["id"]] = {"score": j["relevance"]["score"], "why": j["relevance"]["why"], "ts": now_iso}
    cutoff = (now - timedelta(days=60)).isoformat(timespec="seconds")
    cache = {k: v for k, v in cache.items() if v.get("ts", now_iso) >= cutoff}

    jobs.sort(key=lambda j: j["first_seen"], reverse=True)
    jobs.sort(key=lambda j: j["relevance"]["score"], reverse=True)

    out = {
        "meta": {
            "updated_at": now_iso,
            "cv_hash": cv_hash,
            "total": len(jobs),
            "sources": health,
        },
        "jobs": [
            {
                "id": j["id"], "title": j["title"], "company": j["company"],
                "location": j.get("location", ""), "country": j["country"],
                "url": j["url"], "source": j["source"], "posted": j.get("posted", ""),
                "first_seen": j["first_seen"], "visa": j["visa"],
                "relevance": j["relevance"], "desc": j.get("desc", "")[:1200],
            }
            for j in jobs
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    print(f"Published {len(jobs)} jobs -> {OUT}")


if __name__ == "__main__":
    run()
