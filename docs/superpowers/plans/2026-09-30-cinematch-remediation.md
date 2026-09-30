# CineMatch Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix F01–F43 and deliver the reference-inspired UI, regional watch options, and a verified catalog through 30 September 2026.

**Architecture:** Keep FastAPI/SQLAlchemy and vanilla JavaScript. Separate the indexed catalog and immutable model generations from personal data. Delegate independent file domains with explicit contracts; integrate and review the resulting working tree centrally.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pandas/SciPy/scikit-learn, unittest, HTML/CSS/JavaScript, TMDB.

**Spec:** `docs/superpowers/specs/2026-09-30-cinematch-remediation-design.md`.

## Global Constraints

- India (`IN`) is the default country; offer a country selector.
- The cutoff is 30 September 2026; preserve existing historical films and personal data.
- Every movie card includes watch options with JustWatch/TMDB attribution; no invented direct playback availability or personal/critics scores.
- Explicit quality filters are strict; full watched-ID exclusions are independent of bounded profiling history.
- Preserve the existing dirty working tree; do not reset, stash, stage, or commit unrelated user changes.
- Run behavior tests on disposable databases; stub external requests except the explicitly required real catalog refresh.
- Latest user instruction authorizes starting implementation now. Ruling: execute without further spec/plan approval prompts, respecting the user's repeated direct instruction.

## Review Focus

- Country change during in-flight availability loading: only the latest country paints results (Task 6).
- A missing-field or zero-vote recent film: remains in title search/browse without a fake rating (Tasks 1, 3, 6).
- Existing library item missing from a new catalog: remains accessible and exportable (Task 4).
- Refresh interruption between metadata and credits/model files: previous generation stays usable (Tasks 1, 2).
- A profile larger than 200 entries with only negative ratings: full exclusions and dislike influence remain active (Tasks 3, 4).

## Shared Interfaces and Ownership

- Data domain: `backend/catalog.py`, `backend/artifacts.py`, preprocessing/refresh modules, data/artifact tests, generated snapshots. CatalogRepository(path: Path | None = None) exposes `get_movie(movie_id: int) -> dict | None`, `search_titles(query: str, limit: int = 12) -> list[dict]`, `browse(page=1, page_size=24, genre=None, year_from=None, year_to=None, sort="popular") -> dict`, `stats() -> dict`, and `metadata() -> dict`. Movie dictionaries include the existing MovieOut fields plus optional release_date/backdrop_path/credits. `backend.artifacts.active_model_dir(model_root: Path) -> Path` resolves and validates a published generation or allows explicitly identified legacy models.
- Backend domain: main/schemas/auth/database/config/tmdb/posters modules and its new tests. `/catalog` accepts the browse parameters above and returns `{movies,total,page,page_size,pages}`. `/watch/countries` returns `{countries:[{code,name}],default_country:"IN"}`. `POST /watch/options` accepts `{movie_ids:[int],country:"IN"}` and returns `{country,movies:[{movie_id,country,status,link,providers:[{id,name,logo_path,types}],checked_at}]}`. Status is `available`, `not_listed`, or `unavailable`. Every valid movie has an HTTPS availability-page link; provider chips use that link.
- Root owns `backend/recommender.py`, evaluator, recommender regression tests, dependency/CI/deploy files, README, plan/progress/finding ledger and integration.
- Frontend domain owns `frontend/**`, PRODUCT.md and DESIGN.md, and frontend tests/checks only. It consumes the shared API contracts; authenticated collection routes use page/page_size, totals, stable order, and backwards-compatible existing collection field names. Profile retains `history` as a bounded recent sample and `total_watched` as full count.
- Backend personal recommendations pass `excluded_movie_ids` separately to `RecommendationEngine.recommend_for_user(..., excluded_movie_ids=None)`. Hybrid accepts empty movie_ids when genres supply an effective signal. Genre limits align to all 19 supported genres.

### Task 1: Safe comprehensive catalog refresh (F11, F12, F15, F32)

**Files:** refresh/preprocessing/catalog/artifacts modules; new `backend/tests/test_catalog_pipeline.py`.

**Interfaces:** produces CatalogRepository and compact catalog seed; carries source cutoffs/coverage independently of user data.

- [ ] Write failing tests: empty failed discovery preserves existing files, date-window pagination is exhaustive/deduplicated, missing overview/genre/zero votes survive catalog import, credits merge by ID without loss.
- [ ] Run `python -m unittest backend.tests.test_catalog_pipeline -v`; observe the relevant failures.
- [ ] Implement checkpointed partitioned refresh, validation, atomic generation publication, compact seed and indexed catalog. Bound network concurrency and redact credentials.
- [ ] Repeat the task tests until green; start the real January–September refresh, retaining resumable checkpoints and coverage evidence.

### Task 2: Immutable model generations (F38)

**Files:** `backend/artifacts.py`, preprocessing module, artifact tests.

**Interfaces:** produces `active_model_dir(model_root)` and an atomic active-generation pointer; root recommender consumes it.

