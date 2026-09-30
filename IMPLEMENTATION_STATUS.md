# CineMatch implementation evidence

The 43 findings in PROJECT_AUDIT.md have implementation changes and verification evidence below. The approved scope also includes the reference-inspired UI, India-first regional watch links, and a real catalog refresh through September 30, 2026. Work remains in the existing checkout on `codex/audit-remediation`; prior local changes were preserved. GitHub publication is separate from production deployment; no production deployment has been performed.

## Executed verification

- Backend: 92 tests run, 90 passed; two PostgreSQL-only tests skip without an explicit disposable service. The two PostgreSQL migration tests were additionally executed successfully against a disposable PostgreSQL 17 container earlier in this implementation.
- Frontend: 14 tests passed, including actual application functions for reversed search completion, session replacement, modal stacking, chip focus, account pagination, route races, provider cache expiry, and compact/full watch-provider rendering.
- Ruff lint and formatting, Python compilation, JavaScript syntax, and dependency consistency passed.
- A fresh virtual environment installed the exact dependency lock. The source copy excluded `.env`, the 650 MB raw source, personal databases, and prebuilt models. It rebuilt the complete model/catalog offline from the compressed seed, passed the backend suite, and successfully served readiness, search, details, and catalog requests.
- `render.yaml` validates against the [official Render JSON schema](https://render.com/schema/render.yaml.json). Windows/Ubuntu CI is configured but has not run remotely. Local Python was 3.13.3; CI/deployment pin 3.13.15.
- Browser verification exercised mobile navigation/focus, nested modal Escape/focus return, title search/details, signup with disposable data, keyboard autocomplete, private-list creation/edit/reload, and saved-history blend execution. Mobile and desktop layouts were inspected. Compact cards show one provider; details shows all providers. Live links are HTTPS regional availability pages.
- Independent final review confirmed fixes for seven integration regressions, reran relevant backend/frontend cases, and found no actionable regression in that focused scope.

Evidence: [offline build](docs/verification/offline-build.log), [fresh backend tests](docs/verification/offline-tests.log), [fresh startup](docs/verification/clean-startup.json), [frontend tests](docs/verification/frontend-tests.log), [mobile card](docs/verification/watch-card-mobile.jpg), [mobile details](docs/verification/watch-details-mobile.jpg), and [desktop](docs/verification/footer-desktop.jpg).

## Catalog and recommendation evidence

The final catalog has 56,542 indexed titles spanning 1888–2026, with 51,077 posters. The model contains 54,461 movies, a 54,461 × 70,019 sparse matrix, and 256-dimensional LSA embeddings. It retains 29,832 cast-bearing and 35,135 director-bearing model rows. The Windows preview used approximately 447 MB resident/peak process memory after startup and browser requests; this is a local observation, not a deployment load test.

The live discovery traversed the complete January 1–September 30, 2026 TMDB non-adult, non-video primary-release-date scope across languages/countries. It discovered 34,546 unique IDs, retrieved their details, and published 34,520 valid records. Twenty-six detail records were out of scope after source changes. One valid movie's credits/keywords returned 404 and remain explicitly marked missing. A single-day source-count drift was reconciled with independent sorting and a redundant year filter; coverage records the discrepancy. Historical coverage remains limited to supplied sources.

See [refresh coverage](data/catalog_refresh_2026-09-30.json), [delivered seed provenance](data/catalog_seed_v1.json), [50-seed baseline evaluation](docs/verification/recommender-evaluation.json), and [real-generation qualitative neighbors](docs/verification/recommender-neighbours.json).

Using the same 50 samples and K=10, hybrid attribute NDCG was 0.6695 versus genre 0.5484 and popularity 0.0859. Attribute precision was 0.768, 0.766, and 0.050 respectively. Corrected attribute recall was 0.0078, 0.0029, and 0.0002. These are genre/keyword proxies, not human preference accuracy. The model returns known franchise neighbors for The Dark Knight, The Godfather, and Toy Story. Inception neighbors still span action/thriller themes; plot relevance is not uniformly solved by this measurement. No human interaction dataset was supplied.

## Finding ledger

Every row describes the implemented change and the boundary of its verification; it does not certify that all possible defects have been discovered.

| Finding | Implementation | Verification |
|---|---|---|
| F01 | Numeric sparse theme similarity; no object-array crash | Theme-search regression |
| F02 | Explicit rating/vote filters stay strict | Impossible-threshold and catalog filtering regressions |
| F03 | Negative-only history demotes similar content | Negative-profile engine and API regressions |
| F04 | Full watched exclusions are separate from sampled profile | >200-history and full-exclusion regressions |
| F05 | Hybrid weights reflect only visible active inputs | Seed-only/genre-only/API validation and frontend blend tests |
| F06 | Mobile drawer fills available height and traps focus | Live 390px mobile navigation/focus check |
| F07 | Top-dialog ownership, Escape, and focus restoration | Actual modal-stack test and nested browser dialogs |
| F08 | Autocomplete combobox options support keyboard selection | Live ArrowDown/Enter added Inception to watched shelf |
| F09 | Warm-black palette with readable foreground/secondary colors | Contrast inspection; cream/muted/red/teal palette |
| F10 | Valid Render runtime, patch pin, locked offline build | Official schema validation and release-contract test |
| F11 | Deliver compact normalized seed; raw source optional | Fresh full offline build without raw source or models |
| F12 | Checkpointed refresh validates and atomically publishes pairs | Failed refresh/build preserve prior sources and active pair |
| F13 | Correct recall denominator, eligible pool, distinct predictions; honest proxy label | Recall regression and real-generation baseline comparison |
| F14 | Password changes revoke sessions; missing version claims rejected | Password/revocation API tests |
| F15 | Merge valid historical/supplement credits without empty overwrite | Credit-merge regression and final feature counts |
| F16 | Separate plot/keyword/genre/metadata vectors; plot emphasis; genre-free LSA fit | Plot-vs-genre fixture, franchise neighbors, baseline comparison; human quality unmeasured |
| F17 | Exact/partial/theme/no-match feedback and real TMDB rating labels | Search regressions, browser search, no fabricated percentage |
| F18 | Saved-history or explicit manual seeds shown and submitted | Live saved Inception blend and request-input tests |
| F19 | One balance slider with complementary effective labels | Hybrid input tests and live 100% movies/0% genres state |
| F20 | Signup, browse, profile, and hybrid genres independent | Actual chip/state test and all-supported-genre schema/API tests |
| F21 | Chips preserve focus and expose selection with aria-pressed | Actual focused-button regression |
| F22 | Form names, landmarks, controls, and dialog semantics | Accessibility/DOM inspection and keyboard flows |
| F23 | Mutation-aware saved labels and membership refresh | Membership API coverage and live shelf/list changes |
| F24 | Per-surface generations, session ownership, cancelation, guarded route updates | Reversed-completion, account replacement, list mutation race tests |
| F25 | Independent startup requests, visible failures, bounded repeated mutations | Startup offline check, request ownership and backend recovery tests |
| F26 | Nullable PATCH clears supplied fields; notes/rating independent | SQLite and PostgreSQL nullable patch coverage |
| F27 | Canonical metadata for known IDs; reject unknown/unsafe/nonfinite input | Canonical-write, unknown-ID, poster, and schema regressions |
| F28 | Transactional watch/watchlist invariant with concurrency protection | Repeated moves, legacy overlap, and simultaneous-write tests |
| F29 | Private owner editor, authorization, separate public sharing | Owner/nonowner API tests and private edit surviving reload |
| F30 | Hash routes preserve shared/owner lists and navigation | Route tests and live owner-list reload |
| F31 | Full indexed archive with filters/pages and pre-1970 browsing | Historical/incomplete-title and global-pagination tests |
| F32 | Stored-popularity labels and real catalog/provider provenance | Provenance API tests and live retrieval/cutoff display |
| F33 | Bounded concurrent media requests; duplicate inflight requests shared | Different-movie overlap/same-movie deduplication tests |
| F34 | Bounded TTL caches, retryable outages, short negative expiry | Media clock/recovery tests and browser cache age/eviction tests |
| F35 | Dialect-correct migration timestamps and preserved legacy rows | SQLite preservation and real PostgreSQL 17 migration tests |
| F36 | SQLite PRAGMAs registered before first checkout | First pooled-connection foreign-key/WAL test |
| F37 | Rollback/recovery, uniqueness, schema-aware readiness | Parallel writes, rollback, readiness degradation/recovery; in-memory thread regression |
| F38 | Immutable catalog/model pair; checksums, IDs, dimensions, finite arrays/runtime contracts | Corrupt/missing catalog, reordered IDs, incompatible runtime and publication-failure tests |
| F39 | Bounded collection pages/profile sample and grouped list counts | Pagination/profile and bounded-query-count tests |
| F40 | Hermetic fixtures, meaningful regressions, fresh build, cross-platform CI config | 92 backend/14 frontend cases; clean install/build/startup; hosted CI pending |
| F41 | Exact runtime and dev dependencies | Fresh dependency installation, release-contract test, pip check |
| F42 | Reduced-motion handling for transitions/scrolling | CSS media-query inspection |
| F43 | Minimum 44px interactive controls and clear focus | Responsive control inspection and keyboard/browser checks |

## Practical limits

There is no claim of exhaustive security certification: the managed security-scan permission path was unavailable earlier; the engineering audit and specific authentication/integrity regressions were handled. Production credentials, personal/remote database migration, hosted CI, remote deployment, and production load testing were outside the executed local scope. Catalog completeness means the documented TMDB date scope and supplied historical sources. Movie data and provider listings can change after retrieval. Regional availability links may require another provider selection on TMDB.

## Footer follow-up

Removed an unmatched closing tag that detached the footer from the page container. The flex-column page frame now keeps the footer at the bottom of short pages and after content on long pages. Brand/attribution typography and wrapping were improved. Browser measurements at 1440px confirmed the footer aligns at the same 52px inset as the main content and ends at the viewport bottom; at 390px its copy ends above the mobile navigation, with no horizontal overflow. HTML nesting validation and all 14 frontend tests passed. See [mobile footer](docs/verification/footer-mobile.jpg) and [desktop footer](docs/verification/footer-desktop.jpg).
