# CineMatch project audit

Date: 30 September 2026 (Asia/Kolkata). Target: the current working tree in `C:/Users/AYUSH/Documents/movie-recommender`, including existing uncommitted and untracked implementation files and generated models. This is a functional, backend, recommendation, data, and UI audit; it is not a completed Codex Security scan.

## Assessment

The application has a useful foundation, a coherent cinema-oriented visual identity, and working happy paths. It is **not ready for a production release of this working tree**. The main problems are broken thematic search, recommendation controls that do not honor their promises, accessibility failures, incomplete model features, fragile refresh/deployment paths, and insufficient regression coverage.

**43 findings: 15 P1 and 28 P2.** No P0 finding is asserted. P1 means a major defect or release blocker, sometimes conditional on the explicitly stated deployment scenario. P2 means a narrower defect, reliability gap, or material usability/quality issue. Counts exclude speculative problems, duplicate detector warnings, and subjective aesthetic preferences. Evidence labels distinguish reproduced behavior, source-confirmed behavior, and conditional risks. A thorough audit cannot guarantee that every possible issue has been found.

### Implementation integrity verdict

**Fail on behavior; coherent on visual identity.** The editorial palette, typography, poster grids, and hierarchy fit the product. However, the interface promises theme discovery that errors, history blending that inserts an unrelated seed, hidden-watched recommendations that can include watched films, and weekly activity without a live activity signal. These are substantive product mismatches rather than aesthetic objections.

### UI health score

These are engineering judgments from the inspected implementation, not accessibility certification or Lighthouse scores.

| Dimension | Score | Main evidence |
|---|---:|---|
| Accessibility | 1/4 | Keyboard cannot select autocomplete results; stacked dialogs handle the wrong modal; small text on primary buttons fails AA contrast |
| Performance | 3/4 | Lean vanilla frontend and lazy poster loading; repeated requests and large unpaginated libraries remain |
| Responsive design | 2/4 | Mobile poster grid works; the navigation drawer is only about 70px tall; several touch targets are small |
| Theming | 3/4 | Useful color and geometry tokens; overlapping old/new CSS and hard-coded residual colors complicate maintenance |
| Implementation integrity | 2/4 | Coherent presentation, but multiple mismatches between displayed controls and actual behavior |
| **Total** | **11/20** | **Acceptable by the UI rubric; significant work required, and release blockers remain** |

## What was checked

- Read all backend Python modules, request/response schemas, database models and migrations, frontend HTML/CSS/JavaScript, deployment configuration, dependency files, both test modules, README, and model metadata. The concept notebook is explicitly educational; the production implementation was the authority for recommendation behavior.
- Ran `./.venv/Scripts/python.exe -m unittest discover -s backend/tests -v`: **12/12 tests passed** (9 API tests, 3 recommendation tests). The suite took 4.853 seconds after discovery/import work.
- Ran `pip check`: **no broken installed requirements**. This checks the local installation, not reproducibility of a fresh installation.
- Started a separate localhost server on port 8017, using a disposable SQLite database and dummy audit credentials. For controlled UI and edge-case checks, TMDB API access and poster lookups were disabled. Existing user data and model artifacts were preserved.
- Inspected the live UI, screenshots, accessibility trees, DOM bounds, and keyboard behavior at mobile and desktop/tablet viewport settings, including 390x844, 1024x900, and 1440x1000. Also checked 820px layout bounds; that check did **not** establish a navigation overflow defect.
- Reproduced title/theme search, recommendation thresholds, negative-only personalization, history exclusion beyond 200 entries, hybrid controls, private-list access, nullable updates, metadata validation, password-change behavior, refresh failures, and TMDB cache/concurrency behavior. Network failure tests used stubs, not a live TMDB outage.
- Ran the Impeccable detector once and verified findings against active CSS and observed behavior. Its white-on-coral contrast warning was confirmed independently. Hidden legacy glow rules and purely aesthetic kicker/numbered-label warnings were not counted as functional defects.
- Evaluated 50 eligible movies, seed 42, top 10, using the supplied evaluation implementation. Profiled generated model contents and the local server's process memory. No production load benchmark, live PostgreSQL migration, full model rebuild, or deployed-site test was performed.
- Checked current Render runtime specifications and PostgreSQL date/time documentation for the deployment and migration findings.

### Security coverage limitation

The dedicated Deep Security Scan did not start. Its exact error was:

> Deep Scan cannot safely start a read-only worker: the parent must provide a managed filesystem permission profile.

