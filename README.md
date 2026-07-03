# EU Job Radar

Personal dashboard for EU jobs (NL / DE / DK preferred, all EU included). GitHub Actions fetches jobs daily, scores each posting against your CV with Claude, estimates visa-sponsorship probability, verifies every apply link, and publishes a static dashboard on GitHub Pages.

## Setup (one time, ~10 min)

1. **Create a GitHub repo** and push this folder's contents (repo must be public for free GitHub Pages).
2. **Repo → Settings → Secrets and variables → Actions**, add:

   | Secret | Required | Where to get it |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | yes (for CV analysis + relevance scores) | console.anthropic.com |
   | `CV_TEXT` | yes — paste your full CV as plain text | — |
   | `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | optional, adds NL/DE/AT/BE/SE/FR coverage | free at developer.adzuna.com |
   | `JOOBLE_KEY` | optional, adds Denmark + more EU coverage | free at jooble.org/api/about |

3. **Settings → Pages** → Deploy from a branch → `main`, folder `/docs`.
4. **Actions tab** → "Daily job scrape" → *Run workflow* (first run also happens automatically at 05:00 UTC daily; edit the cron in `.github/workflows/daily.yml`).
5. Open `https://<username>.github.io/<repo>/`. In the dashboard's **Settings**, paste your Anthropic key + CV once — used only by the *Tailor CV* button and stored only in your browser.

## Sources

| Source | Type | Notes |
|---|---|---|
| Company career boards | Greenhouse / Lever / Ashby public JSON | List in `companies.yml` — extend freely; wrong slugs are skipped automatically |
| Arbeitnow | free API | Germany; has an explicit visa-sponsorship flag |
| Adzuna | API (free key) | NL, DE, AT, BE, SE, FR (no DK coverage) |
| Jooble | API (free key) | DK, NL, DE |
| The Muse | free API | Major EU cities |
| Relocate.me, IamExpat | HTML scrape (gray-area) | May break or block at any time — failures show as a red dot in the dashboard header and never stop the pipeline |

LinkedIn and Indeed are deliberately excluded: scraping them violates their ToS and is bot-blocked from CI runners.

## How the numbers work

- **Relevance (0–100)** — Claude Haiku scores each *new* posting against `CV_TEXT`; scores are cached, so daily cost is typically a few cents. Changing `CV_TEXT` rescores everything.
- **Visa probability** — High / Medium / Low / Unknown / Unlikely, from: source-level sponsorship flags, the NL IND recognised-sponsor register and DK certified fast-track list (fetched live, bundled fallback lists in `data/` if the fetch fails), and positive/negative keywords in the posting. It is an estimate — always verify with the employer.
- **Links** — new postings are HTTP-verified; confirmed-dead links (404/410) are dropped before publishing.

## Privacy

Your CV lives only in the `CV_TEXT` GitHub secret and your own browser. The public repo contains job data and numeric scores only.
