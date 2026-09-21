# HKJC Predictor

Python CLI that builds **Hong Kong Jockey Club (HKJC)** tip sheets from **fundamental condition analysis only**.

**No odds, pools, or dividends are used anywhere in scoring.** GraphQL payloads may contain `winOdds` / `pmPools` fields; the mapper **strips or ignores** them and never passes them into scoring.

> **DISCLAIMER:** For study and entertainment only. This is **NOT** betting advice.

## Install

```bash
python3 -m venv /workspace/hkjc-predictor/.venv
source /workspace/hkjc-predictor/.venv/bin/activate
pip install -e "/workspace/hkjc-predictor[dev]"
```

## Live schedule via GraphQL (`--live`)

Real meeting schedules come from the public HKJC GraphQL endpoint using the **exact whitelisted** `horseQuery` (bundled as `src/hkjc_predictor/horseQuery.graphql`, from `@gikndue/hkjc-api`). Arbitrary custom queries return schema errors.

```
POST https://info.cld.hkjc.com/graphql/base/
Headers: Content-Type application/json, Origin/Referer https://bet.hkjc.com, browser User-Agent
```

Venue rules:

- `ST` / `HV` → local path (local weights + `tips_YYYY-MM-DD_ST|HV.*`)
- `S1` / `S2` / `S3` or `meetingType: O` → overseas path (overseas weights + `tips_overseas_*`)

Raw responses are cached under `data/cache/`.

```bash
# Fetch active meeting(s), score all races, write tip sheets, rebuild pages
python -m hkjc_predictor --live

# Default (no flags): try --live first; if no runners, fall back to local demo with a clear message
python -m hkjc_predictor
```

When the only active meeting is overseas (e.g. **2026-09-19 S1 Australia / Caulfield**), `--live` writes the overseas tip sheet + `overseas.html`. If no local card is declared, `local.html` notes the next guessed local fixture.

## Run (local HK)

```bash
# Offline demo (sample Happy Valley 2-race card)
python -m hkjc_predictor --demo

# Live local fetch (GraphQL preferred, HTML RaceCard fallback)
python -m hkjc_predictor --date 2026-09-23 --venue HV

# Options
python -m hkjc_predictor --demo --race 1 --config config/weights.yaml --output output/
```

Tip sheets are written as Markdown and plain text under `output/` (e.g. `tips_2026-09-17_HV.md`).

## Overseas / Simulcast (separate page & data path)

Overseas (simulcast) races use a **separate package, weights file, tip-sheet stem, and HTML page** from local HV/ST cards.

### Why separate?

- Overseas cards historically lived under different URL trees; live data now prefers **GraphQL**.
- Local HV/ST **draw-bias tables do not apply** abroad; overseas scoring uses **generic draw** + form + jockey/trainer + rating/weight + course/distance/going.
- Pluggable source adapters keep HKJC simulcast and future external feeds isolated from local HTML-only paths.

### Adapters

| `--source` | Module | Status |
|------------|--------|--------|
| `hkjc_simulcast` (default) | `overseas/hkjc_simulcast.py` | **GraphQL live** for active overseas meetings; demo JSON always available |
| `external` | `overseas/external.py` | **PLACEHOLDER** stub (Racing Post / Racing.com style — not implemented) |

### How to run overseas

```bash
# Live active overseas via GraphQL (same as --live when only S* is active)
python -m hkjc_predictor --live
python -m hkjc_predictor --overseas --date 2026-09-19

# Offline Japan (JPN) S2-style sample — always works
python -m hkjc_predictor --demo-overseas

# Regenerate static HTML pages from latest tip sheets
python -m hkjc_predictor pages
python -m hkjc_predictor --build-pages
```

### Sample output paths

