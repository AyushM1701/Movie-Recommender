# CineMatch remediation and September 2026 catalog design

Date: 30 September 2026, Asia/Kolkata.

Status: proposed written specification. The user approved the design direction in chat; this document awaits written-spec review. No application fixes are represented as implemented or verified here.

## Intended outcome

Implement every actionable finding F01–F43 in `PROJECT_AUDIT.md`, redesign the existing movie discovery application around the supplied mobile screenshot, place watch links beneath every movie, and refresh the movie catalog through 30 September 2026. Streaming availability defaults to India, with a user-selectable country; the user explicitly confirmed this requirement.

Retain CineMatch, FastAPI, SQLAlchemy, and the vanilla HTML/CSS/JavaScript frontend. Preserve existing user accounts, watched history, notes, ratings, watchlists, custom lists, and all unrelated working-tree changes. Improve boundaries where they resolve a defect or simplify the affected workflows. The work is a coordinated remediation, not a framework migration.

Success means verified behavior, not a green legacy test suite or a claim that every possible defect has disappeared. Every audit finding receives an implementation entry and evidence. Conditional findings require a corresponding scenario test or an explicit remaining verification limitation.

## Decisions and alternatives

**Selected: retain the stack and introduce focused boundaries.** Separate catalog provisioning, artifact publication, media availability, and library rules from request handlers; introduce frontend modules for API/state, movie presentation, navigation/dialogs, and library workflows where useful. This preserves the functioning product while resolving the defects and supporting the new catalog/provider contracts.

**Alternative: framework rewrite.** A React/Next.js replacement could offer different development conventions but adds a frontend migration and deployment changes unrelated to the reported defects. It is outside this design.

**Alternative: fully live TMDB discovery and recommendation.** This avoids local refresh artifacts but makes core browsing and recommendation dependent on external latency and availability, and cannot preserve the existing local recommendation engine as the primary service. Live TMDB is reserved for enrichment and watch availability; local catalog browsing and ranking remain usable during outages.

## Visual and interaction design

The supplied screenshot is the visual authority: warm near-black backgrounds, cream typography, muted red uppercase section headings, thin warm borders, rounded feature panels, teal rating outlines, and prominent film imagery. Keep the CineMatch name. The screenshot's phone status bar, social-app overlays, and unsupported TV/chat functions are outside the product design.

Use a condensed display treatment for the masthead, legible body type, a restrained shared spacing scale, and centralized color, radius, and type tokens. Replace overlapping legacy theme rules in affected surfaces rather than layering another complete theme on top. Red surfaces and their text must meet contrast requirements in default, selected, hover, disabled, and focus states.

The home surface leads with one split feature card: real title, genre, year, runtime where known, a community-rating ring, visible watch availability, and a large poster/backdrop. Personal recommendations receive a plain-language reason. Do not manufacture a predicted personal rating, critics score, activity count, or match probability to reproduce the image. The existing TMDB vote average is labelled as a community rating; sparse/no votes receive an unrated/limited-votes state. Algorithm scores remain internal unless explicitly labelled as ranking scores.

Poster shelves follow the feature, including personal suggestions/watchlist when authenticated and recent releases/top-rated selections when appropriate. Every shared movie-card variant includes its watch-link area: home shelves, browse/search results, recommendation results, watched history, watchlist, custom lists, shared lists, and similar movies. Each card offers separate, clearly labelled details, watch, and library controls; nested interactive elements do not trigger card-detail handlers accidentally.

On mobile, provide a floating bottom navigation for the real primary destinations: Home, Discover, Library, and Profile/sign-in. Secondary discovery controls remain accessible through a properly managed menu. Support safe-area insets and reserve enough bottom content space that navigation never covers actions. On larger screens, use a clear top navigation and wider feature/card layouts. Poster shelves support keyboard scrolling; archive browsing is a paginated grid. Verify at 390px, 820px, and 1440px widths, including long titles and missing artwork.