The [Deep Security Scan skill](C:/Users/AYUSH/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.31/skills/deep-security-scan/SKILL.md) states: “An invocation failure before a scan starts is still a blocker; do not create a replacement scan or infer results.” No replacement scan was started and no canonical security findings, manifest, or completed security report were produced. Daybreak access also returned `not_granted`; [application information](https://chatgpt.com/cyber). The auth/session observations below are local engineering checks and do not imply exhaustive vulnerability coverage. Dependency CVEs, attack paths, and production security posture remain unverified.

## Measured recommendation and runtime facts

| Measure | Result |
|---|---:|
| Catalog / eligible movies | 18,189 / 18,189 |
| Genres | 19 |
| Release-year range | 1888–2026 |
| Movies with poster paths | 18,185 |
| Movies with cast / director features | 73 / 73, or 0.401% each |
| Duplicate title strings | 860; IDs remain the runtime identity |
| Movies before 1970 | 1,425 |
| Sparse TF-IDF shape | 18,189 x 59,166 |
| Sparse arrays in memory | Approximately 7.28 MB |
| Semantic backend | LSA / TruncatedSVD, 256 dimensions |
| SVD explained variance | 0.51267 |
| Engine initialization after imports | 0.279 seconds in one local check |
| Server working set during audit | Approximately 361–383 MB |
| Observed peak server working set | Approximately 428 MB |

The process measurements are Windows observations, not predictions of Linux memory use. The current Render specification lists 512 MB for its smallest web-service plans, so measure Linux startup and concurrent requests before choosing such a plan. The measurement does not prove an out-of-memory failure. [Render specification](https://render.com/docs/blueprint-spec)

The existing evaluator returned:

```json
{
  "sample_movies": 50,
  "top_k": 10,
  "hit_rate_at_k": 1.0,
  "attribute_recall_at_k": 1.0,
  "attribute_ndcg_at_k": 0.9463,
  "shared_genre_rate": 1.0,
  "intra_list_diversity": 0.1095,
  "catalog_coverage": 0.0239,
  "mean_quality": 0.6623,
  "mean_novelty": 0.4483
}
```

These are **attribute-proxy metrics**, not evidence of human satisfaction or real held-out user accuracy. The recall calculation is incorrect for conventional recall, as explained in F13. Coverage is the union of recommendations over this 50-seed sample, not a measured global coverage ceiling. Low intra-list diversity means average pairwise similarity is approximately 0.8905 under this evaluator's embedding measure.

## P1 findings

### F01 — Thematic search crashes on ordinary queries

**Reproduced.** [recommender.py:660](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:660)

`self.tfidf_matrix @ sparse_query.T` is sparse. `np.asarray(...)` wraps it as an object instead of extracting its numeric values; casting then raises `ValueError: setting an array element with a sequence`. All six suggested themes failed, including `Cyberpunk sci-fi`, `Time travel thriller`, and `Space exploration`. HTTP `/search` returned 500; the UI displayed “Request failed.” Title search for `Inception` worked.

**Repair:** Convert the sparse result explicitly with `.toarray().ravel()` or use a supported similarity operation. Add regression cases for every suggested theme, title matches, and out-of-vocabulary input.

### F02 — Genre recommendations silently discard rating and vote thresholds

**Reproduced.** [recommender.py:423](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:423)

When fewer than `top_n` candidates meet the thresholds, the engine replaces the validity mask with `genre_scores > 0`, removing both restrictions. Drama with minimum rating 10 and minimum votes 1,000,000 returned ordinary movies rated 8.1–8.7 with far fewer votes. A normal “Rating 8+” selection can also be relaxed when a genre has too few qualifying candidates.

**Repair:** Honor explicit filters and return fewer results. If relaxation is a product choice, require an explicit option and return the actual applied filters and a visible explanation.

### F03 — Negative-only profiles ignore dislikes and return watched movies

**Reproduced.** [recommender.py:555](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:555), [recommender.py:586](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:586)

Negative profiles are applied only when there is a positive seed. Otherwise the genre/popular fallback ignores negative vectors and all watched exclusions. Giving the initial ten suggestions one-star ratings produced the same ten watched suggestions again with `exclude_watched=True`, both with no preferences and with Drama preferences.

**Repair:** Apply exclusions in every strategy and support a negative-only profile or an explicitly explained fallback that still honors dislikes and watched status.

### F04 — “Hide watched” stops working for older library entries

**Reproduced.** [main.py:530](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:530)

The route reads only the latest 200 watched records. Those same IDs are used for both profiling and exclusion. A disposable 201-entry history returned older watched movie ID 10940 despite `exclude_watched=true`.

**Repair:** Keep the bounded history sample for profile construction if desired, but retrieve the user's full watched ID set separately for candidate exclusion. Test libraries above the profile limit.

### F05 — Hybrid recommendations inject preferences the user never selected

**Source confirmed.** [app.js:1679](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1679), [schemas.py:106](C:/Users/AYUSH/Documents/movie-recommender/backend/schemas.py:106)

With no selected seeds, the client inserts Avatar (`19995`); with no genres, it inserts Science Fiction. A user requesting a genre-only blend receives a profile influenced by Avatar; a seed-only blend gains a fabricated genre. The API requires at least one movie ID, encouraging this workaround.

**Repair:** Allow either real seed IDs or real genres, require at least one effective signal, and remove hidden defaults. Show precisely which inputs drive the blend.

### F06 — Mobile navigation is confined to the header

**Reproduced.** [app.css:147](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:147), [app.css:1797](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:1797), [app.css:1993](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:1993)

At 390x844, the open drawer measured only 70px high, approximately the sticky header's height. Its links extended over the darkened content outside that background. The fixed drawer lives inside a blurred header, and later CSS also overrides its intended padding to zero. Focus remains on the menu toggle; there is no drawer focus containment, Escape handler, scroll lock, or expanded-state announcement.

**Repair:** Put the drawer in a viewport-level overlay outside the header, consolidate the mobile rules, move/restore focus, implement Escape and background isolation, and expose `aria-expanded`/`aria-controls`. Suggested UI command: `$impeccable adapt`, then `$impeccable harden`.

### F07 — Stacked dialogs trap focus and dismiss the wrong dialog

**Reproduced.** [app.js:487](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:487), [app.js:508](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:508)

Opening details from search leaves both dialogs open. `getOpenModal()` chooses the first matching element in document order, which is the underlying search dialog. Shift+Tab from the movie close button moved focus into search; Escape closed search while leaving movie details open. Add-to-list can introduce a similar stack/paint-order problem. Multiple elements simultaneously claim `aria-modal=true`.

**Repair:** Use one active dialog or a real modal stack with explicit topmost ownership, layer ordering, inert underlying content, and per-layer focus restoration. Relevant standard: keyboard operation and focus order. Suggested command: `$impeccable harden`.

### F08 — Keyboard users cannot select search suggestions

**Reproduced.** [app.js:1604](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1604), [app.js:1709](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1709)

History-seed and library suggestions are clickable `div` elements with no role, tab stop, or key handling. ArrowDown followed by Enter in the seed input left the seed count at zero. This blocks the primary seed-based flow for keyboard users and makes library quick-add inaccessible. Relevant standard: WCAG keyboard operation, 2.1.1.

**Repair:** Implement an accessible combobox/listbox interaction or actual buttons, including keyboard selection and results announcements. Suggested command: `$impeccable harden`.

### F09 — Primary buttons and active filters fail text contrast

**Detector finding independently confirmed.** [app.css:2062](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:2062), [app.css:2353](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:2353)

White text on `#c85f42` has **4.061:1** contrast; the hover background `#df7858` has **3.015:1**. Small button/filter text requires 4.5:1 for WCAG AA, 1.4.3. The muted text token on the page background measured 5.678:1 and is not a general contrast failure.

**Repair:** Darken the accent surface or use a text/background combination that meets contrast in every interaction state. Suggested command: `$impeccable colorize`.

### F10 — Render runtime value is invalid

**Configuration confirmed against the current official schema.** [render.yaml:5](C:/Users/AYUSH/Documents/movie-recommender/render.yaml:5)

`runtime: python-3.12` is not a supported runtime value. Render expects `python`; version selection is separate. `env: python` is a deprecated field and does not make the invalid runtime valid. This is a Blueprint deployment blocker, not proof that a separately configured existing service is down. [Render runtime specification](https://render.com/docs/blueprint-spec)

**Repair:** Use the valid runtime field and one supported Python-version mechanism. Validate the Blueprint before release.

### F11 — The model build depends on a large untracked dataset

**Repository state and source confirmed.** [data_preprocessing.py:105](C:/Users/AYUSH/Documents/movie-recommender/backend/data_preprocessing.py:105), [render.yaml:6](C:/Users/AYUSH/Documents/movie-recommender/render.yaml:6)

The current pipeline requires `data/TMDB_movie_dataset_v11.csv`, a 650,114,445-byte file. It is untracked, and there is no download/provisioning step or fallback to the tracked TMDB 5000 CSVs. Models are also intentionally ignored. A release containing this implementation without provisioning that data cannot build from a clean checkout. Several newly imported modules also remain untracked; do not commit only the modified tracked files.

**Repair:** Establish a reproducible, versioned dataset/artifact delivery mechanism, record provenance/checksums, and verify a clean-checkout build. Do not merely add a 650 MB file to ordinary Git without choosing an appropriate storage strategy.

### F12 — A failed data refresh destroys usable supplements

**Reproduced with stubbed TMDB failure in a temporary directory.** [fetch_latest_movies.py:119](C:/Users/AYUSH/Documents/movie-recommender/backend/fetch_latest_movies.py:119), [data_preprocessing.py:118](C:/Users/AYUSH/Documents/movie-recommender/backend/data_preprocessing.py:118)

If discovery/details all fail, refresh still publishes empty DataFrames. Both CSVs become two-byte files with no columns, and subsequent `pd.read_csv` raises `EmptyDataError`. Existing good data would be overwritten. Atomic writes protect each individual file from partial writes but do not validate content or publish the movie/credit pair together.

**Repair:** Fail refresh without publishing when results are empty/invalid, preserve the previous successful snapshot, validate both schemas, and publish a versioned pair atomically.

### F13 — The evaluator's “recall” calculation materially overstates recall

**Source and numeric behavior confirmed.** [evaluate_recommender.py:77](C:/Users/AYUSH/Documents/movie-recommender/backend/evaluate_recommender.py:77), [evaluate_recommender.py:26](C:/Users/AYUSH/Documents/movie-recommender/backend/evaluate_recommender.py:26)

The denominator is `min(top_k, relevant_total)`, so with many relevant movies this is effectively precision at K, not recall. Inception had 1,189 attribute-relevant catalog rows under the same threshold (1,188 other candidates after excluding the seed); even ten relevant recommendations recover only about 0.84% of those other candidates, not 100%. The reported sample recall was 1.0. Relevance itself uses the same genre/keyword attributes that drive ranking, so it rewards agreement with the model's own input signals.

**Repair:** Correct or rename the metric, retain proxy metrics with clear labels, add held-out interactions and human relevance judgments, and compare against genre-only/popular baselines. Do not interpret the current 1.0 values as user-quality validation.

### F14 — Password changes do not invalidate existing sessions

**Reproduced.** [main.py:410](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:410), [auth.py:36](C:/Users/AYUSH/Documents/movie-recommender/backend/auth.py:36), [config.py:51](C:/Users/AYUSH/Documents/movie-recommender/backend/config.py:51)

After a successful password change, the original bearer token still accessed `/auth/me`. Tokens have a default 30-day lifetime and no session/token version or revocation state. Browser logout only removes local storage. Changing the password therefore cannot terminate a previously obtained session. The change-password schema also accepts an all-numeric password that signup rejects.

**Repair:** Add a session version or revocation mechanism, invalidate prior sessions on credential changes, define logout/session semantics, and reuse a single password validator. Verify old-token rejection after changing credentials.

### F35 — Legacy PostgreSQL migrations use an unsupported type

**Conditional upgrade risk; source/documentation confirmed, not run against live PostgreSQL.** [database.py:186](C:/Users/AYUSH/Documents/movie-recommender/backend/database.py:186)

Several added timestamp columns use raw `DATETIME` SQL. PostgreSQL uses `timestamp` types; an older production schema missing one of these columns will fail the ALTER and startup. A fresh schema created by SQLAlchemy's `DateTime` does not encounter that path. The additive migration mechanism also does not version, backfill, or repair missing constraints on existing tables. [PostgreSQL date/time types](https://www.postgresql.org/docs/current/datatype-datetime.html)

**Repair:** Use versioned, dialect-aware migrations with timestamps, data backfills, and constraint/index upgrades. Test both fresh and legacy schemas on the production dialect.

## P2 findings

### F15 — Cast/director recommendations lack almost all catalog credits

**Measured.** [data_preprocessing.py:130](C:/Users/AYUSH/Documents/movie-recommender/backend/data_preprocessing.py:130), [data_preprocessing.py:186](C:/Users/AYUSH/Documents/movie-recommender/backend/data_preprocessing.py:186)

Only the latest credits supplement is merged; the tracked older credits corpus is unused. Cast and director lists are populated for just 73 of 18,189 movies. Thus 99.6% of the catalog cannot contribute those advertised signals. Runtime TMDB details do not update recommendation vectors.

**Repair:** Merge credits by movie ID from all valid sources, retain them across refreshes, and publish coverage metrics for each feature before evaluating cast/director-based quality.

### F16 — Similarity heavily favors broad attributes over plot nuance

**Measured representation; quality concern supported by examples, not human relevance ground truth.** [data_preprocessing.py:22](C:/Users/AYUSH/Documents/movie-recommender/backend/data_preprocessing.py:22), [recommender.py:342](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:342)

When all four independently normalized fields are nonempty, their nominal squared contributions are genres 37.4%, keywords 46.2%, overview 11.5%, metadata 4.9%. The default semantic vectors are an SVD of this same representation. Inception's top six were two Star Wars films, Ant-Man and the Wasp, Babylon 5, Black Lightning, and The Incredible Hulk. This is plausible broad genre similarity but weak evidence for the promised shared plot/feel. Sample intra-list diversity was 0.1095.

**Repair:** Evaluate plot/theme relevance independently, tune field weights and diversification against those judgments, and compare LSA with the optional neural backend before choosing weights. Preserve successful franchise cases.

### F17 — Search metadata and fallback copy overclaim relevance

**Reproduced/source confirmed.** [recommender.py:649](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:649), [recommender.py:674](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:674), [app.js:546](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:546)

All substring title matches return `exact_match=true`. Nonsense query `zzzzxyqfoobar` returned popular films while describing them as closest thematic matches, even though no theme signal matched. Separately, arbitrary blended ranking scores are presented as “72% Match”; no calibration establishes such a percentage as a probability or user-preference rate.

**Repair:** Distinguish exact titles, partial titles, thematic retrieval, and popular fallback. Say when a query has no meaningful match. Label ranking scores honestly or calibrate them before displaying percentages. Suggested command: `$impeccable clarify`.

### F18 — “Saved history” in Mix & Match actually means temporary lab seeds

**Source confirmed.** [app.js:1670](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1670), [index.html:468](C:/Users/AYUSH/Documents/movie-recommender/frontend/index.html:468)

The screen says saved history influences the blend, but sends `state.historySeeds`, populated only in More Like These. It never uses `state.profile.history`, and the blend screen has no seed picker or summary. Even a user with a rich watched library gets the Avatar fallback unless they manually visited another lab first.

**Repair:** Either use actual watched history or rename the input and add a visible picker/summary on this screen. Suggested command: `$impeccable clarify`.

### F19 — The second blend slider does not update its displayed value

**Reproduced.** [app.js:1658](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1658)

Only the history slider has an input listener. Moving genre weight from 0.3 to 0.4 left its displayed label at 0.3 and history at 0.7. The backend normalizes the submitted 0.7/0.4 values, so displayed weights, submitted weights, and effective weights disagree.

**Repair:** Use one complementary slider or synchronize both controls and labels in both directions. Show normalized weights when independent weights are intended. Suggested command: `$impeccable harden`.

### F20 — Genre selection state and API limits disagree

**Reproduced/source confirmed.** [schemas.py:35](C:/Users/AYUSH/Documents/movie-recommender/backend/schemas.py:35), [schemas.py:86](C:/Users/AYUSH/Documents/movie-recommender/backend/schemas.py:86), [app.js:401](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:401)

The UI offers 19 genres without caps; signup/preferences permit 15 while genre/hybrid requests permit 10. Saving 11 genres succeeded, but recommending with the same selection returned 422. One `state.genres` also serves signup, saved preferences, and temporary browsing, so browsing modifies the unsaved profile selection and signup highlights/counts can disagree with the set submitted.

**Repair:** Separate persisted preferences, signup choices, and temporary filters; align or visibly enforce endpoint limits; synchronize selection counts. Suggested command: `$impeccable harden`.

### F21 — Genre chips lose focus and do not expose selection state

**Reproduced.** [app.js:401](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:401)

Selecting Comedy rebuilt both grids and moved focus to `BODY`. Selected chips expose no `aria-pressed` or checked state. Active decade filters and several tab-like controls similarly depend on classes alone. This makes repeated keyboard selection cumbersome and hides selected state from assistive technology.

**Repair:** Update elements in place or restore focus, expose pressed/checked state, and use appropriate tab semantics where applicable. Suggested command: `$impeccable harden`.

### F22 — Search and genre controls lack explicit accessible labels

**Source and accessibility tree confirmed.** [index.html:413](C:/Users/AYUSH/Documents/movie-recommender/frontend/index.html:413), [index.html:655](C:/Users/AYUSH/Documents/movie-recommender/frontend/index.html:655)

The main search input relies on a long placeholder, and the genre count/rating selects have no explicit label or accessible name. Placeholder text is not a persistent field instruction and disappears during entry. The watchlist remove button is labeled only “✕”.

**Repair:** Add visible or appropriately hidden labels, descriptive action names, and clear field instructions. Suggested command: `$impeccable clarify` / `$impeccable harden`.

### F23 — Movie action labels remain stale after saves

**Source confirmed.** [app.js:948](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:948), [app.js:991](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:991)

Mutations start `fetchWatchlist()`/`fetchProfile()` without awaiting them, then immediately compute modal labels from old state. Neither fetch subsequently refreshes the active modal. “Want to Watch” or “Save to Watched” can remain unchanged after a successful operation. Card bookmarks always announce “Add” even when toggling an existing bookmark removes it.

**Repair:** Await/reconcile the new state before rendering all affected controls, and keep accessible names consistent with the action. Suggested command: `$impeccable harden`.

### F24 — Async responses can overwrite newer UI state

**Source-confirmed race; adverse timing not injected in the browser.** [app.js:374](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:374), [app.js:684](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:684), [app.js:1287](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1287)

Details, searches, profile loads, and recommendations commit responses without request IDs, cancellation, or account/active-movie checks. A slower earlier request can replace the result of a later selection. Details also retain old poster/facts/action callbacks while loading, allowing actions against the prior film. In-flight profile work can complete after sign-out or account changes.

**Repair:** Cancel superseded work or compare request/session generations before committing responses; clear or disable stale details actions during loading. Suggested command: `$impeccable harden`.

### F25 — Several loading failures leave stale or misleading screens

**Source confirmed; theme error observed.** [app.js:374](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:374), [app.js:845](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:845), [app.js:1079](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1079), [app.js:1760](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1760)

Profile, watchlist, custom-list, and initialization failures mostly log to the console with no inline retry/error state. Main search failures retain previous results and show only a toast. A failed health request also prevents the initial genre request because they share one sequential try block. Several mutation/recommendation buttons permit duplicate submissions while pending.

**Repair:** Track loading/error/empty/success states per surface, clear or label stale results, decouple independent startup loads, and disable pending mutations. Suggested command: `$impeccable harden`.

### F26 — Ratings and notes cannot be cleared naturally

**Reproduced/source confirmed.** [main.py:650](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:650), [app.js:1054](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1054)

PATCH accepts nullable fields but treats `null` as “do not update”; clearing a five-star rating with `rating:null` left it at five stars. The UI requires a valid rating before editing a note and uses two sequential native prompts, with no “unrate” action or length guidance.

**Repair:** Distinguish omitted fields from explicit null using the model's supplied-fields set. Provide one accessible editor with independent rating/notes, clear actions, and the 500-character limit. Suggested command: `$impeccable harden`.

### F27 — Library and list metadata validation is incomplete

**Reproduced.** [schemas.py:124](C:/Users/AYUSH/Documents/movie-recommender/backend/schemas.py:124), [schemas.py:341](C:/Users/AYUSH/Documents/movie-recommender/backend/schemas.py:341), [main.py:567](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:567)

The backend accepted unknown movie ID 999999999, title “Bogus catalog title”, and TMDB rating 999. That movie cannot open in details or contribute to profiling. Known IDs can also be saved with unrelated titles/genres. A list title containing only spaces passed validation and became an empty title after route-level stripping. Non-finite rating input was accepted in a local check; it did not produce the initially suspected response crash, so no such crash is claimed.

**Repair:** Resolve canonical catalog metadata on the server or explicitly support external movies, constrain/require finite vote averages, and trim before validating list-title length.

### F28 — Watched and watchlist consistency depends on the add path

**Reproduced.** [main.py:578](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:578), [main.py:611](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:611), [main.py:722](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:722)

A first watched insertion removes the watchlist entry, but updating an already-watched movie returns earlier without doing so. Adding an existing watched movie to the watchlist and saving it as watched again leaves it in both lists. This contradicts the automatic move behavior elsewhere.

**Repair:** Define whether rewatch watchlists are supported. Apply the chosen invariant consistently across add/update/move routes and reflect it in the UI.

### F29 — Private curated lists lack an owner-facing management flow

**Reproduced/source confirmed.** [app.js:1091](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1091), [main.py:929](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:929)

Every list offers Share Link, including private lists. That link returns 404 even to its authenticated owner. List cards expose only a four-poster preview, sharing, and deletion; there is no full owner detail view, item-removal UI, metadata editor, or privacy toggle after creation. The API has item deletion but no list-update route.

**Repair:** Add an owner detail/editor and public/private management; hide or explain sharing for private lists. Preserve the backend's private-list access restriction. Suggested command: `$impeccable shape`.

### F30 — Navigation does not maintain route/history state

**Source confirmed.** [app.js:441](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:441), [app.js:1806](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1806)

The shared-list hash is read only at startup; there is no `hashchange` handler. Page switches do not update history or clear a shared-list hash. Back to Explore can leave a list URL in the address bar, and reloading opens the old list again. Normal pages are not deep-linkable and browser Back does not track in-app navigation.

**Repair:** Use consistent hash or History API routing, handle changes, and keep the address bar aligned with the visible page. Suggested command: `$impeccable harden`.

### F31 — Archive sorting/filtering operates on tiny preselected shelves

**Source/catalog confirmed.** [recommender.py:749](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:749), [recommender.py:763](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:763), [app.js:638](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:638)

The server supplies only twelve quality/popularity-selected movies per decade, and the client sorts/filters those twelve. “Newest”, “Oldest”, and “Highest Rated” do not query the decade's catalog. “All Time” concatenates six decades starting at 1970, excluding the 1,425 earlier films even though the catalog reaches 1888.

**Repair:** Query/filter/sort the actual catalog with pagination and older eras, or clearly label the controls as sorting a curated sample. Suggested command: `$impeccable clarify`.

### F32 — Weekly discovery copy has no freshness guarantee

**Source confirmed.** [recommender.py:727](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:727), [index.html:309](C:/Users/AYUSH/Documents/movie-recommender/frontend/index.html:309), [app.js:597](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:597)

“Now playing” and “Films people are returning to this week” are derived from stored popularity values, with no release-window filter, weekly activity data, refresh timestamp, or automated update. The client additionally caches Explore for the entire session. The refresh script fetches popular movies, not a weekly app activity signal.

**Repair:** Use accurately named snapshot discovery with a timestamp, or implement a documented freshness source and refresh/invalidation policy. Suggested command: `$impeccable clarify`.

### F33 — TMDB detail requests serialize behind a global network lock

**Reproduced with stubbed network latency.** [tmdb.py:38](C:/Users/AYUSH/Documents/movie-recommender/backend/tmdb.py:38)

The lock is held while fetching over the network. Three distinct concurrent misses, each taking 0.2 seconds, took 0.603 seconds collectively. Real calls can retry two five-second timeouts, so one slow movie blocks unrelated detail requests and consumes waiting request threads.

**Repair:** Hold locks only for cache state, use per-key request coalescing, allow bounded independent fetches, and apply a shared client/time budget.

### F34 — Transient TMDB failures are cached permanently

**Reproduced with a stub; poster behavior source confirmed.** [tmdb.py:45](C:/Users/AYUSH/Documents/movie-recommender/backend/tmdb.py:45), [posters.py:60](C:/Users/AYUSH/Documents/movie-recommender/backend/posters.py:60)

Any failed request marks a movie known-missing for the process lifetime, including timeout/rate-limit/server failures. After a first failed fetch, a second call never retried even though the stub would have recovered. Successful details also have no TTL; expired/unbounded cache entries remain until restart. Missing-poster background fills do not notify already-rendered cards.

**Repair:** Separate permanent 404s from transient failures, use TTL/backoff and bounded caches, and define when the client refreshes late poster data.

### F36 — SQLite initialization happens after the first pooled connection exists

**Reproduced at import; impact depends on connection reuse.** [database.py:32](C:/Users/AYUSH/Documents/movie-recommender/backend/database.py:32), [database.py:49](C:/Users/AYUSH/Documents/movie-recommender/backend/database.py:49)

`_get_engine()` opens a connection before the connect listener is registered. Immediately after import, that pooled connection reported `foreign_keys=0` and journal mode `delete`, rather than the requested foreign-key enforcement and WAL. Later application connections were correctly configured; an orphan insertion in one post-startup check was rejected. Therefore this is an inconsistent-pool initialization risk, not evidence that all runtime foreign keys are disabled.

**Repair:** Register initialization before the first connection checkout, or dispose/recreate the pre-listener pool. Verify every pooled connection, not only a later one.

### F37 — Database races and connection failures have no controlled recovery

**Source-confirmed conditional risk; no production race/outage injected.** [main.py:344](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:344), [main.py:578](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:578), [main.py:731](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:731), [database.py:32](C:/Users/AYUSH/Documents/movie-recommender/backend/database.py:32)

Create paths check existence and then commit without handling `IntegrityError`; concurrent duplicate requests can both pass the check and one becomes a server error. SQL uniqueness protects new-schema data, but the API lacks rollback/conflict mapping or upsert behavior. PostgreSQL pooling has no `pool_pre_ping`/reconnect strategy. `/health` checks cached catalog state but not DB readiness after startup.

**Repair:** Use transactional upserts or catch/rollback conflicts with defined responses, configure connection health appropriately, and separate liveness from readiness with database checks.

### F38 — Model artifacts are published without a versioned bundle contract

**Source-confirmed rebuild risk; models were not overwritten during the audit.** [data_preprocessing.py:393](C:/Users/AYUSH/Documents/movie-recommender/backend/data_preprocessing.py:393), [recommender.py:53](C:/Users/AYUSH/Documents/movie-recommender/backend/recommender.py:53)

The build overwrites multiple files sequentially. A crash or concurrent startup can load an old/new mixture. Runtime checks only row counts for vectors, not shared ID ordering, feature dimensions, vectorizer/reducer compatibility, source checksum, or common build identity. Equal row counts do not prove semantic alignment. Pickles also require trusted artifacts and compatible dependencies.

**Repair:** Build into a versioned temporary directory, validate a manifest/checksums/dimensions/ID-order digest, then atomically select the bundle. Record the library and data versions.

### F39 — Library/list endpoints and rendering grow without pagination

**Source confirmed.** [main.py:387](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:387), [main.py:705](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:705), [main.py:836](C:/Users/AYUSH/Documents/movie-recommender/backend/main.py:836), [app.js:1001](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.js:1001)

Profile responses contain every watched item, and list/watchlist routes materialize all entries. List serialization lazily loads each list's items, adding per-list queries. Frontend rendering creates all cards and rebuilds large portions after mutations. Repeated profile loads also trigger watchlist/list loads, sometimes duplicated by callers.

**Repair:** Separate profile summary from paginated collections, eager-load needed list relationships, avoid duplicate fetches, and render incrementally. Suggested command: `$impeccable optimize`.

### F40 — Passing tests omit the project's most important failure modes

**Source and test-run confirmed.** [test_api.py:64](C:/Users/AYUSH/Documents/movie-recommender/backend/tests/test_api.py:64), [test_recommender_quality.py:39](C:/Users/AYUSH/Documents/movie-recommender/backend/tests/test_recommender_quality.py:39)

The 12-test suite has no search test, no strict-threshold check, no negative-only or >200-history exclusion check, no keyboard/modal test, no migration/refresh-failure test, and no build-from-clean-checkout check. Franchise tests only require one franchise term somewhere in ten results. Tests require real local model files; API tests disable poster lookups but do not consistently disable TMDB details, so environment credentials can introduce network calls. No CI workflow was found.

**Repair:** Add focused regression coverage for the reproduced defects, fixture-sized pipeline and dialect tests, deterministic TMDB stubs, and browser accessibility tests in CI. Keep real-catalog quality evaluation as a separately labeled job.

### F41 — Fresh dependency installs are not reproducible

**Source confirmed; local installed dependencies are consistent.** [requirements.txt:5](C:/Users/AYUSH/Documents/movie-recommender/backend/requirements.txt:5), [requirements-semantic.txt:3](C:/Users/AYUSH/Documents/movie-recommender/backend/requirements-semantic.txt:3)

Most requirements use open-ended lower bounds, and no lock/constraints file captures transitive versions. Pickled sklearn objects and SVD artifacts can be sensitive to library changes; a clean build may differ from the audited virtual environment even with the same source. `pip check` passing locally does not resolve this.

**Repair:** Produce a tested dependency lock/constraints set, record artifact build versions, and validate the optional semantic environment separately.

### F42 — Motion has no reduced-motion alternative

**Source confirmed.** [app.css:410](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:410), [app.css:2232](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:2232)

Reveal, loading shimmer, hover movement, modal animation, and smooth scrolling have no `prefers-reduced-motion` handling. The visual transitions are modest, so this is a user-preference/accessibility gap rather than a claimed flashing or seizure hazard.

**Repair:** Provide intentional reduced-motion states that preserve status feedback without movement/shimmer. Suggested command: `$impeccable animate`.

### F43 — Several touch targets are small

**Measured/source confirmed.** [app.css:1841](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:1841), [app.css:1300](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:1300), [app.css:2295](C:/Users/AYUSH/Documents/movie-recommender/frontend/assets/app.css:2295)

The mobile drawer close target measured 20x24px, modal close is 36x36px, quick card actions are 36px tall, and quick theme tags have small padding. The mobile search/menu triggers correctly use 44x44px. A blanket claim that every sub-44px target violates WCAG would be incorrect; 44px is the usability target used here, and formal minimum-target conformance has exceptions.

**Repair:** Increase the actual hit regions and spacing, especially close/remove controls, without relying only on icon size. Suggested command: `$impeccable adapt`.

## Systemic patterns

1. **State is shared across unrelated intentions.** Persisted taste, signup choices, browsing filters, history seeds, active dialogs, and async loading need distinct ownership. F05, F07, F18–F25 are connected symptoms.
2. **Fallbacks override explicit contracts.** Filters, watched exclusions, and search descriptions are replaced with more convenient output instead of preserving the user's request. F02–F05 and F17 should be repaired together.
3. **Offline evaluation measures agreement with attributes, not recommendation usefulness.** The sparse architecture is efficient, but feature coverage and external relevance evidence lag behind the marketing claims.
4. **Freshness and publication lack a shared contract.** Refresh pairs, model bundles, deployment inputs, and caches need version/provenance/expiry rules.
5. **Happy-path validation dominates the tests.** Existing passing tests miss complete core flows. Regression tests should assert user-visible contracts and failure recovery.
6. **CSS has two overlapping visual systems.** The original rules and a large appended editorial override coexist, including duplicate tokens and mobile definitions. This contributed to navigation behavior and makes detector output noisy. Consolidate active rules while preserving the current visual identity.

## Practices to keep

- Sparse retrieval avoids a full 18,189 x 18,189 similarity matrix; the core matrix arrays use about 7.28 MB.
- Generated sparse and semantic rows were aligned and normalized in the existing tests. Rating inversion changed personalized ordering; known franchise neighbors were found.
- User-owned update/delete routes consistently include user filters in their source. The public sharing route correctly rejects private lists; the owner-sharing UI problem should not be fixed by removing that restriction.
- Password hashing uses bcrypt with a prehash, signed tokens restrict the algorithm, and production mode refuses an unset signing secret.
- Database connection failure no longer silently redirects production data into another SQLite database.
- Most user text is escaped or inserted with `textContent`; poster paths are validated on both sides. These observations do not constitute an exhaustive XSS review.
- Lazy poster loading, image fallback initials, visible focus outlines, labeled core auth forms, and retry states on Explore/personal recommendations are useful foundations.
- Individual refresh CSV writes use replacement rather than exposing partially written bytes; retain that property while adding validation and pair-level publication.

## Recommended repair order

1. **Restore core contracts:** F01 search, F02 strict filters, F03/F04 watched exclusion, F05/F18/F19 truthful hybrid inputs and controls. Add focused regression tests as each defect is repaired.
2. **Make the UI operable:** F06–F09 and F21/F22. Use `$impeccable adapt`, `$impeccable harden`, and `$impeccable colorize` for the scoped UI work.
3. **Make release and data refresh reproducible:** F10–F12, F35–F38, F41. Validate a clean build and a legacy PostgreSQL migration before release.
4. **Improve recommendation evidence:** F13/F15/F16/F17. Correct metric names/formulas, broaden credits coverage, add human/held-out relevance judgments, and compare simple baselines before tuning or adopting neural embeddings.
5. **Complete library/session workflows:** F14, F20, F23–F30, F39. Add explicit lifecycle and pagination semantics; verify error/retry behavior.
6. **Control freshness and latency:** F31–F34. Make catalog scope and update times visible, fix TMDB concurrency and cache expiry, and profile Linux memory and representative concurrency.
7. **Finish accessibility and clarity:** `$impeccable clarify`, `$impeccable animate`, `$impeccable optimize`, then `$impeccable polish` after the behavior is stable. Re-run `$impeccable audit` for the UI score.

These steps are recommendations; **no application fixes were applied** during this audit. The user can request them individually, together, or in another order.

## Additional limitations and documentation notes

- The audit reviewed the current working tree, not an immutable commit. The existing changes were preserved. Deployment findings apply to a release containing these files; the README's deployed demo was not tested.
- The concept notebook was not executed, and its educational older-corpus behavior was not treated as production behavior. Full notebook correctness remains outside the verification performed here.
- README descriptions still mention 15,000 features/simple averaged vectors and an 8,000+ catalog, whereas current artifacts have 59,166 features, LSA, diversified and rating-aware ranking, and 18,189 titles. Windows guidance says `set`, which is cmd syntax rather than PowerShell `$env:NAME=...`. Document the actual default pipeline, artifact files, both test modules, and controlled refresh/build workflow.
- There is no independent user-interaction dataset supplied for this audit, so no held-out interaction result or true preference accuracy is asserted. The reported quality metrics are the existing evaluator's output, with its limitations disclosed.
- PostgreSQL migration execution, actual Render deploy validation, production proxy/rate-limiter behavior, dependency vulnerability intelligence, security headers, token attack resistance, and large-scale load behavior require additional verification. The limiter is process-local and IP-based; scaling/proxy configuration should be tested in the real deployment, rather than assumed safe or broken from localhost.
- Local reproduction attempts that did not establish a claimed defect were excluded: 820px navigation overflow was not confirmed; accepted non-finite metadata did not crash response serialization; a post-startup SQLite connection did reject an orphan insertion. These narrow results do not invalidate the separate source-confirmed validation and initialization findings.