| Artifact | Path |
|----------|------|
| Overseas tip sheet (md/txt) | `output/tips_overseas_2026-09-19_AUS.md` / `.txt` |
| Pages index (Local \| Overseas nav) | `output/pages/index.html` |
| Local page | `output/pages/local.html` |
| **Overseas page (separate)** | `output/pages/overseas.html` |
| Weights | `config/weights_overseas.yaml` |
| Sample meeting | `data/sample_overseas_meeting.json` |
| GraphQL query | `src/hkjc_predictor/horseQuery.graphql` |
| GraphQL cache | `data/cache/` |

The overseas HTML page shows a **Source** label such as `HKJC GraphQL / real schedule 2026-09-19` and the standard disclaimer.


## Web UI (live refresh)

Small FastAPI app that serves Local / Overseas tip sheets and can refresh from the real HKJC GraphQL schedule (fundamentals only — **no odds**).

### Local run

```bash
source /workspace/hkjc-predictor/.venv/bin/activate
pip install -e "/workspace/hkjc-predictor[dev]"

# Serve on http://0.0.0.0:8080
python -m hkjc_predictor.web
# or
hkjc-web --host 0.0.0.0 --port 8080
```

Open **http://127.0.0.1:8080/** — dashboard with nav **本地 Local | 海外 Overseas**, last-refresh status, and **Refresh live**.

| Route | Purpose |
|-------|---------|
| `GET /` | Dashboard / home + status |
| `GET /local` | Local tip sheet HTML |
| `GET /overseas` | Overseas tip sheet HTML |
| `POST /api/refresh` | Run GraphQL `--live` pipeline; JSON `{ok, meeting, races, refreshed_at, error?}` |
| `GET /api/status` | Last refresh metadata from `data/web_state.json` |

Outbound HTTPS to `https://info.cld.hkjc.com` is required for live refresh.

### Docker

```bash
cd /workspace/hkjc-predictor
docker build -t hkjc-predictor .
docker run --rm -p 8080:8080 hkjc-predictor

# Or with persisted output/cache:
docker compose up --build
```

The container listens on port **8080**. GraphQL live refresh needs outbound HTTPS from the host/container to `info.cld.hkjc.com`.


## Deploy to Cloudflare Pages

Cloudflare Pages serves **static** HTML (no long-running FastAPI). Live HKJC data is refreshed **at build time**; the on-site **Refresh live** button triggers a new Pages build via a Deploy Hook.

### Dashboard settings

| Setting | Value |
|---------|--------|
| **Build command** | `bash scripts/cf_pages_build.sh` |

**If the build fails with a generic “error occurred while running deploy/build command”:**

1. Framework preset = **None** (not Poetry / not auto Python).
2. Build command exactly: `bash scripts/cf_pages_build.sh`
3. Output directory: `dist`
4. Environment variable (optional): `PYTHON_VERSION` = `3.11`
5. Re-deploy after pulling the latest `main` (build no longer uses `venv`; installs via `pip` + `requirements.txt`).

| **Build output directory** | `dist` |
| **Root directory** | `/` (repo root) |

Optional `wrangler.toml` documents the same (`pages_build_output_dir = "dist"`).

### Steps after connecting GitHub

1. **Create a GitHub repo** and push this project (do not commit secrets or `.env`).
2. **Cloudflare Dashboard** → **Workers & Pages** → **Create** → **Connect to Git** → select the repo.
3. Set **Build command** / **Output directory** as above. First deploy will run `--live` during the build (soft-falls back to last known / demo pages if fetch fails).
4. After the first successful deploy:
   - **Settings** → **Deploy hooks** → **Create deploy hook** (e.g. name `refresh`).
   - Copy the hook URL.
   - **Settings** → **Environment variables** → add `DEPLOY_HOOK_URL` = that URL (Production, and Preview if you want).
   - Redeploy once so the Pages Function `functions/api/refresh.js` can read the env var.
5. Open the site → **Refresh live** → POSTs `/api/refresh` → Function POSTs the hook → new build with fresh GraphQL data.
6. **Optional scheduled refresh:** add GitHub Actions secret `CF_DEPLOY_HOOK_URL` (same hook URL). Workflow `.github/workflows/refresh.yml` curls it every 6 hours (and on manual `workflow_dispatch`).