Navigation updates URL/history state and handles reload, Back/Forward, authenticated destinations, and public-list links. Use one explicit dialog controller with a topmost stack only where a child dialog is necessary. The top layer owns Escape, focus containment, modal semantics, and background isolation; closing it restores focus to its initiating control. A mobile drawer follows the same ownership rules outside the blurred/sticky header.

## Regional watch links

Add a media-availability service backed by TMDB's `/movie/{id}/watch/providers` data. Provider information is region-specific and groups subscription, free, ad-supported, rental, and purchase options. Validate country codes against the available-country configuration, with India (`IN`) as the default. Persist the user's country preference locally independently of authentication and update visible cards when it changes.

TMDB does not supply full provider playback deep links in this endpoint. Provider chips link to the returned TMDB movie watch page for that country, which contains the provider destinations. Label the action as viewing watch options; do not claim that a chip starts Netflix or other playback directly. Use provider names/logos supplied by the source, deduplicate categories appropriately, validate outbound HTTPS destinations, and open external links with safe new-tab behavior.

Always provide a useful availability link beneath a valid catalog movie, even before enrichment finishes. If the source has no listings for the selected country, say that no providers are listed and retain the link to check availability. Distinguish that state from unavailable service/failed lookup. Do not infer theatrical, subscription, or rental availability from release date or popularity.

Serve country configuration and a bounded availability batch API for visible cards, with a maximum of 50 movie IDs per request. Cache records by movie and region, deduplicate in-flight requests per key, use bounded concurrency, and avoid one global lock across network work. Successful availability entries expire after six hours; missing records expire after a shorter interval. Transient failures are retryable and are never permanent missing records. Bound cache size and provide refreshed/checked timestamps.

Show visible JustWatch attribution beside availability information and retain TMDB attribution. Availability and catalog release-date freshness are separate concepts.

## Catalog scope, refresh, and provenance

Interpret latest movies as films with a primary release date from 1 January 2026 through 30 September 2026, inclusive, across languages and countries; preserve the existing historical catalog. Upcoming films after the cutoff cannot enter released-movie shelves. The normal discovery surface uses TMDB's non-adult movie scope and excludes video-only entries. Report this scope explicitly in refresh metadata rather than describing it as every film in existence.

Read-only investigation established the following starting facts:

- The large local CSV contains 1,472,679 rows, including 19,358 records dated January–September 2026. It is an input source, not proof of current global coverage.
- Those 19,358 recent records contain no rows with at least 100 votes. The current global minimum-vote filter therefore excludes them from the built model unless a later supplement supplies updated information.
- The current supplement contains 100 popular films and 56 dated January–September 2026. It cannot establish a complete date-bounded refresh.
- Live discovery for September returned 3,964 reported results over 199 pages. A whole January–September query returned 20,001 results over 1,001 pages; a single large query is unsuitable for verified coverage.
- The configured credential successfully accessed country configuration, discovery, and movie availability without being disclosed in logs or documentation.

Replace the fixed five-page popular refresh with release-date discovery over bounded date windows. Start with monthly partitions and subdivide when a partition would exceed the supported page range. Walk every page in each partition, deduplicate by TMDB ID, verify returned dates, and record discovered IDs, page totals, actual counts, retries, and failed requests. If a single-day partition still exceeds limits, split with non-overlapping additional filters or mark that partition incomplete; do not silently truncate and claim completion.

Fetch detailed metadata, credits, and keywords for discovered films with bounded workers and a shared request budget. Respect `Retry-After`, retry recoverable failures with backoff, and stop on invalid authentication. Checkpoint progress so a large refresh can resume without repeating successful work. Start by carrying forward existing valid records; supplement failures must not delete usable metadata or credits. A partial run may save staging/checkpoints but does not replace the current successful catalog with an incomplete snapshot.

Publish a refresh coverage report containing cutoff, retrieval time, source names/checksums, per-window totals, unique IDs, invalid/excluded rows and reasons, missing dates, details/credits success counts, feature coverage, and remaining failed IDs. Source totals may change during a run, so flag count drift and perform a bounded reconciliation pass. Claim complete discovery only when the recorded scope and verification support it. Never claim that TMDB itself contains every movie globally.