- [ ] Write/run failing tests for mixed ordered IDs, feature dimensions, checksums and interrupted publication.
- [ ] Build generation manifests, validate before activation, and leave old generation intact on error.
- [ ] Run pipeline/artifact tests, build the full refreshed generation, and inspect memory and coverage.

### Task 3: Recommendation/search correctness (F01–F05, F13, F16, F17)

**Files:** recommender, evaluator, `backend/tests/test_recommender_regressions.py`, existing quality tests.

**Interfaces:** add independent exclusions; load verified active models; enrich title lookup via the catalog without erasing low-vote recent titles.

- [ ] Write/run failures for sparse theme search, impossible strict thresholds, negative-only exclusions/influence, full independent exclusions, genre-only/seed-only hybrids, exact/partial/no-signal search, and recall denominator.
- [ ] Correct those behaviors; tune plot emphasis and diversification using comparison fixtures rather than self-referential quality claims.
- [ ] Run targeted tests, preserve franchise fixtures, compare deterministic evaluation with popular/genre baselines, and report evidence limitations.

### Task 4: Authentication, migrations and personal-library integrity (F14, F20, F26–F29, F35–F37, F39)

**Files:** auth/database/schemas/main, new backend regression/migration tests.

**Interfaces:** session-version authentication, canonical catalog writes, complete exclusions, pagination, owner-only list management.

- [ ] Write/run failures for first-connection SQLite pragmas, password old-token rejection, nullable PATCH, malformed metadata, whitespace list titles, every watched/watchlist branch, duplicate writes, legacy migrations, private owners/nonowners and multiple pages.
- [ ] Implement dialect-aware versioned migration and backup, shared password checks, transactions/rollback, controlled conflicts/readiness and canonical metadata resolution.
- [ ] Add owner list GET/PATCH and bounded collection endpoints; preserve unresolved existing entries and full exports.
- [ ] Run backend regression tests with disposable data and SQLite legacy fixtures. Run PostgreSQL execution only against an available disposable service; otherwise retain explicit limitation.

### Task 5: Regional media/watch service (F33, F34 plus new watch feature)

**Files:** tmdb/posters/main/schemas/config, media-service tests.

**Interfaces:** `/watch/countries`, `/watch/options` above, optional watch_options in details, bounded per-key caches.

- [ ] Write/run failures for transient recovery, successful TTL expiry, cache capacity, per-key request deduplication and different-key concurrency.
- [ ] Parse regional provider types, watch-page links and timestamps; enforce 50-ID batch limit and valid countries; supply local-credit fallback.
- [ ] Run stubbed media tests and a live read-only India availability check.

### Task 6: Reference-inspired resilient frontend (F06–F09, F18–F25, F30–F32, F42, F43)

**Files:** frontend HTML/CSS/JS, product/design docs, frontend regression checks.

**Interfaces:** consumes catalogue/watch endpoints and paginated library/list routes above; retains existing product workflows.

- [ ] Capture regression evidence for keyboard suggestions, dialog stack, mobile drawer, stale async state, labels, genre state and contrast before implementing.
- [ ] Consolidate design tokens and replace affected composition: warm dark split feature, red shelf headings, teal rating rings, poster shelves and safe-area bottom navigation.
- [ ] Render watch links on every movie card; batch visible provider enrichment, expose country changes/status and attribution without fictional playback links.
- [ ] Implement independent request/state ownership, URL/history routing, complementary hybrid slider/source picker, labelled forms, in-place chips, accessible editors/list management and bounded pagination.
- [ ] Run JavaScript syntax/regression checks; root verifies live keyboard/desktop/mobile/error/reduced-motion workflows in one batched inspection and one confirmation round.

### Task 7: Reproducible tooling/deployment (F10, F40, F41)

**Files:** requirements/lock/dev checks, Render/Python config, CI, README and environment examples.

**Interfaces:** documented static-check → lint → tests → build commands using reproducible compatible dependencies and a compact/offline seed.

- [ ] Establish behavior checks for a clean model build without the raw source and hermetic API tests without TMDB/model side effects.
- [ ] Correct Blueprint runtime; pin runtime/dependencies, add minimal CI checks and document coverage/fallback/deployment semantics.
- [ ] Verify fresh install, dependency consistency, all regression tests, and a separate clean-source build.

### Task 8: Integration, audit ledger and final review

**Files:** `IMPLEMENTATION_STATUS.md`, validation evidence and final report.

**Interfaces:** records every F01–F43 status, changed area and concrete verification result.

- [ ] Inspect all domain diffs and reconcile contracts; run static checks, lint, tests and complete build.
- [ ] Verify live application with disposable personal data at mobile/desktop, including real catalog cutoffs/watch links and performance.
- [ ] Obtain one fresh independent code review of the whole working-tree implementation. Reproduce/fix important findings and rerun relevant checks.
- [ ] Record actual catalog counts/coverage, screenshots, test results and conditional limitations. Commit only scoped changes when safe; do not claim all findings resolved without evidence.