### Local FastAPI vs Cloudflare

| | Local / Docker | Cloudflare Pages |
|--|----------------|------------------|
| App | FastAPI (`python -m hkjc_predictor.web`) | Static `dist/` + Pages Function |
| Refresh | `POST /api/refresh` runs live pipeline in-process | `POST /api/refresh` → Deploy Hook → rebuild |
| Nav | `/`, `/local`, `/overseas` | `index.html`, `local.html`, `overseas.html` |

Both UIs call relative **`/api/refresh`**. Build script uses venv at `.venv` when present (or creates one).

### Build locally (same as CF)

```bash
bash scripts/cf_pages_build.sh
# → dist/index.html, local.html, overseas.html, status.json, tip sheets
```

## Score vs Conf % vs Race confidence

| Metric | What it is |
|--------|------------|
| **Score** (0–100) | Weighted fundamental rating for that horse (form, draw, jockey, etc.). Kept as-is. |
| **Conf %** | Softmax win probability across the race × 100 (1 decimal). How strongly the model backs *this* horse **relative to the field** — not the same as Score. Tunable via `confidence.temperature` in the weights YAML (lower = sharper favourite). |
| **Race confidence** | One 0–100% number (plus High/Med/Low) under each race header. High when top pick is well separated from #2 and the probability mass is concentrated; low when scores are bunched / high-entropy. Uses `gap_scale` and entropy blend in `confidence:` config. |

Fundamentals only — still no odds in scoring.

## Scoring factors (0–100, weighted)

### Local (`config/weights.yaml`)

| Factor | Default weight | What it uses |
|--------|----------------|--------------|
| `recent_form` | 0.28 | Last up to 6 placings; recent starts weighted more |
| `course_distance_fit` | 0.18 | CD / C / D win & place proxies |
| `draw_bias` | 0.12 | HV vs ST × turf vs AWT draw heuristics |
| `jockey` | 0.10 | Name-tier proxy |
| `trainer` | 0.08 | Name-tier proxy |
| `rating` | 0.14 | Official rating vs field + change |
| `weight_claim` | 0.07 | Carried weight & claims |
| `going_gear` | 0.03 | Going preference & gear notes |

### Overseas (`config/weights_overseas.yaml`)

Same factor set, but **`draw_generic`** replaces local HV/ST tables (documented in the tip sheet). Defaults lean slightly more on form / jockey / trainer for unfamiliar tracks.

## Project layout

```
hkjc-predictor/
  pyproject.toml
  README.md
  config/weights.yaml
  config/weights_overseas.yaml
  data/sample_meeting.json
  data/sample_overseas_meeting.json
  data/cache/                  # GraphQL raw caches
  src/hkjc_predictor/
    cli.py fetch.py parse.py score.py report.py models.py
    graphql_client.py horseQuery.graphql
    live.py
    overseas/
      sources.py hkjc_simulcast.py external.py
      score_overseas.py report_overseas.py
    web/
      app.py templates/
  tests/
    fixtures/graphql_s1_caulfield_slice.json
  output/
  output/pages/
  data/web_state.json   # last web refresh meta
  Dockerfile
  docker-compose.yml
  scripts/cf_pages_build.sh
  scripts/prepare_cf_dist.py
  functions/api/refresh.js   # CF Pages Function → deploy hook
  wrangler.toml
  .github/workflows/refresh.yml
  dist/                      # Cloudflare publish dir (generated, gitignored)
```

## Live fetch notes

- **Preferred:** public GraphQL `horseQuery` (fundamentals mapped; odds fields ignored).
- Local HTML `RaceCard.aspx` remains a fallback if GraphQL has no local card.
- Overseas HTML fixture/racecard URLs remain a weak fallback behind GraphQL.
- Prefer `--demo` / `--demo-overseas` when offline.

## Tests

```bash
pytest /workspace/hkjc-predictor/tests -q
```