Keep a **searchable catalog separate from recommendation eligibility**. Include valid recent films regardless of vote count; missing overview, genre, or poster does not erase a real film from title search or recent-release browsing. Use honest missing-data states. Eligibility for theme-based ranking requires an actual usable content signal, and user-selected rating/vote filters remain strict. New/unrated titles can appear in recent-release discovery without inventing quality evidence.

Use an indexed local catalog store for paginated title/metadata browsing and canonical movie lookup. Keep it separate from personal library storage so model/catalog publication cannot overwrite user data. The in-memory recommendation pool contains the historical recommendation corpus and recent films with usable content, rather than loading the entire multi-million-row source into application memory. Import large source files in chunks and inspect memory during the complete build/startup.

Merge historical and refreshed credits by movie ID, including the tracked TMDB 5000 credits file. Do not erase prior credits when an enrichment call fails. Catalog details fall back to known local cast/director metadata during media-service outages.

Create a compact, normalized, versioned catalog seed from the supplied sources and refreshed recent films. Keep the 650 MB raw source outside ordinary Git delivery. Clean checkout provisioning must use either the compact seed or a configured versioned artifact URL with checksum verification; the tracked TMDB 5000 source provides a documented limited/offline fallback. A fallback must report reduced coverage, and cannot satisfy the September refresh acceptance check. Deployment uses a validated full snapshot when available rather than making a massive live refresh part of every web-service boot.

## Model publication and recommendation behavior

Build data and models into immutable generation directories. A manifest identifies pipeline version, catalog generation, cutoff, ordered-ID hash, matrix rows/columns, vectorizer field order/dimensions, embedding backend/dimensions, package versions, and artifact checksums. Validate every contract before updating the active-generation pointer atomically. A failed refresh/build leaves the preceding generation active. Runtime loads one generation and rejects mixed, incompatible, or corrupt artifacts with an actionable startup error.

Honor explicit recommendation filters without silent relaxation. An empty or short valid result is a legitimate outcome with useful explanation. Apply watched exclusions to every strategy, including popular/genre fallbacks. Construct profiles from a bounded recent history sample, while obtaining the full watched-ID set separately for exclusion. Negative-only profiles must apply negative-content penalties and exclusions, with an honest explanation of the fallback strategy.

Hybrid requests accept real seed IDs, real genres, or both; require at least one recognized signal with effective nonzero weight. Unknown seeds do not silently become another film. The blend screen defaults to explicitly shown saved history for authenticated users and offers a visible manual-seed mode; guests use manual seeds or genres. Present a complementary blend slider with effective weights and a source summary. A single active signal receives the full effective weight, with that behavior shown to the user.

Separate signup choices, persisted preferences, genre browsing filters, and hybrid genres in frontend state. Use one server-advertised genre limit consistent with all supported catalog genres. Preserve chip focus and expose selection state. Popular fallback, exact title, partial title, and thematic search must be distinguishable response states; no-signal nonsense queries must not be described as meaningful theme matches.

Correct recall denominators and label attribute metrics as proxies. Compare updated ranking with popular/genre baselines and deterministic qualitative fixtures that cover plot/theme relevance and known successful franchise neighbors. Tune plot emphasis and diversity based on those comparisons rather than blindly increasing one weight. Keep optional neural embeddings as an evaluated option; do not make an unmeasured large model download a mandatory deployment dependency.

Human satisfaction cannot be established without human judgments or real held-out interactions. Report available evaluation evidence and that limitation; do not invent a user-interaction dataset or promise that every recommendation is subjectively correct.

## Backend integrity and personal-data behavior

Add a durable per-user session version, include it in new tokens, and enforce it during authentication. Changing a password increments the version and invalidates old sessions. Existing tokens without the new claim are rejected after migration, requiring sign-in without deleting account data. Reuse one password validator for signup and changes. Distinguish normal browser sign-out from an explicit all-session revocation action.

