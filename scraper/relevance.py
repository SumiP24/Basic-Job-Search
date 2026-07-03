"""CV analysis + job relevance scoring via the Anthropic API (Haiku; only new jobs are scored)."""
import json
import os
import re

import requests

API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"


def _ask(prompt, max_tokens=2000):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    r = requests.post(
        API, timeout=180,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]},
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", [])
                   if b.get("type") == "text")


def _parse_json(text, default):
    if not text:
        return default
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    try:
        return json.loads(m.group(0)) if m else default
    except Exception:
        return default


def extract_profile(cv_text):
    """CV -> search profile used to query the job APIs."""
    try:
        out = _ask(
            "Extract a job-search profile from this CV. Reply with ONLY minified JSON, "
            'no other text: {"titles":["up to 5 job titles to search for"],'
            '"skills":["up to 12 key skills"],"seniority":"junior|mid|senior|lead"}\n\nCV:\n'
            + cv_text[:8000], max_tokens=500)
    except Exception as e:
        print("profile extraction failed:", e)
        return None
    p = _parse_json(out, None)
    return p if isinstance(p, dict) and p.get("titles") else None


def score_jobs(cv_text, jobs):
    """Score jobs 0-100 against the CV in batches of 10. Returns {id: {score, why}}."""
    results = {}
    for i in range(0, len(jobs), 10):
        batch = jobs[i:i + 10]
        lines = "\n".join(
            f'{j["id"]} | {j["title"]} | {j["company"]} | {j.get("desc", "")[:350]}'
            for j in batch)
        try:
            out = _ask(
                "Score how well each job matches this CV on 0-100 (100 = ideal next role). "
                "Consider skills overlap, seniority fit and domain. Reply with ONLY a JSON "
                'array, no other text: [{"id":"...","score":0,"why":"max 12 words"}]\n\nCV:\n'
                + cv_text[:6000] + "\n\nJOBS (id | title | company | description):\n" + lines)
        except Exception as e:
            print("scoring batch failed:", e)
            continue
        for r in _parse_json(out, []):
            if not isinstance(r, dict) or not r.get("id"):
                continue
            try:
                s = max(0, min(100, int(r.get("score", 0))))
            except (TypeError, ValueError):
                s = 0
            results[str(r["id"])] = {"score": s, "why": str(r.get("why", ""))[:120]}
    return results
