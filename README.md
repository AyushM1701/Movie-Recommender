# CineMatch

CineMatch combines movie discovery, regional watch availability, and a personal film library. The frontend uses vanilla JavaScript and a dark, poster-led layout; the backend uses FastAPI, SQLite or PostgreSQL, and TF-IDF plus latent semantic retrieval.

The published catalog contains **56,542 searchable titles**, including **54,461 titles with recommendation features**. Its release-date cutoff is **September 30, 2026**. The live refresh covers TMDB non-adult, non-video movies across all languages and countries with primary release dates between January 1 and September 30, 2026. Historical coverage comes from the bundled sources; this does not claim every movie ever released.

## Product behavior

- Explore the complete indexed catalog with genre, decade, rating, sorting, and pagination controls, including films before 1970.
- Search by title or plot/theme. The interface distinguishes exact, partial, theme, and empty results.
- Discover similar movies, blend explicit seeds with genres, or use saved viewing history and ratings. Watched exclusions apply to the full history; dislikes influence recommendations.
- Keep a watched shelf, watchlist, private notes, ratings, and curated lists. Owners can edit private lists; public lists have a separate share route.
- Select a watch country (India by default). Browsing cards show one provider; movie details show every provider, availability timestamps, trailers, and cast.
- Watch links open TMDB regional availability pages powered by JustWatch. They are availability links, not guaranteed direct playback links.

## Run locally

Use Python **3.13**; deployment and CI pin the patch in `.python-version`. Local verification used Python 3.13.3 and Node 22.16.0. Node is needed only for frontend tests.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.lock
Copy-Item .env.example .env
.venv/Scripts/python -m backend.data_preprocessing
.venv/Scripts/python -m uvicorn backend.main:app --reload
```

On macOS/Linux, use `.venv/bin/python`. Open [localhost:8000](http://127.0.0.1:8000). Set a random `CINEMATCH_SECRET_KEY`; production refuses an unset signing key. Leave `CINEMATCH_DATABASE_URL` unset for local SQLite, or configure PostgreSQL explicitly. Never point tests at a personal or production database.

The **15 MB compressed catalog seed** in `data/catalog_seed_v1.csv.gz`, with its provenance JSON, supports a clean offline build. The 650 MB raw source is optional and ignored. A TMDB key enables live details, availability, poster lookup, and refreshes; offline catalog browsing does not require it. See `.env.example`. Secrets and personal databases are ignored.

## Refresh and model publication

```powershell
.venv/Scripts/python -m backend.fetch_latest_movies --help
.venv/Scripts/python -m backend.fetch_latest_movies --start 2026-01-01 --end 2026-09-30
.venv/Scripts/python -m backend.data_preprocessing
```

The refresh CLI supports explicit start and cutoff dates and checkpoint controls; consult `--help` for the arguments. Discovery walks all result pages and splits date windows when API limits or count discrepancies require it. Detail and credit requests resume from checkpoints. Invalid, adult, video, and out-of-scope records are excluded with coverage evidence. Failed refreshes preserve the previous active pair.

Refreshes publish immutable paired movie/credit generations. Model builds publish a matching SQLite catalog, aligned IDs, sparse vectors, normalized semantic vectors, checksums, and a manifest. An atomic pointer activates a validated generation. The running process pins that catalog/model pair; restart after building to load it. Corrupt generations fail startup instead of silently loading unrelated files.

The September refresh discovered 34,546 IDs and published 34,520 valid movie details. Twenty-six IDs had detail metadata outside the release scope. One valid movie's credit/keyword endpoints returned 404; that missing source data is recorded. See [coverage evidence](data/catalog_refresh_2026-09-30.json).

Field weights favor plot text (1.8), then keywords (1.0), cast/director metadata (0.8), and genres (0.75). Default semantic retrieval uses reproducible 256-dimensional LSA, fitted without genre columns. Optional neural embeddings require `backend/requirements-semantic.txt` and an explicitly selected backend.

## Verification

```powershell
.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
.venv/Scripts/python -m ruff check backend
.venv/Scripts/python -m ruff format --check backend
.venv/Scripts/python -m compileall -q backend
.venv/Scripts/python -m unittest discover -s backend/tests -v
node --check frontend/assets/app.js
node --test frontend/tests/*.test.mjs
.venv/Scripts/python -m pip check
```

Tests use disposable databases and deterministic recommendation fixtures. PostgreSQL migration tests opt in through `CINEMATCH_TEST_POSTGRES_URL`, which must identify a disposable database. Windows and Ubuntu CI also rebuild artifacts offline from the compact seed.

```powershell
.venv/Scripts/python -m backend.evaluate_recommender --sample-size 50 --top-k 10 --seed 42 --compare-baselines --output docs/verification/recommender-evaluation.json
```

The evaluation labels its genre/keyword relevance measure as an **attribute proxy**, compares the same samples against genre and popularity baselines, and calculates recall against the full eligible pool. It does not measure human satisfaction. `--interactions-csv` accepts interaction data for held-out evaluation; no human interaction dataset was available for this implementation.

Read [PROJECT_AUDIT.md](PROJECT_AUDIT.md), [the approved specification](docs/superpowers/specs/2026-09-30-cinematch-remediation-design.md), and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for the audit and finding-level evidence.

## API and deployment

Interactive API documentation is at `/docs`. `/health` reports process/catalog information; `/ready` checks the model, catalog, migrations, and personal database schema. Catalog endpoints include `/catalog`, `/catalog/metadata`, `/search`, `/movies/{id}/details`, and `/movies/{id}/similar`. Watch availability uses `/watch/countries` and `/watch/options`; authenticated routes manage profiles, libraries, lists, exports, and personal recommendations.

`render.yaml` uses locked runtime dependencies, an offline model build, one Gunicorn/Uvicorn worker, and `/ready`. Configure production signing, TMDB, and database credentials in the deployment environment. The implementation was verified locally; it has not been deployed or run through hosted CI.