Use versioned dialect-aware migrations for fresh and legacy SQLite/PostgreSQL schemas. Compile timestamps through the database dialect, backfill required values, and add missing indexes/constraints after checking existing data. Preserve duplicate or invalid legacy records through an explicit documented repair policy rather than dropping user rows silently. Back up the local personal database before any live migration; migration tests use disposable databases.

Register SQLite connection setup before any engine connection is opened, so every pooled connection enables foreign keys and the intended journal mode. Enable connection health checks. Map known uniqueness conflicts and unavailable databases to controlled API responses with rollback and retry guidance rather than leaking a stack trace or switching silently to another database. Provide database/catalog readiness distinct from simple process liveness.

Validate finite bounded numbers and stripped nonempty titles in schemas. Resolve canonical title, genres, artwork, and community rating server-side for library writes; do not trust client-supplied movie metadata. Reject unknown new movie IDs with a clear response. Preserve existing historical personal entries even when the refreshed catalog cannot resolve them.

Saving/updating a watched record and moving it from watchlist are transactional. A watched film cannot simultaneously be added to the watchlist through a different branch. Custom lists may contain watched films. Repeated mutations are idempotent where appropriate, and concurrent duplicate writes have defined outcomes. Nullable PATCH uses supplied-field semantics: omitted fields remain unchanged, explicit null clears a rating/note. Use an accessible in-app editor for rating and note updates, allowing each to be changed independently.

List owners can view and manage private lists, edit title/description/visibility, and remove items. Public sharing is available only for public lists; unauthenticated access to private lists stays denied. Owner routes use ownership checks independent of public share links. Whitespace-only list titles are invalid after normalization.

Paginate watched history, watchlist, custom-list summaries/items, public list items, and archive browsing with bounded page sizes, totals, and stable ordering. Avoid loading every item to show a list summary. Profile hydration returns identity/preferences/counts and a bounded recent sample; dedicated endpoints load additional pages. Audit every consumer when response contracts change. Full personal-data exports remain complete independently of pagination.

## Frontend state, resilience, and accessibility

Centralize request handling, parsed server validation errors, abort/generation ownership, authentication versioning, and meaningful retry states. Malformed stored preferences must not crash initialization. Stale search, details, profile, country, or session responses cannot overwrite newer state. Reset details/actions while a different movie loads.

After a mutation, update canonical shared state from its response and await required reconciliation before painting final labels. Watched/bookmarked labels and accessible names match the current action. Do not refetch all personal collections multiple times per mutation. Disable only the affected control while its request is pending and prevent duplicate submission. Failures remain visible with a practical retry; health, genre, and profile loading fail independently where possible.

Use accessible autocomplete with named input, listbox/option semantics, active-result state, ArrowUp/ArrowDown, Enter, Escape, and results announcements. All forms/selects have explicit labels and understandable validation. Dialogs/drawers restore focus, prevent background interaction, and close predictably. Use native semantics where possible, meaningful pressed/tab states where needed, visible keyboard focus, at least 4.5:1 contrast for ordinary text, 3:1 for qualifying large text, and approximately 44px touch targets for primary and icon controls. Support reduced-motion preferences and avoid essential information conveyed only through animation or color.

Archive genre/year/sort controls query the full published searchable catalog, not a handful of preselected shelves. Include older decades, including pre-1970 films, and expose pagination. Replace unsupported "weekly" or "now playing" claims with truthful shelf labels and catalog/provider freshness timestamps unless actual refreshed evidence supports those claims.

## Finding-to-change and acceptance ledger

All entries below are **planned**, not completed. During implementation, record touched files, verification commands/results, and final status for each ID. The original audit supplies reproduction details and severity.

| ID | Required change | Acceptance evidence |
|---|---|---|
| F01 | Convert sparse thematic-query results correctly. | Suggested themes, title queries, and nonsense queries return defined responses without 500s. |
| F02 | Keep explicit genre rating/vote thresholds strict. | Every result meets thresholds; impossible thresholds return an empty list. |
| F03 | Apply dislikes and exclusions in negative-only fallbacks. | One-star-only fixtures exclude watched IDs and demonstrate negative-profile influence. |
| F04 | Separate bounded profiling history from complete watched exclusion. | A library with more than 200 records never returns an older watched ID when hidden. |
| F05 | Remove fabricated hybrid seeds/genres; validate effective signals. | Genre-only, seed-only, combined, and empty inputs have truthful defined behavior. |
| F06 | Move/manage mobile navigation at viewport level. | 390px navigation bounds, keyboard focus, Escape, scroll isolation, expanded state. |
| F07 | Make topmost dialog own keyboard/background behavior. | Search → details → list selection focus/Escape/close-restoration checks. |
| F08 | Implement keyboard-operable autocomplete. | Arrow keys + Enter select seeds and quick-add results; Escape closes suggestions. |
| F09 | Fix contrast across all active/hover button states. | Measured text/background contrast meets the applicable threshold. |
| F10 | Correct Render runtime and consistent Python-version selection. | Blueprint schema/configuration check and documented compatible startup. |
| F11 | Provide reproducible data/model provisioning. | Clean checkout builds from a valid compact seed/artifact without the untracked raw CSV. |
| F12 | Validate/stage refresh and preserve previous good generations. | Empty discovery, failed details, malformed CSV, and interruption tests leave active data usable. |
| F13 | Correct recall and compare independent/proxy baselines honestly. | Numeric denominator fixture, deterministic evaluator output, labelled evidence/limitations. |
| F14 | Revoke old sessions after password change; share validation. | Old token gets 401, new sign-in works, numeric-password rules agree. |
| F15 | Merge/preserve credits from all valid sources. | Known historical credits retained; refreshed feature-coverage counts recorded. |
| F16 | Evaluate/tune plot emphasis and diversification. | Before/after theme fixtures, baseline comparisons, and preserved franchise cases. |
| F17 | Truthful search match types and score presentation. | Exact/partial/theme/no-signal response checks; no fabricated match percentages. |
| F18 | Expose real saved-history/manual-seed hybrid sources. | Submitted IDs match the visible selected source; no cross-screen hidden dependence. |
| F19 | Synchronize complementary blend control and effective labels. | Control value, displayed weights, submitted weights, and effective weights agree. |
| F20 | Separate genre state and align API limits. | All supported selections accepted; browsing cannot silently alter saved/signup preferences. |
| F21 | Preserve chip focus and expose selected state. | Repeated keyboard selection keeps focus; pressed/checked state matches visuals. |
| F22 | Label search/select/remove controls. | Accessible names remain meaningful after input and include movie-specific actions. |
| F23 | Refresh canonical action state after mutations. | Card/modal labels immediately agree after save, bookmark, removal, and move. |
| F24 | Guard stale asynchronous responses and reset detail actions. | Delayed reversed-order search/details/session/provider fixtures retain the newest state. |
| F25 | Show recoverable errors and prevent duplicate submission. | Startup partial failures and failed mutations show correct retry/pending states. |
| F26 | Support nullable clearing and independent rating/note editing. | Null PATCH clears fields, omission preserves them, editor saves each independently. |
| F27 | Validate metadata and use canonical server-side catalog records. | Unknown IDs/blank titles/nonfinite values rejected; spoofed metadata cannot be persisted. |
| F28 | Enforce watched/watchlist invariant on every branch. | Add/update/move/repeated/concurrent scenarios maintain consistent membership. |
| F29 | Add private-list owner management and valid titles. | Owner can view/edit/remove; another user cannot; private share UI is unavailable. |
| F30 | Implement URL/history routing and public-list lifecycle. | Reload, Back/Forward, shared-list exit, and authenticated-route checks. |
| F31 | Query full catalog with archive filters/pagination. | Old/pre-1970 fixtures, later pages, global sorting, genre/year filters return correctly. |
| F32 | Replace unsupported freshness copy and publish provenance. | Shelf labels and timestamps match the actual catalog/provider source. |
| F33 | Remove global network serialization. | Different movie requests overlap within bounded concurrency; same-key requests deduplicate. |
| F34 | Expire/bound caches and distinguish temporary failures. | Failed-then-success lookup recovers; TTL/cache bounds and late image/provider updates work. |
| F35 | Version and validate dialect-aware legacy migrations. | Fresh/legacy SQLite tests; PostgreSQL migration execution when a disposable service is available. |
| F36 | Configure SQLite before the first pooled connection. | First and subsequent connections enforce foreign keys and the configured journal mode. |
| F37 | Handle database races/failures and add readiness. | Duplicate writes controlled; rollback works; database failure gives degraded readiness. |
| F38 | Publish and enforce immutable artifact-manifest contracts. | Mismatched row order/features/checksum and interrupted build rejected without replacing active bundle. |
| F39 | Paginate collections and eliminate summary N+1/full reloads. | Stable multi-page totals/items; bounded responses and measured summary-query behavior. |
| F40 | Add hermetic behavior coverage and CI. | Reproduced defects covered with disposable data, stubbed TMDB, and clean build/test jobs. |
| F41 | Lock compatible dependencies and document update workflow. | Fresh environment installs from the lock; dependency consistency and compatibility checks. |
| F42 | Respect reduced motion. | Emulated preference removes nonessential reveal/transition animation without hiding content. |
| F43 | Enlarge small actionable targets. | Mobile hit areas verified without overlap or obscured neighboring controls. |

## Validation and delivery requirements

Preserve a baseline of the existing 12 passing tests, but replace their dependency on live media requests and incidental generated models with hermetic fixtures where appropriate. Write regression tests around observable defects and important invariants, not trivial implementation mirrors. Use disposable SQLite databases, media stubs, artificial races/delays, and small deterministic model generations.

Establish the smallest useful lint/static-check/frontend-syntax and CI checks for this Python/vanilla-JavaScript stack. Run the appropriate static checks, lint, tests, and build in order for each major group. Validate dependency installation and the clean-checkout data/artifact path separately from the current virtual environment.

Run live UI verification on a separate local server with a disposable personal database. Inspect desktop/mobile views together, including providers, recent releases, authentication, profile preferences, all recommendation modes, search, dialogs, library edits, private/public lists, routing, pagination, reduced motion, loading/error states, and console output. Fix the observed batch of defects and perform a bounded confirmation round.

Perform the actual live date-bounded refresh, validate its coverage report, build the new generation, and confirm recent titles are discoverable through the cutoff. Do not substitute mocked refresh tests for the requested real catalog update. Inspect memory/startup behavior with the complete new generation before claiming deployment readiness.

Keep local and deployed checks distinct. PostgreSQL execution, Render deployment, dedicated security scanning, subjective recommendation quality, and human satisfaction cannot be called verified without their corresponding evidence. The prior dedicated security scan did not start; fixing the local authentication finding does not turn that audit into an exhaustive security certification.

The final delivery must include verified finding IDs, UI screenshots or a working preview, a concise catalog coverage/freshness summary, watch-provider behavior, executed checks, and any remaining material limitations. Do not claim all findings fixed merely because source edits exist. No remote deployment, push, or external publication is part of this design.

## References

- `PROJECT_AUDIT.md`: 43 current-working-tree findings and reproductions.
- User image: `C:/Users/AYUSH/AppData/Local/Temp/codex-clipboard-8683cfea-364b-48b1-8a64-e47bc2823889.png`.
- [TMDB movie watch providers](https://developer.themoviedb.org/reference/movie-watch-providers): regional availability, watch-page links, and JustWatch attribution.
- [TMDB discover movies](https://developer.themoviedb.org/reference/discover-movie): release-date filters and paginated discovery.
- [TMDB rate limiting](https://developer.themoviedb.org/docs/rate-limiting): respect changing service limits and HTTP 429 responses.
- [Render Blueprint specification](https://render.com/docs/blueprint-spec): deployment runtime configuration.
