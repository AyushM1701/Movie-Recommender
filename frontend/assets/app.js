/* ============================================================
   CineMatch — Modern Cinema Discovery Engine
   ============================================================ */

import {safeStoredArray, RequestOwnership, blendInputs, routeFromHash} from './state.mjs';
const ownership = new RequestOwnership();
const silentError = (error) => error?.name === 'AbortError';
const TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500";
const TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280";

const state = {
  token: localStorage.getItem("cm_token"),
  userId: localStorage.getItem("cm_user_id"),
  username: localStorage.getItem("cm_username"),
  genres: new Set(safeStoredArray(localStorage.getItem("cm_genres"))),
  signupGenres: new Set(),
  browseGenres: new Set(),
  hybridGenres: new Set(),
  hybridSeeds: [],
  hybridSource: 'manual',
  country: localStorage.getItem('cm_country') || 'IN',
  availability: new Map(),
  watchedIds: new Set(),
  watchlistedIds: new Set(),
  history: [],
  pages: {archive:1, watched:1, watchlist:1, lists:1, shared:1, owner:1},
  currentPage: 'explore',
  modalStack: [],
  drawerOpen: false,
  exploreRequest: null,
  pendingMutations: new Set(),
  catalog: null,
  allGenres: [],
  profile: null,
  personalized: [],
  historySeeds: [],
  exploreCatalog: null,
  exploreDecade: "all",
  exploreMinRating: 0,
  exploreSortBy: "popularity",
  watchlist: [],
  customLists: [],
  activeMovie: null,
  activeMovieForList: null,
  lastFocusedElement: null,
};

const elements = {
  brandLink: document.getElementById("brand-link"),
  authView: document.getElementById("auth-view"),
  appView: document.getElementById("app-view"),
  profileSidebar: document.getElementById("profile-sidebar"),
  dashboardMain: document.getElementById("dashboard-main"),
  navAuthButton: document.getElementById("nav-auth-button"),
  navLogoutButton: document.getElementById("nav-logout-button"),
  navDrawerAuthButton: document.getElementById("nav-drawer-auth-button"),
  navDrawerLogoutButton: document.getElementById("nav-drawer-logout-button"),
  navMenu: document.getElementById("app-nav"),
  navToggle: document.getElementById("nav-toggle"),
  navCloseButton: document.getElementById("nav-close-button"),
  navOverlay: document.getElementById("nav-overlay"),
  authAlert: document.getElementById("auth-alert"),
  loginPanel: document.getElementById("login-panel"),
  signupPanel: document.getElementById("signup-panel"),
  loginForm: document.getElementById("login-form"),
  signupForm: document.getElementById("signup-form"),
  passwordForm: document.getElementById("password-form"),
  signupGenreGrid: document.getElementById("signup-genre-grid"),
  signupGenreCount: document.getElementById("signup-genre-count"),
  profileGenreGrid: document.getElementById("profile-genre-grid"),
  browseGenreGrid: document.getElementById("browse-genre-grid"),
  profileUsername: document.getElementById("profile-username"),
  profileAvatar: document.getElementById("profile-avatar"),
  profileLibraryCount: document.getElementById("profile-library-count"),
  profileWatchlistCount: document.getElementById("profile-watchlist-count"),
  profileGenreCount: document.getElementById("profile-genre-count"),
  navLibraryBadge: document.getElementById("nav-library-badge"),

  // Explore page
  exploreTrendingGrid: document.getElementById("explore-trending-grid"),
  exploreTopRatedGrid: document.getElementById("explore-top-rated-grid"),
  exploreDecadeGrid: document.getElementById("explore-decade-grid"),
  exploreDecadeTitle: document.getElementById("explore-decade-title"),
  exploreDecadeDesc: document.getElementById("explore-decade-desc"),
  exploreDecadeFilters: document.getElementById("explore-decade-filters"),
  exploreMinRating: document.getElementById("explore-min-rating"),
  exploreSortBy: document.getElementById("explore-sort-by"),

  // Personalized & Labs
  personalizedGrid: document.getElementById("personalized-grid"),
  personalReason: document.getElementById("personal-reason"),
  excludeWatchedToggle: document.getElementById("exclude-watched-toggle"),
  genreResults: document.getElementById("genre-grid-results"),
  genreTopN: document.getElementById("genre-top-n"),
  genreMinRating: document.getElementById("genre-min-rating"),
  runGenreRecommend: document.getElementById("run-genre-recommend"),
  historyResults: document.getElementById("history-grid-results"),
  hybridResults: document.getElementById("hybrid-grid-results"),
  historySeeds: document.getElementById("history-seeds"),

  // Library & Watchlist & Lists
  libraryList: document.getElementById("library-list"),
  watchlistGrid: document.getElementById("watchlist-grid"),
  customListsContainer: document.getElementById("custom-lists-container"),
  libWatchedCount: document.getElementById("lib-watched-count"),
  libWatchlistCount: document.getElementById("lib-watchlist-count"),
  libListsCount: document.getElementById("lib-lists-count"),
  exportCsvBtn: document.getElementById("export-csv-btn"),
  exportJsonBtn: document.getElementById("export-json-btn"),

  // Shared list
  sharedListTitle: document.getElementById("shared-list-title"),
  sharedListCreator: document.getElementById("shared-list-creator"),
  sharedListDescription: document.getElementById("shared-list-description"),
  sharedListGrid: document.getElementById("shared-list-grid"),
  copySharedListLink: document.getElementById("copy-shared-list-link"),
  backToExploreBtn: document.getElementById("back-to-explore-btn"),

  // Modals & Toasts
  toastStack: document.getElementById("toast-stack"),
  movieModalShell: document.getElementById("movie-modal-shell"),
  movieModalClose: document.getElementById("movie-modal-close"),
  movieModalPoster: document.getElementById("movie-modal-poster"),
  movieModalTitle: document.getElementById("movie-modal-title"),
  movieModalTagline: document.getElementById("movie-modal-tagline"),
  movieModalYear: document.getElementById("movie-modal-year"),
  movieModalRuntime: document.getElementById("movie-modal-runtime"),
  movieModalRatingBadge: document.getElementById("movie-modal-rating-badge"),
  movieModalDirectorName: document.getElementById("movie-modal-director-name"),
  movieModalOverview: document.getElementById("movie-modal-overview"),
  movieModalGenres: document.getElementById("movie-modal-genres"),
  movieModalSave: document.getElementById("movie-modal-save"),
  movieModalWatchlistBtn: document.getElementById("movie-modal-watchlist-btn"),
  movieModalAddListBtn: document.getElementById("movie-modal-add-list-btn"),
  movieModalExternalLinks: document.getElementById("movie-modal-external-links"),
  movieModalBackdropImg: document.getElementById("movie-modal-backdrop-img"),
  movieModalPlayTrailerBtn: document.getElementById("movie-modal-play-trailer-btn"),
  movieModalTrailerWrapper: document.getElementById("movie-modal-trailer-wrapper"),
  movieModalTrailerFrame: document.getElementById("movie-modal-trailer-frame"),
  movieModalBackdropWrapper: document.getElementById("movie-modal-backdrop-wrapper"),
  modalFactReleaseDate: document.getElementById("modal-fact-release-date"),
  modalFactBudget: document.getElementById("modal-fact-budget"),
  modalFactRevenue: document.getElementById("modal-fact-revenue"),
  modalFactVotes: document.getElementById("modal-fact-votes"),
  movieModalCastGrid: document.getElementById("movie-modal-cast-grid"),
  movieModalSimilarGrid: document.getElementById("movie-modal-similar-grid"),

  // Custom List Modal
  createListModalShell: document.getElementById("create-list-modal-shell"),
  createListModalClose: document.getElementById("create-list-modal-close"),
  openCreateListModal: document.getElementById("open-create-list-modal"),
  createListForm: document.getElementById("create-list-form"),
  createListTitle: document.getElementById("create-list-title"),
  createListDescription: document.getElementById("create-list-description"),
  createListIsPublic: document.getElementById("create-list-is-public"),
  addToListModalShell: document.getElementById("add-to-list-modal-shell"),
  addToListModalClose: document.getElementById("add-to-list-modal-close"),
  addToListMovieTitle: document.getElementById("add-to-list-movie-title"),
  pickListContainer: document.getElementById("pick-list-container"),

  // Search Modal
  searchModalShell: document.getElementById("search-modal-shell"),
  searchModalClose: document.getElementById("search-modal-close"),
  navSearchButton: document.getElementById("nav-search-button"),
  mobileSearchToggle: document.getElementById("mobile-search-toggle"),
  mainSearchForm: document.getElementById("main-search-form"),
  mainSearchInput: document.getElementById("main-search-input"),
  mainSearchSubmit: document.getElementById("main-search-submit"),
  mainSearchClear: document.getElementById("main-search-clear"),
  mainSearchGrid: document.getElementById("main-search-grid-results"),
  searchFeedbackBanner: document.getElementById("search-feedback-banner"),
};

/* ── Utilities ─────────────────────────────────────────────── */

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatCurrency(amount) {
  if (!amount || amount <= 0) return "N/A";
  if (amount >= 1e9) return `$${(amount / 1e9).toFixed(1)}B`;
  if (amount >= 1e6) return `$${(amount / 1e6).toFixed(1)}M`;
  return `$${amount.toLocaleString()}`;
}

function formatRuntime(minutes) {
  if (!minutes || minutes <= 0) return "N/A";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function createPosterMarkup(movie) {
  const title = escapeHtml(movie.title || "Unknown title");
  const src = getPosterUrl(movie.poster_path);
  if (src) {
    return `
      <img
        src="${src}"
        alt="${title}"
        loading="lazy"
        onload="this.classList.add('loaded')"
        onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='grid';"
      /><div class="movie-poster-fallback" style="display:none">${title.split(/\s+/).slice(0, 2).map(w => w[0] || "").join("").toUpperCase() || "CM"}</div>
    `;
  }
  const initials = title
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] || "")
    .join("")
    .toUpperCase();
  return `<div class="movie-poster-fallback">${initials || "CM"}</div>`;
}

function getPosterUrl(posterPath) {
  if (typeof posterPath !== "string") return null;
  const cleanPath = posterPath.trim();
  if (!/^\/[A-Za-z0-9._-]+\.(?:jpe?g|png|webp)$/i.test(cleanPath)) return null;
  return `${TMDB_IMAGE_BASE}${cleanPath}`;
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  elements.toastStack.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.2s ease";
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

function renderLoading(container, count = 4) {
  if (!container) return;
  container.innerHTML = "";
  for (let index = 0; index < count; index += 1) {
    const placeholder = document.createElement("div");
    placeholder.className = "movie-card skeleton-card";
    placeholder.setAttribute("aria-hidden", "true");
    container.appendChild(placeholder);
  }
}

function renderStatus(container, message, retry) {
  if (!container) return;
  container.innerHTML = "";
  const wrapper = document.createElement("div");
  wrapper.className = "inline-status";
  const copy = document.createElement("p");
  copy.className = "muted-copy";
  copy.textContent = message;
  wrapper.appendChild(copy);
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-secondary";
    button.textContent = "Try again";
    button.addEventListener("click", retry);
    wrapper.appendChild(button);
  }
  container.appendChild(wrapper);
}

/* ── HTTP API Client ───────────────────────────────────────── */

async function api(path, options = {}) {
  const session = ownership.session;
  const token = state.token;
  const request = options.owner ? ownership.begin(options.owner) : null;
  const {owner, ...fetchOptions} = options;
  const headers = new Headers(options.headers || {});
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, {
    ...fetchOptions,
    signal: request?.signal || options.signal,
    headers,
  });
  if (session !== ownership.session || (request && !request.isCurrent())) throw new DOMException('Superseded request', 'AbortError');

  if (res.status === 401 && token && token === state.token) {
    clearAuth();
    showToast("Session expired. Please sign in again.", "error");
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const fallback = res.status === 503
      ? "CineMatch is temporarily unavailable. Please retry in a moment."
      : "Request failed";
    const err = await res.json().catch(() => ({ detail: fallback }));
    let errorMsg = err.detail || fallback;
    if (Array.isArray(errorMsg)) {
        errorMsg = errorMsg.map(e => e.msg || JSON.stringify(e)).join(", ");
    } else if (typeof errorMsg === 'object') {
        errorMsg = JSON.stringify(errorMsg);
    }
    throw new Error(errorMsg);
  }

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = await res.json();
    if (session !== ownership.session || (request && !request.isCurrent())) throw new DOMException('Superseded request', 'AbortError');
    return data;
  }
  return res.text();
}

/* ── Auth Management ───────────────────────────────────────── */

function setAuth(token, userId, username, genres = []) {
  ownership.resetSession();
  resetPersonalPages();
  state.profile=null;state.history=[];state.watchlist=[];state.customLists=[];state.watchedIds.clear();state.watchlistedIds.clear();state.pendingMutations.clear();
  state.token = token;
  state.userId = userId;
  state.username = username;
  state.genres = new Set(genres);
  state.hybridSource = 'saved';

  localStorage.setItem("cm_token", token);
  localStorage.setItem("cm_user_id", String(userId));
  localStorage.setItem("cm_username", username);
  localStorage.setItem("cm_genres", JSON.stringify(genres));

  updateNavAuthUI();
  hydratePersonal();
}

function clearAuth() {
  ownership.resetSession();
  resetPersonalPages();
  state.token = null;
  state.userId = null;
  state.username = null;
  state.genres = new Set();
  state.profile = null;
  state.watchlist = [];
  state.customLists = [];
  state.history = [];
  state.watchedIds.clear();
  state.watchlistedIds.clear();
  state.hybridSource = 'manual';
  state.hybridGenres.clear();
  state.pendingMutations.clear();
  state.modalStack.slice().reverse().forEach(entry => closeModal(entry.shell));
  renderLibraryShelf();
  renderWatchlist();
  renderCustomLists();
  refreshActionLabels();

  localStorage.removeItem("cm_token");
  localStorage.removeItem("cm_user_id");
  localStorage.removeItem("cm_username");
  localStorage.removeItem("cm_genres");

  updateNavAuthUI();
  switchPage("explore");
}

function updateNavAuthUI() {
  const isAuthed = Boolean(state.token);

  document.querySelectorAll(".auth-only-nav").forEach((el) => {
    el.classList.toggle("hidden", !isAuthed);
  });
  if (elements.dashboardMain) {
    elements.dashboardMain.classList.toggle("full-width-when-guest", !isAuthed);
  }

  if (isAuthed) {
    elements.navAuthButton.classList.add("hidden");
    elements.navLogoutButton.classList.remove("hidden");
    elements.navDrawerAuthButton.classList.add("hidden");
    elements.navDrawerLogoutButton.classList.remove("hidden");
  } else {
    elements.navAuthButton.classList.remove("hidden");
    elements.navLogoutButton.classList.add("hidden");
    elements.navDrawerAuthButton.classList.remove("hidden");
    elements.navDrawerLogoutButton.classList.add("hidden");
  }
}

function showAuth(updateURL = true) {
  if (updateURL && location.hash !== '#auth') history.pushState(null, '', '#auth');
  elements.authView.classList.remove("hidden");
  elements.appView.classList.add("hidden");
  elements.authAlert.classList.add("hidden");
  closeMobileNav();
  elements.loginForm?.username?.focus();
}

async function fetchProfile() {
  if (!state.token) return;
  try {
    const profile = await api("/auth/me", {owner:'profile'});
    state.profile = profile;
    state.genres = new Set(profile.genres || []);
    localStorage.setItem("cm_genres", JSON.stringify([...state.genres]));
    renderProfile();
    (profile.history || []).forEach(item => state.watchedIds.add(item.movie_id));
    refreshActionLabels();
    renderHybridSummary();
  } catch (err) {
    if (silentError(err)) return;
    renderStatus(document.getElementById('profile-status'), err.message, fetchProfile);
  }
}

function renderProfile() {
  if (!state.profile) return;
  elements.profileUsername.textContent = state.profile.username || "Film Lover";
  elements.profileAvatar.textContent = (state.profile.username || "CM")[0].toUpperCase();
  elements.profileLibraryCount.textContent = state.profile.total_watched || 0;
  elements.profileGenreCount.textContent = (state.profile.genres || []).length;
  if (elements.libWatchedCount) elements.libWatchedCount.textContent = state.profile.total_watched || 0;

  renderProfileGenreChips();
  document.getElementById('profile-status').innerHTML = '';
}

function renderProfileGenreChips() {
  renderGenreChips(elements.profileGenreGrid, state.genres);
  renderGenreChips(elements.browseGenreGrid, state.browseGenres);
  renderGenreChips(elements.signupGenreGrid, state.signupGenres, () => {
    elements.signupGenreCount.textContent = `${state.signupGenres.size} selected (minimum 2)`;
  });
  renderGenreChips(document.getElementById('hybrid-genre-grid'), state.hybridGenres, renderHybridSummary);
}

function renderGenreChips(container, selected, changed = () => {}) {
  if (!container) return;
  // Reconcile only hydration; clicking updates the same button, preserving keyboard focus.
  container.replaceChildren();
  state.allGenres.forEach(genre => {
    const chip = document.createElement('button');
    chip.type = 'button'; chip.className = 'genre-chip'; chip.textContent = genre;
    const update = () => {chip.classList.toggle('selected', selected.has(genre)); chip.setAttribute('aria-pressed', String(selected.has(genre)));};
    update();
    chip.onclick = () => { selected.has(genre) ? selected.delete(genre) : selected.add(genre); update(); changed(); };
    container.append(chip);
  });
}

/* ── Navigation & Page Routing ─────────────────────────────── */

function switchPage(pageName, updateURL = true) {
  if (pageName === 'auth') { showAuth(updateURL); return; }
  if (updateURL) {
    const hash = `#${pageName}`;
    if (location.hash !== hash) history.pushState(null, '', hash);
  }
  state.currentPage = pageName;
  // Update nav links
  document.querySelectorAll("[data-page]").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === pageName);
    if (link.dataset.page === pageName) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });

  // Check auth requirement
  if (!state.token && (pageName === "for-you" || pageName === "library" || pageName === "profile")) {
    showAuth(false);
    return;
  }

  elements.authView.classList.add("hidden");
  elements.appView.classList.remove("hidden");

  // Switch pages
  document.querySelectorAll(".dashboard-page").forEach((page) => {
    page.classList.toggle("active", page.dataset.pageName === pageName);
  });

  closeMobileNav();

  // Load data for specific page
  if (pageName === "explore") {
    loadExploreCatalog();
  } else if (pageName === "for-you") {
    fetchPersonalized();
  } else if (pageName === "genres") {
    loadGenrePage();
  } else if (pageName === "library") {
    hydratePersonal();
  } else if (pageName === 'profile') {
    fetchProfile();
  } else if (pageName === 'hybrid') {
    renderHybridSummary();
  }
  refreshWatchOptions();
}

function openMobileNav() {
  if (state.drawerOpen) return;
  state.drawerOpen = true;
  state.drawerReturnFocus = document.activeElement;
  if (elements.navMenu.parentElement !== document.body) document.body.append(elements.navMenu);
  elements.navMenu.classList.add("open");
  elements.navOverlay.classList.add("active");
  elements.navMenu.setAttribute('role', 'dialog'); elements.navMenu.setAttribute('aria-modal','true'); elements.navMenu.setAttribute('aria-label','Navigation');
  elements.navToggle.setAttribute('aria-expanded', 'true');
  document.querySelector('.site-shell').inert = true;
  document.getElementById('mobile-primary-nav').inert = true;
  document.body.classList.add('modal-open');
  elements.navCloseButton.focus();
}

function closeMobileNav() {
  if (!state.drawerOpen) return;
  state.drawerOpen = false;
  elements.navMenu.classList.remove("open");
  elements.navOverlay.classList.remove("active");
  elements.navToggle.setAttribute('aria-expanded', 'false');
  elements.navMenu.removeAttribute('role'); elements.navMenu.removeAttribute('aria-modal');
  document.querySelector('.topbar-actions').prepend(elements.navMenu);
  syncModalIsolation();
  state.drawerReturnFocus?.focus();
}

function getOpenModal() {
  return state.modalStack.at(-1)?.shell || (state.drawerOpen ? elements.navMenu : null);
}

function openModal(shell, initialFocus) {
  if (!shell) return;
  closeMobileNav();
  const existing = state.modalStack.find(entry => entry.shell === shell);
  if (!existing) state.modalStack.push({shell, returnFocus:document.activeElement});
  else state.modalStack = [...state.modalStack.filter(entry => entry !== existing), existing];
  shell.classList.remove("hidden");
  syncModalIsolation();
  requestAnimationFrame(() => {if(getOpenModal() === shell) (initialFocus || shell.querySelector('button,input'))?.focus();});
}

function closeModal(shell) {
  if (!shell) return;
  const entry = state.modalStack.find(item => item.shell === shell);
  state.modalStack = state.modalStack.filter(item => item.shell !== shell);
  shell.classList.add("hidden");
  if (shell === elements.movieModalShell) {ownership.cancel('details'); elements.movieModalTrailerFrame.src = ''; state.activeMovie = null;}
  if (shell === elements.searchModalShell) ownership.cancel('search');
  syncModalIsolation();
  if (entry?.returnFocus?.isConnected && !entry.returnFocus.closest('.hidden') && !entry.returnFocus.closest('[inert]')) entry.returnFocus.focus();
  else getOpenModal()?.querySelector('button,input')?.focus();
}

function syncModalIsolation() {
  const top = getOpenModal();
  document.querySelector('.site-shell').inert = !!top;
  document.getElementById('mobile-primary-nav').inert = !!top;
  document.body.classList.toggle('modal-open', !!top);
  document.querySelectorAll('.modal-shell').forEach(shell => {
    const active = shell === top;
    shell.inert = !active;
    shell.setAttribute('aria-modal', String(active));
    shell.style.zIndex = String(100 + state.modalStack.findIndex(entry => entry.shell === shell) * 2);
  });
}

function handleModalKeyboard(event) {
  const modal = getOpenModal();
  if (!modal) return;
  if (event.key === "Escape") {
    event.preventDefault();
    if (state.drawerOpen) closeMobileNav();
    else if (modal === elements.movieModalShell) closeMovieDetails();
    else closeModal(modal);
    return;
  }
  if (event.key !== "Tab") return;

  const focusable = [...modal.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter((item) => !item.closest(".hidden") && item.getClientRects().length);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!modal.contains(document.activeElement)) {event.preventDefault();first.focus();return;}
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

/* ── Card Rendering & Interaction ─────────────────────────── */

function renderMovieCard(movie, options = {}) {
  const card = document.createElement("article");
  card.className = "movie-card";
  card.dataset.movieId = movie.id;

  const voteAvg = typeof movie.vote_average === "number" && movie.vote_average > 0 ? movie.vote_average.toFixed(1) : "—";
  const year = movie.release_year || "—";
  const genres = Array.isArray(movie.genres) ? movie.genres.join(", ") : (movie.genres || "");

  const matchBadge = '';

  card.innerHTML = `
    <div class="movie-poster-box">
      ${createPosterMarkup(movie)}
      <div class="card-rating-badge" aria-label="TMDB community rating ${voteAvg} out of 10">${voteAvg}</div>
      ${matchBadge}
      <div class="card-quick-actions">
        <button class="quick-action-btn card-details-trigger" type="button" aria-label="View details for ${escapeHtml(movie.title)}">
          Details
        </button>
        <button class="quick-action-btn card-watchlist-trigger" type="button" aria-label="Add ${escapeHtml(movie.title)} to watchlist">
          Save
        </button>
      </div>
    </div>
    <div class="movie-card-info">
      <h3 class="movie-card-title"><button class="title-details-button" type="button">${escapeHtml(movie.title)}</button></h3>
      <div class="movie-card-sub">
        <span>${year}</span>
        <span class="movie-card-genres">${escapeHtml(genres)}</span>
      </div>
    </div>
  `;

  // Click handler: open rich details modal
  card.addEventListener("click", (e) => {
    if (e.target.closest(".card-watchlist-trigger")) {
      e.stopPropagation();
      quickToggleWatchlist(movie);
      return;
    }
    if (e.target.closest('.card-details-trigger,.title-details-button,.movie-poster-box') && !e.target.closest('a,button:not(.card-details-trigger):not(.title-details-button)')) openMovieDetails(movie.id);
  });
  card.append(createWatchArea(movie.id));
  refreshCardLabel(card, movie);
  queueWatchRefresh();
  return card;
}

function refreshCardLabel(card, movie) {
  const button = card.querySelector('.card-watchlist-trigger');
  if (!button) return;
  const watched = state.watchedIds.has(movie.id);
  const saved = state.watchlistedIds.has(movie.id);
  button.textContent = watched ? 'Watched' : saved ? 'Saved' : 'Save';
  button.disabled = watched || state.pendingMutations.has(`movie:${movie.id}`);
  button.setAttribute('aria-label', watched ? `${movie.title} is in your watched library` : `${saved ? 'Remove' : 'Add'} ${movie.title} ${saved ? 'from' : 'to'} watchlist`);
  button.setAttribute('aria-pressed', String(saved));
}

function refreshActionLabels() {
  document.querySelectorAll('.movie-card[data-movie-id]').forEach(card => refreshCardLabel(card, {id:Number(card.dataset.movieId),title:card.querySelector('h3')?.textContent || 'movie'}));
  if (state.activeMovie) updateModalActionButtons(state.activeMovie);
}

function safeHTTPS(value, fallback = '') {
  try {const url = new URL(value); return url.protocol === 'https:' ? url.href : fallback;} catch {return fallback;}
}

function resetPersonalPages() {
  for (const key of ['watched','watchlist','lists','owner']) state.pages[key] = 1;
}

function cacheAvailability(key, entry, fetchedAt = Date.now()) {
  const checkedAt=Date.parse(entry.checked_at);
  if(Number.isFinite(checkedAt)) fetchedAt=Math.min(fetchedAt,checkedAt);
  state.availability.delete(key);
  state.availability.set(key,{...entry,fetchedAt});
  while(state.availability.size > 512) state.availability.delete(state.availability.keys().next().value);
}

function cachedAvailability(key) {
  const entry=state.availability.get(key);
  if(!entry) return undefined;
  const ttl=entry.status==='available'?6*3600000:entry.status==='not_listed'?15*60000:30000;
  if(Date.now()-entry.fetchedAt>=ttl) {state.availability.delete(key);return undefined;}
  return entry;
}

function createWatchArea(movieId, presentation = 'card') {
  const area = document.createElement('div');
  area.className = 'watch-options'; area.dataset.watchMovieId = movieId;
  area.dataset.watchPresentation = presentation;
  paintWatchArea(area, cachedAvailability(`${state.country}:${movieId}`));
  return area;
}

function paintWatchArea(area, entry) {
  const id = Number(area.dataset.watchMovieId);
  const fallback = `https://www.themoviedb.org/movie/${id}/watch?locale=${state.country}`;
  const link = safeHTTPS(entry?.link, fallback);
  const detailed=area.dataset.watchPresentation==='details';
  const hasProviders=entry?.status === 'available' && entry.providers?.length;
  area.innerHTML = `<span class="watch-region">Watch in ${escapeHtml(state.country)}</span>`;
  if (hasProviders) {
    const providers = document.createElement('div'); providers.className = 'provider-chips';
    entry.providers.slice(0,detailed?entry.providers.length:1).forEach(provider => {
      const badge = document.createElement('a'); badge.className='provider-badge'; badge.href=link; badge.target='_blank'; badge.rel='noopener noreferrer';
      badge.setAttribute('aria-label', `${provider.name}: ${provider.types.map(type => ({flatrate:'subscription',free:'free',ads:'with ads',rent:'rent',buy:'buy'}[type] || type)).join(', ')}. Check availability in ${state.country}`);
      const imageURL = getPosterUrl(provider.logo_path);
      if (imageURL) {const logo = document.createElement('img');logo.src=imageURL;logo.alt='';logo.loading='lazy';badge.append(logo);}
      const name = document.createElement('span');name.textContent=provider.name;badge.append(name);providers.append(badge);
    }); area.append(providers);
  } else {
    const message = document.createElement('p'); message.className='watch-status';
    message.textContent = entry?.status === 'not_listed' ? 'No providers listed in this region.' : entry?.status === 'unavailable' ? 'Availability temporarily unavailable.' : 'Checking availability…';
    area.append(message);
    if (entry?.status === 'unavailable') {const retry = document.createElement('button');retry.type='button';retry.className='watch-retry';retry.textContent='Retry availability';retry.onclick=()=>{state.availability.delete(`${state.country}:${id}`);refreshWatchOptions();};area.append(retry);}
  }
  if(detailed || !hasProviders) {const page = document.createElement('a');page.href=link;page.target='_blank';page.rel='noopener noreferrer';page.className='availability-link';page.textContent='Watch options';page.setAttribute('aria-label',`Check watch options in ${state.country}`);area.append(page);}
  if (detailed && entry?.checked_at) {const checked=document.createElement('small');checked.className='provider-checked';checked.textContent=`Checked ${new Date(entry.checked_at).toLocaleDateString()}`;area.append(checked);}
  const attribution=document.createElement('small');attribution.className='provider-attribution';attribution.textContent='JustWatch / TMDB';area.append(attribution);
}

const queueWatchRefresh = debounce(() => refreshWatchOptions(), 80);
let watchGeneration = 0;
async function refreshWatchOptions() {
  const generation = ++watchGeneration;
  ownership.cancel('providers');
  const country=state.country;
  const areas=[...document.querySelectorAll('[data-watch-movie-id]')].filter(area => area.getClientRects().length && !area.closest('[inert]'));
  areas.forEach(area => paintWatchArea(area,cachedAvailability(`${country}:${area.dataset.watchMovieId}`)));
  const ids=[...new Set(areas.map(area=>Number(area.dataset.watchMovieId)))].filter(id=>id>0&&!cachedAvailability(`${country}:${id}`));
  if(state.token)refreshMembership([...new Set(areas.map(area=>Number(area.dataset.watchMovieId)))]);
  for(let start=0;start<ids.length;start+=50) {
    const batch=ids.slice(start,start+50);
    try {
      const data=await api('/watch/options',{method:'POST',body:JSON.stringify({movie_ids:batch,country}),owner:'providers'});
      if(generation!==watchGeneration||country!==state.country) return;
      (data.movies||[]).forEach(entry=>cacheAvailability(`${country}:${entry.movie_id}`,entry));
    } catch(error) {
      if(silentError(error)||generation!==watchGeneration) return;
      batch.forEach(id=>cacheAvailability(`${country}:${id}`,{status:'unavailable'}));
    }
    areas.filter(area=>batch.includes(Number(area.dataset.watchMovieId))).forEach(area=>paintWatchArea(area,cachedAvailability(`${country}:${area.dataset.watchMovieId}`)));
  }
}

/* ── 1. Explore Page ───────────────────────────────────────── */

async function refreshMembership(ids) {
  for(let start=0;start<ids.length;start+=50) {
    try {
      const data=await api(`/library/status?movie_ids=${ids.slice(start,start+50).join(',')}`,{owner:'membership'});
      data.movies.forEach(item=>{
        if(state.pendingMutations.has(`movie:${item.movie_id}`))return;
        item.watched ? state.watchedIds.add(item.movie_id) : state.watchedIds.delete(item.movie_id);
        item.watchlisted ? state.watchlistedIds.add(item.movie_id) : state.watchlistedIds.delete(item.movie_id);
      });refreshActionLabels();
    }catch(error){if(silentError(error))return;}
  }
}

async function loadExploreCatalog() {
  try {
    if (!state.exploreCatalog || Date.now() - (state.exploreLoadedAt || 0) > 300000) {
      renderLoading(elements.exploreTrendingGrid);
      renderLoading(elements.exploreTopRatedGrid);
      renderLoading(elements.exploreDecadeGrid);
      const data = await api("/explore", {owner:'explore'});
      state.exploreCatalog = data;
      state.exploreLoadedAt = Date.now();
    }
    renderExploreView();
  } catch (err) {
    if (silentError(err)) return;
    console.error("Failed to load explore catalog:", err);
    renderStatus(elements.exploreTrendingGrid, "We could not load the catalog.", loadExploreCatalog);
    renderStatus(elements.exploreTopRatedGrid, "Please try again in a moment.", loadExploreCatalog);
    renderStatus(elements.exploreDecadeGrid, "Catalog filters are temporarily unavailable.", loadExploreCatalog);
  }
}

function renderExploreView() {
  if (!state.exploreCatalog) return;
  const featured = document.getElementById('featured-movie');
  featured.replaceChildren();
  const leading = state.exploreCatalog.trending?.[0] || state.exploreCatalog.top_rated?.[0];
  if (leading) {
    const card=renderMovieCard(leading);card.classList.add('feature-movie');
    const overview=document.createElement('p');overview.className='feature-overview';overview.textContent=leading.overview || 'Discover the story, cast and similar films.';
    card.querySelector('.movie-card-info').append(overview);featured.append(card);
  }
  renderCatalogProvenance();

  // Trending
  if (elements.exploreTrendingGrid) {
    elements.exploreTrendingGrid.innerHTML = "";
    state.exploreCatalog.trending.slice(0, 8).forEach((m) => {
      elements.exploreTrendingGrid.appendChild(renderMovieCard(m));
    });
  }

  // Top Rated
  if (elements.exploreTopRatedGrid) {
    elements.exploreTopRatedGrid.innerHTML = "";
    state.exploreCatalog.top_rated.slice(0, 8).forEach((m) => {
      elements.exploreTopRatedGrid.appendChild(renderMovieCard(m));
    });
  }

  // Decade Showcase Filtered
  renderDecadeSection();
}

async function renderDecadeSection() {
  const decade = state.exploreDecade;
  elements.exploreDecadeTitle.textContent = decade === 'all' ? 'The complete catalogue' : decade === 'before1970' ? 'Cinema before 1970' : `${decade} on screen`;
  const params=new URLSearchParams({page:state.pages.archive,page_size:24,sort:state.exploreSortBy==='popularity'?'popular':state.exploreSortBy,min_rating:state.exploreMinRating});
  if(decade==='before1970')params.set('year_to','1969');
  else if(decade!=='all'){params.set('year_from',String(parseInt(decade,10)));params.set('year_to',String(parseInt(decade,10)+9));}
  const genre=document.getElementById('archive-genre').value;if(genre)params.set('genre',genre);
  renderLoading(elements.exploreDecadeGrid);
  try {
    const data=await api(`/catalog?${params}`,{owner:'archive'});
    elements.exploreDecadeDesc.textContent=`${data.total.toLocaleString()} titles across the published catalogue. Filters and sorting apply to every title.`;
    renderMovies(elements.exploreDecadeGrid,data.movies,'No films match these filters. Try another era or a lower minimum rating.');
    renderPagination(document.getElementById('archive-pagination'),data,page=>{state.pages.archive=page;renderDecadeSection();});
  }catch(error){if(!silentError(error))renderStatus(elements.exploreDecadeGrid,error.message,renderDecadeSection);}
}

function renderMovies(container, movies, empty='No films found for these inputs.') {
  container.replaceChildren();
  if(!movies?.length){renderStatus(container,empty);return;}
  movies.forEach(movie=>container.append(renderMovieCard(movie)));
}

function renderCatalogProvenance() {
  const data=state.catalogMetadata;
  document.getElementById('catalog-freshness').textContent=data ? `Catalogue cutoff: ${data.cutoff || 'not recorded'} · retrieved ${data.retrieved_at ? new Date(data.retrieved_at).toLocaleDateString() : 'date not recorded'} · ${typeof data.scope==='string'?data.scope:'published catalogue'}. Popularity comes from stored TMDB data.` : 'Catalogue snapshot • popularity from stored TMDB data. Live weekly activity is not measured.';
}

function renderPagination(container, data, go) {
  if(!container)return;container.replaceChildren();
  if(!data.total)return;
  const previous=document.createElement('button');previous.type='button';previous.className='button button-secondary';previous.textContent='Previous page';previous.disabled=data.page<=1;previous.onclick=()=>go(data.page-1);
  const count=document.createElement('span');count.textContent=`Page ${data.page} of ${data.pages || 1} · ${data.total.toLocaleString()} total`;
  const next=document.createElement('button');next.type='button';next.className='button button-secondary';next.textContent='Next page';next.disabled=data.page >= data.pages;next.onclick=()=>go(data.page+1);
  container.append(previous,count,next);
}

/* ── 2. Rich Movie Details Modal & YouTube Trailer ─────────── */

async function openMovieDetails(movieId) {
  try {
    openModal(elements.movieModalShell, elements.movieModalClose);
    state.activeMovie = null;
    elements.movieModalPoster.replaceChildren();
    elements.movieModalGenres.replaceChildren();
    elements.movieModalExternalLinks.replaceChildren();
    elements.movieModalBackdropWrapper.classList.add('hidden');
    elements.movieModalBackdropImg.removeAttribute('src');
    [elements.movieModalYear,elements.movieModalRuntime,elements.movieModalRatingBadge,elements.movieModalDirectorName,elements.modalFactReleaseDate,elements.modalFactBudget,elements.modalFactRevenue,elements.modalFactVotes].forEach(element=>element.textContent='—');
    [elements.movieModalSave,elements.movieModalWatchlistBtn,elements.movieModalAddListBtn].forEach(button=>{button.disabled=true;button.onclick=null;});
    document.getElementById('movie-detail-status').replaceChildren();
    document.getElementById('movie-watch-options').replaceChildren();
    elements.movieModalTitle.textContent = "Loading details...";
    elements.movieModalTagline.textContent = "";
    elements.movieModalOverview.textContent = "Retrieving trailer, cast and similarity metrics...";
    elements.movieModalCastGrid.innerHTML = "";
    elements.movieModalSimilarGrid.innerHTML = "";
    elements.movieModalTrailerWrapper.classList.add("hidden");
    elements.movieModalTrailerFrame.src = "";
    elements.movieModalPlayTrailerBtn.classList.add("hidden");

    const movie = await api(`/movies/${movieId}/details`,{owner:'details'});
    state.activeMovie = movie;

    // Title & Meta
    elements.movieModalTitle.textContent = movie.title;
    elements.movieModalTagline.textContent = movie.tagline ? `“${movie.tagline}”` : "";
    elements.movieModalYear.textContent = movie.release_year || "—";
    elements.movieModalRuntime.textContent = formatRuntime(movie.runtime);
    elements.movieModalRatingBadge.textContent = movie.vote_average > 0 ? `TMDB ${movie.vote_average.toFixed(1)} / 10` : 'TMDB: unrated';
    elements.movieModalOverview.textContent = movie.overview || "No overview available.";

    // Poster
    elements.movieModalPoster.innerHTML = createPosterMarkup(movie);

    // Backdrop
    if (movie.backdrop_url || movie.backdrop_path) {
      const bUrl = safeHTTPS(movie.backdrop_url) || (getPosterUrl(movie.backdrop_path) ? `${TMDB_BACKDROP_BASE}${movie.backdrop_path}` : '');
      elements.movieModalBackdropImg.src = bUrl;
      elements.movieModalBackdropWrapper.classList.remove("hidden");
    } else {
      elements.movieModalBackdropImg.src = "";
      elements.movieModalBackdropWrapper.classList.add("hidden");
    }

    // Trailer handling
    if (movie.trailer && /^[A-Za-z0-9_-]+$/.test(movie.trailer.key)) {
      elements.movieModalPlayTrailerBtn.classList.remove("hidden");
      elements.movieModalPlayTrailerBtn.onclick = () => {
        elements.movieModalBackdropWrapper.classList.add("hidden");
        elements.movieModalTrailerWrapper.classList.remove("hidden");
        elements.movieModalTrailerFrame.src = `https://www.youtube-nocookie.com/embed/${movie.trailer.key}?autoplay=1`;
      };
    } else {
      elements.movieModalPlayTrailerBtn.classList.add("hidden");
    }

    // Director
    if (movie.directors && movie.directors.length > 0) {
      elements.movieModalDirectorName.textContent = movie.directors.map(d => d.name).join(", ");
    } else {
      elements.movieModalDirectorName.textContent = "Unknown";
    }

    // Genres
    let genresArray = Array.isArray(movie.genres) ? movie.genres : (movie.genres || "").split(",");
    elements.movieModalGenres.innerHTML = genresArray
      .map(g => typeof g === "string" ? g.trim() : g)
      .filter(Boolean)
      .map(g => `<span class="genre-chip">${escapeHtml(g)}</span>`)
      .join("");

    // Facts
    elements.modalFactReleaseDate.textContent = movie.release_date || (movie.release_year ? String(movie.release_year) : "—");
    elements.modalFactBudget.textContent = formatCurrency(movie.budget);
    elements.modalFactRevenue.textContent = formatCurrency(movie.revenue);
    elements.modalFactVotes.textContent = movie.vote_count ? movie.vote_count.toLocaleString() : "—";

    // External links
    elements.movieModalExternalLinks.innerHTML = `
      ${safeHTTPS(movie.imdb_url) ? `<a href="${escapeHtml(safeHTTPS(movie.imdb_url))}" target="_blank" rel="noopener noreferrer" class="ext-link-btn">IMDb ↗</a>` : ""}
      ${safeHTTPS(movie.tmdb_url) ? `<a href="${escapeHtml(safeHTTPS(movie.tmdb_url))}" target="_blank" rel="noopener noreferrer" class="ext-link-btn">TMDB ↗</a>` : ""}
    `;

    // Cast Cards
    elements.movieModalCastGrid.innerHTML = "";
    if (movie.cast && movie.cast.length > 0) {
      movie.cast.slice(0, 8).forEach((actor) => {
        const pUrl = safeHTTPS(actor.profile_url) || getPosterUrl(actor.profile_path) || '';
        const castCard = document.createElement("div");
        castCard.className = "cast-card";
        castCard.innerHTML = `
          ${pUrl ? `<img class="cast-photo" src="${escapeHtml(pUrl)}" alt="${escapeHtml(actor.name)}" onerror="this.style.display='none'" />` : `<div class="cast-photo cast-placeholder" aria-hidden="true">${escapeHtml(actor.name?.slice(0,1)||'—')}</div>`}
          <strong class="cast-name">${escapeHtml(actor.name)}</strong>
          <span class="cast-character">${escapeHtml(actor.character)}</span>
        `;
        elements.movieModalCastGrid.appendChild(castCard);
      });
    } else {
      elements.movieModalCastGrid.innerHTML = `<p class="muted-copy">Cast information is not available.</p>`;
    }

    // Similar Movies
    elements.movieModalSimilarGrid.innerHTML = "";
    if (movie.similar_movies && movie.similar_movies.length > 0) {
      movie.similar_movies.forEach((sm) => {
        elements.movieModalSimilarGrid.appendChild(renderMovieCard(sm));
      });
    }

    // Action button state updates
    [elements.movieModalSave,elements.movieModalWatchlistBtn,elements.movieModalAddListBtn].forEach(button=>button.disabled=false);
    document.getElementById('movie-watch-options').append(createWatchArea(movie.id,'details'));
    queueWatchRefresh();
    updateModalActionButtons(movie);
  } catch (err) {
    if(silentError(err))return;
    elements.movieModalTitle.textContent='Details unavailable';
    elements.movieModalOverview.textContent='';
    renderStatus(document.getElementById('movie-detail-status'),err.message,()=>openMovieDetails(movieId));
  }
}

function updateModalActionButtons(movie) {
  const isWatched = state.watchedIds.has(movie.id);
  const isWatchlisted = state.watchlistedIds.has(movie.id);

  if (elements.movieModalSave) {
    elements.movieModalSave.textContent = isWatched ? "✓ In Library" : "+ Save to Watched";
    elements.movieModalSave.disabled = isWatched || state.pendingMutations.has(`movie:${movie.id}`);
    elements.movieModalSave.onclick = () => {
      if (!state.token) {
        closeMovieDetails();
        showAuth();
        showToast("Please sign in to save movies to your library.", "info");
        return;
      }
      saveToLibrary(movie);
    };
  }

  if (elements.movieModalWatchlistBtn) {
    elements.movieModalWatchlistBtn.textContent = isWatched ? 'Already watched' : isWatchlisted ? "Remove from watchlist" : "Save to watchlist";
    elements.movieModalWatchlistBtn.disabled = isWatched || state.pendingMutations.has(`movie:${movie.id}`);
    elements.movieModalWatchlistBtn.onclick = () => {
      if (!state.token) {
        closeMovieDetails();
        showAuth();
        showToast("Please sign in to manage your watchlist.", "info");
        return;
      }
      toggleWatchlist(movie);
    };
  }

  if (elements.movieModalAddListBtn) {
    elements.movieModalAddListBtn.disabled = state.pendingMutations.has(`movie:${movie.id}`);
    elements.movieModalAddListBtn.onclick = () => {
      if (!state.token) {
        closeMovieDetails();
        showAuth();
        showToast("Please sign in to create and add to lists.", "info");
        return;
      }
      openAddToListModal(movie);
    };
  }
}

function closeMovieDetails() {
  closeModal(elements.movieModalShell);
  elements.movieModalTrailerFrame.src = "";
  state.activeMovie = null;
}

/* ── 3. Watchlist Management ───────────────────────────────── */

async function fetchWatchlist() {
  if (!state.token) return;
  try {
    const res = await api(`/watchlist?page=${state.pages.watchlist}&page_size=24`,{owner:'watchlist'});
    if(state.pages.watchlist>Math.max(1,res.pages)) {state.pages.watchlist=Math.max(1,res.pages);return fetchWatchlist();}
    state.watchlist = res.watchlist || [];
    state.watchlist.forEach(item=>state.watchlistedIds.add(item.movie_id));
    if (elements.profileWatchlistCount) elements.profileWatchlistCount.textContent = res.total;
    if (elements.libWatchlistCount) elements.libWatchlistCount.textContent = res.total;
    if (elements.navLibraryBadge) {
      const total = (state.profile?.total_watched || 0) + res.total;
      elements.navLibraryBadge.textContent = total;
      elements.navLibraryBadge.classList.toggle("hidden", total === 0);
    }
    renderWatchlist();
    renderPagination(document.getElementById('watchlist-pagination'),res,page=>{state.pages.watchlist=page;fetchWatchlist();});
    refreshActionLabels();
  } catch (err) {
    if(!silentError(err))renderStatus(elements.watchlistGrid,err.message,fetchWatchlist);
  }
}

function renderWatchlist() {
  if (!elements.watchlistGrid) return;
  elements.watchlistGrid.innerHTML = "";
  if (state.watchlist.length === 0) {
    elements.watchlistGrid.innerHTML = `<p class="muted-copy">Your watchlist is currently empty. Bookmark movies you want to watch next!</p>`;
    return;
  }

  state.watchlist.forEach((item) => {
    const card = renderMovieCard({
      id: item.movie_id,
      title: item.movie_title,
      poster_path: item.poster_path,
      genres: item.genres,
      vote_average: item.vote_average,
    });

    const actionRow = document.createElement("div");
    actionRow.className = "inline-actions";
    actionRow.style.padding = "8px 12px 12px";

    const moveBtn = document.createElement("button");
    moveBtn.type = "button";
    moveBtn.className = "button button-primary";
    moveBtn.style.fontSize = "11px";
    moveBtn.style.padding = "6px 12px";
    moveBtn.textContent = "✓ Mark Watched";
    moveBtn.onclick = (e) => {
      e.stopPropagation();
      moveWatchlistToWatched(item.movie_id);
    };

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "button button-ghost";
    removeBtn.style.fontSize = "11px";
    removeBtn.style.padding = "6px 10px";
    removeBtn.textContent = "✕";
    removeBtn.setAttribute('aria-label',`Remove ${item.movie_title} from watchlist`);
    removeBtn.onclick = (e) => {
      e.stopPropagation();
      removeFromWatchlist(item.movie_id);
    };

    actionRow.appendChild(moveBtn);
    actionRow.appendChild(removeBtn);
    card.appendChild(actionRow);

    elements.watchlistGrid.appendChild(card);
  });
}

async function quickToggleWatchlist(movie) {
  if (!state.token) {
    showToast("Please sign in to add to your watchlist.", "info");
    return;
  }
  toggleWatchlist(movie);
}

async function toggleWatchlist(movie) {
  const session=ownership.session;
  const isAlready = state.watchlistedIds.has(movie.id);
  if(state.pendingMutations.has(`movie:${movie.id}`))return;
  state.pendingMutations.add(`movie:${movie.id}`);
  ownership.cancel('membership');
  setMoviePending(movie.id,true);
  try {
    if (isAlready) {
      await api(`/watchlist/${movie.id}`, { method: "DELETE" });
      state.watchlistedIds.delete(movie.id);
      showToast(`Removed '${movie.title}' from watchlist.`);
    } else {
      await api("/watchlist", {
        method: "POST",
        body: JSON.stringify({
          movie_id: movie.id,
          movie_title: movie.title,
          poster_path: movie.poster_path || "",
          genres: Array.isArray(movie.genres) ? movie.genres.join(", ") : (movie.genres || ""),
          vote_average: movie.vote_average,
        }),
      });
      state.watchlistedIds.add(movie.id);
      showToast(`Added '${movie.title}' to your watchlist!`, "success");
    }
  } catch (err) {
    // If the server state and local state are out of sync, we might get a 404 or 409
    // We swallow it here so the finally block can re-sync the real state.
    if (!err.message.toLowerCase().includes("found") && !err.message.toLowerCase().includes("exist")) {
      showToast(err.message, "error");
    }
  } finally {
    if(session!==ownership.session)return;
    await fetchWatchlist();
    state.pendingMutations.delete(`movie:${movie.id}`);setMoviePending(movie.id,false);refreshActionLabels();
  }
}

async function removeFromWatchlist(movieId) {
  if(state.pendingMutations.has(`movie:${movieId}`))return;
  state.pendingMutations.add(`movie:${movieId}`);setMoviePending(movieId,true);ownership.cancel('membership');
  try {
    await api(`/watchlist/${movieId}`, { method: "DELETE" });
    state.watchlistedIds.delete(movieId);
    showToast("Removed from watchlist.");
    await fetchWatchlist();
    refreshActionLabels();
  } catch (err) {
    showToast(err.message, "error");
  }finally{state.pendingMutations.delete(`movie:${movieId}`);setMoviePending(movieId,false);refreshActionLabels();
  }
}

async function moveWatchlistToWatched(movieId) {
  if(state.pendingMutations.has(`movie:${movieId}`))return;
  state.pendingMutations.add(`movie:${movieId}`);setMoviePending(movieId,true);ownership.cancel('membership');
  try {
    const res = await api(`/watchlist/${movieId}/watched`, { method: "POST" });
    state.watchlistedIds.delete(movieId);state.watchedIds.add(movieId);
    showToast(res.message, "success");
    await Promise.all([fetchWatchlist(),fetchWatched(),fetchProfile()]);refreshActionLabels();
  } catch (err) {
    showToast(err.message, "error");
  }finally{state.pendingMutations.delete(`movie:${movieId}`);setMoviePending(movieId,false);refreshActionLabels();
  }
}

/* ── 4. Watched Library Shelf ──────────────────────────────── */

async function saveToLibrary(movie) {
  const session=ownership.session;
  if(state.pendingMutations.has(`movie:${movie.id}`))return;
  state.pendingMutations.add(`movie:${movie.id}`);ownership.cancel('membership');setMoviePending(movie.id,true);
  try {
    const res = await api("/watched", {
      method: "POST",
      body: JSON.stringify({
        movie_id: movie.id,
        movie_title: movie.title,
        poster_path: movie.poster_path || "",
        genres: Array.isArray(movie.genres) ? movie.genres.join(", ") : (movie.genres || ""),
        vote_average: movie.vote_average,
      }),
    });
    showToast(res.message, "success");
    state.watchedIds.add(movie.id);state.watchlistedIds.delete(movie.id);
    await Promise.all([fetchProfile(),fetchWatched(),fetchWatchlist()]);
  } catch (err) {
    if(!silentError(err))showToast(err.message, "error");
  } finally {
    if(session!==ownership.session)return;
    state.pendingMutations.delete(`movie:${movie.id}`);setMoviePending(movie.id,false);refreshActionLabels();
  }
}

function setMoviePending(id,pending) {
  document.querySelectorAll(`.movie-card[data-movie-id="${id}"] button`).forEach(button=>button.disabled=pending);
  if(state.activeMovie?.id===id)[elements.movieModalSave,elements.movieModalWatchlistBtn,elements.movieModalAddListBtn].forEach(button=>button.disabled=pending);
}

async function hydratePersonal() {
  if(!state.token)return;
  await Promise.allSettled([fetchProfile(),fetchWatched(),fetchWatchlist(),fetchCustomLists()]);
}

async function fetchWatched() {
  if(!state.token)return;
  try {
    const data=await api(`/watched?page=${state.pages.watched}&page_size=24`,{owner:'watched'});
    if(state.pages.watched>Math.max(1,data.pages)) {state.pages.watched=Math.max(1,data.pages);return fetchWatched();}
    state.history=data.history || [];state.history.forEach(item=>state.watchedIds.add(item.movie_id));
    elements.libWatchedCount.textContent=data.total;
    renderLibraryShelf();refreshActionLabels();
    renderPagination(document.getElementById('watched-pagination'),data,page=>{state.pages.watched=page;fetchWatched();});
  }catch(error){if(!silentError(error))renderStatus(elements.libraryList,error.message,fetchWatched);}
}

function renderLibraryShelf() {
  if (!elements.libraryList) return;
  elements.libraryList.innerHTML = "";

  const history = state.history;
  if (history.length === 0) {
    elements.libraryList.innerHTML = `<p class="muted-copy">No movies saved in your watched shelf yet. Use the search bar above to add titles!</p>`;
    return;
  }

  history.forEach((item) => {
    const card = document.createElement("article");
    card.className = "library-item-card";

    const ratingDisplay = item.rating ? `★ ${item.rating.toFixed(1)} / 5` : "Unrated";
    const notesDisplay = item.notes ? `<div class="library-item-notes">“${escapeHtml(item.notes)}”</div>` : "";

    card.innerHTML = `
      <div class="library-item-poster">
        ${createPosterMarkup({ title: item.movie_title, poster_path: item.poster_path })}
      </div>
      <div class="library-item-content">
        <h3>${escapeHtml(item.movie_title)}</h3>
        <div class="library-item-meta">
          <span class="user-rating-stars">${ratingDisplay}</span>
          <span>${escapeHtml(item.genres || "")}</span>
        </div>
        ${notesDisplay}
      </div>
      <div class="library-item-actions">
        <button class="button button-ghost edit-note-btn" type="button">Rate &amp; Note</button>
        <button class="button button-danger delete-item-btn" type="button">Remove</button>
      </div>
    `;

    card.querySelector(".edit-note-btn").addEventListener("click", () => {
      promptRatingAndNote(item);
    });

    card.querySelector(".delete-item-btn").addEventListener("click", async () => {
      try {
        await api(`/watched/entry/${item.id}`, { method: "DELETE" });
        state.watchedIds.delete(item.movie_id);
        showToast(`Removed '${item.movie_title}' from library.`);
        await Promise.all([fetchWatched(),fetchProfile()]);refreshActionLabels();
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    const watch=createWatchArea(item.movie_id);card.append(watch);
    const titleButton=document.createElement('button');titleButton.type='button';titleButton.className='title-details-button';titleButton.textContent=item.movie_title;titleButton.onclick=()=>openMovieDetails(item.movie_id);card.querySelector('h3').replaceChildren(titleButton);
    elements.libraryList.appendChild(card);queueWatchRefresh();
  });
}

function promptRatingAndNote(item) {
  const shell=document.getElementById('rating-modal-shell');
  const form=document.getElementById('rating-form');
  const rating=document.getElementById('edit-rating');const notes=document.getElementById('edit-notes');
  document.getElementById('rating-movie-title').textContent=`Your thoughts on ${item.movie_title}`;
  rating.value=item.rating ?? '';notes.value=item.notes || '';
  document.getElementById('rating-error').textContent='';
  document.getElementById('clear-rating').onclick=()=>{rating.value='';};
  document.getElementById('clear-notes').onclick=()=>{notes.value='';};
  form.onsubmit=async event=>{
    event.preventDefault();
    await busy(form.querySelector('[type=submit]'),async()=>{
      try {
        await api(`/watched/${item.id}`,{method:'PATCH',body:JSON.stringify({rating:rating.value===''?null:Number(rating.value),notes:notes.value.trim()||null})});
        await Promise.all([fetchWatched(),fetchProfile()]);closeModal(shell);showToast('Rating and notes saved.','success');
      }catch(error){if(!silentError(error))document.getElementById('rating-error').textContent=error.message;}
    });
  };
  openModal(shell,rating);
}

/* ── 5. Curated Lists & Social Sharing ─────────────────────── */

async function fetchCustomLists() {
  if (!state.token) return;
  try {
    const data = await api(`/lists/my?page=${state.pages.lists}&page_size=24`,{owner:'lists'});
    if(state.pages.lists>Math.max(1,data.pages)) {state.pages.lists=Math.max(1,data.pages);return fetchCustomLists();}
    state.customLists = data.lists || [];
    state.listData=data;
    if (elements.libListsCount) elements.libListsCount.textContent = data.total;
    renderCustomLists();
    renderPagination(document.getElementById('lists-pagination'),data,page=>{state.pages.lists=page;fetchCustomLists();});
  } catch (err) {
    if(!silentError(err))renderStatus(elements.customListsContainer,err.message,fetchCustomLists);
  }
}

function renderCustomLists() {
  if (!elements.customListsContainer) return;
  elements.customListsContainer.innerHTML = "";

  if (state.customLists.length === 0) {
    elements.customListsContainer.innerHTML = `<p class="muted-copy">No lists yet. Choose “Create a curated list” to start a private or shareable collection.</p>`;
    return;
  }

  state.customLists.forEach((cl) => {
    const card = document.createElement("div");
    card.className = "custom-list-card";

    const thumbs = (cl.items || [])
      .slice(0, 4)
      .map((item) => {
        const posterUrl = getPosterUrl(item.poster_path);
        return posterUrl
          ? `<img class="custom-list-thumb" src="${posterUrl}" alt="${escapeHtml(item.movie_title)}" onerror="this.style.display='none'" />`
          : "";
      })
      .join("");

    card.innerHTML = `
      <h3>${escapeHtml(cl.title)}</h3>
      <p class="custom-list-desc">${escapeHtml(cl.description || "No description")}</p>
      <div class="custom-list-meta">
        <span>${cl.item_count} movie${cl.item_count === 1 ? "" : "s"}</span>
        <span>${cl.is_public ? "Public" : "Private · only you"}</span>
      </div>
      <div class="custom-list-items-preview">${thumbs}</div>
      <div class="custom-list-actions">
        <button class="button button-secondary manage-list-btn" type="button">Open &amp; edit list</button>
        ${cl.is_public ? '<button class="button button-secondary copy-link-btn" type="button">Copy public link</button>' : ''}
        <button class="button button-danger delete-list-btn" type="button">Delete</button>
      </div>
    `;

    card.querySelector('.manage-list-btn').onclick=()=>navigateOwnerList(cl.id);
    card.querySelector(".copy-link-btn")?.addEventListener("click", () => {
      const shareUrl = `${window.location.origin}/#list/${cl.share_slug}`;
      copyLink(shareUrl);
    });

    card.querySelector(".delete-list-btn").addEventListener("click", async () => {
      if (!confirm(`Delete list '${cl.title}'?`)) return;
      try {
        await api(`/lists/${cl.id}`, { method: "DELETE" });
        showToast("List deleted.");
        await fetchCustomLists();
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    elements.customListsContainer.appendChild(card);
  });
}

function openAddToListModal(movie) {
  state.activeMovieForList = movie;
  openModal(elements.addToListModalShell, elements.addToListModalClose);
  elements.addToListMovieTitle.textContent = `Choose a list to add "${movie.title}" to:`;
  elements.pickListContainer.innerHTML = "";
  renderPagination(document.getElementById('pick-list-pagination'),state.listData || {total:0},async page=>{state.pages.lists=page;await fetchCustomLists();openAddToListModal(movie);});

  if (state.customLists.length === 0) {
    elements.pickListContainer.innerHTML = `<p class="muted-copy">You haven't created any custom lists yet.</p>`;
    return;
  }

  state.customLists.forEach((cl) => {
    const btn = document.createElement("button");
    btn.className = "button button-secondary";
    btn.style.width = "100%";
    btn.style.marginBottom = "8px";
    btn.textContent = `+ Add to "${cl.title}"`;
    btn.addEventListener("click", async () => {
      btn.disabled=true;
      try {
        await api(`/lists/${cl.id}/items`, {
          method: "POST",
          body: JSON.stringify({
            movie_id: movie.id,
            movie_title: movie.title,
            poster_path: movie.poster_path || "",
            genres: Array.isArray(movie.genres) ? movie.genres.join(", ") : (movie.genres || ""),
            vote_average: movie.vote_average,
          }),
        });
        showToast(`Added to "${cl.title}"!`, "success");
        closeModal(elements.addToListModalShell);
        fetchCustomLists();
      } catch (err) {
        showToast(err.message, "error");
      }finally{btn.disabled=false;
      }
    });
    elements.pickListContainer.appendChild(btn);
  });
}

async function busy(button, task) {
  if(button?.disabled)return;
  if(button){button.disabled=true;button.setAttribute('aria-busy','true');}
  try{return await task();}finally{if(button){button.disabled=false;button.removeAttribute('aria-busy');}}
}

async function copyLink(link) {
  try{await navigator.clipboard.writeText(link);showToast('Link copied.','success');}
  catch{showToast('Copy failed. You can copy the link from the address bar.','error');}
}

function navigateOwnerList(id) {
  const hash=`#my-list/${id}`;if(location.hash!==hash)history.pushState(null,'',hash);
  state.pages.owner=1;loadOwnerList(id);
}

function canReloadOwnerList(id) {
  return state.currentPage==='owner-list' && routeFromHash(location.hash).id===Number(id);
}

async function loadOwnerList(id) {
  if(!state.token){showAuth(false);return;}
  switchPage('owner-list',false);
  const grid=document.getElementById('owner-list-grid');renderLoading(grid);
  try{
    const data=await api(`/lists/${id}?page=${state.pages.owner}&page_size=24`,{owner:'owner-list'});
    if(!canReloadOwnerList(id)) return;
    if(state.pages.owner>Math.max(1,data.pages)) {state.pages.owner=Math.max(1,data.pages);return loadOwnerList(id);}
    document.getElementById('owner-list-title').textContent=data.title;
    const form=document.getElementById('owner-list-form');
    form.elements.title.value=data.title;form.elements.description.value=data.description||'';form.elements.is_public.checked=Boolean(data.is_public);
    form.onsubmit=event=>{
      event.preventDefault();busy(form.querySelector('[type=submit]'),async()=>{
        try{const title=form.elements.title.value.trim();if(!title)throw new Error('Enter a list title.');
          await api(`/lists/${id}`,{method:'PATCH',body:JSON.stringify({title,description:form.elements.description.value.trim(),is_public:form.elements.is_public.checked})});
          if(canReloadOwnerList(id)) await loadOwnerList(id);await fetchCustomLists();showToast('List updated.','success');
        }catch(error){if(!silentError(error))document.getElementById('owner-list-error').textContent=error.message;}
      });
    };
    const share=document.getElementById('owner-list-share');share.hidden=!data.is_public;share.onclick=()=>copyLink(`${location.origin}/#list/${data.share_slug}`);
    document.getElementById('owner-list-error').textContent='';grid.replaceChildren();
    (data.items||[]).forEach(item=>{
      const card=renderMovieCard({id:item.movie_id,title:item.movie_title,poster_path:item.poster_path,genres:item.genres,vote_average:item.vote_average});
      const remove=document.createElement('button');remove.type='button';remove.className='button button-danger list-remove';remove.textContent='Remove from list';remove.setAttribute('aria-label',`Remove ${item.movie_title} from ${data.title}`);
      remove.onclick=()=>busy(remove,async()=>{try{await api(`/lists/${id}/items/${item.movie_id}`,{method:'DELETE'});if(canReloadOwnerList(id))await loadOwnerList(id);await fetchCustomLists();}catch(error){showToast(error.message,'error');}});card.append(remove);grid.append(card);
    });
    if(!data.items?.length)renderStatus(grid,'This list is empty. Add a film from its details.');
    renderPagination(document.getElementById('owner-pagination'),data,page=>{state.pages.owner=page;loadOwnerList(id);});
  }catch(error){if(!silentError(error))renderStatus(grid,error.message,()=>loadOwnerList(id));}
}

async function loadSharedList(shareSlug) {
  switchPage('shared-list',false);
  renderLoading(elements.sharedListGrid);
  try {
    const data = await api(`/lists/share/${shareSlug}?page=${state.pages.shared}&page_size=24`,{owner:'shared'});
    elements.sharedListTitle.textContent = data.title;
    elements.sharedListCreator.textContent = `Curated by @${data.creator_username}`;
    elements.sharedListDescription.textContent = data.description || "";
    elements.sharedListGrid.innerHTML = "";

    data.items.forEach((item) => {
      elements.sharedListGrid.appendChild(
        renderMovieCard({
          id: item.movie_id,
          title: item.movie_title,
          poster_path: item.poster_path,
          genres: item.genres,
          vote_average: item.vote_average,
        })
      );
    });
    renderPagination(document.getElementById('shared-pagination'),data,page=>{state.pages.shared=page;loadSharedList(shareSlug);});

    elements.copySharedListLink.onclick = () => {
      copyLink(window.location.href);
    };
  } catch (err) {
    if(!silentError(err))renderStatus(elements.sharedListGrid,err.message,()=>loadSharedList(shareSlug));
  }
}

/* ── 6. Recommendations & Labs ─────────────────────────────── */

async function fetchPersonalized() {
  if (!state.token) return;
  try {
    renderLoading(elements.personalizedGrid);
    const excludeWatched = elements.excludeWatchedToggle?.checked ?? true;
    const res = await api(`/recommend/me?top_n=12&exclude_watched=${excludeWatched}`,{owner:'personal'});
    elements.personalReason.textContent = res.reason || "Curated for you.";
    elements.personalizedGrid.innerHTML = "";
    renderMovies(elements.personalizedGrid,res.movies);
  } catch (err) {
    if(silentError(err))return;
    console.error("Failed to fetch personalized recs:", err);
    renderStatus(elements.personalizedGrid, "Your recommendations could not be loaded.", fetchPersonalized);
    showToast(err.message || "Could not load recommendations.", "error");
  }
}

async function loadGenrePage() {
  const topN = elements.genreTopN ? parseInt(elements.genreTopN.value, 10) : 12;
  const minRating = elements.genreMinRating ? parseFloat(elements.genreMinRating.value) : 6.5;
  const genres = Array.from(state.browseGenres);
  if (genres.length === 0) {
    elements.genreResults.innerHTML = `<p class="muted-copy">Select at least one genre in your profile or above to browse picks.</p>`;
    return;
  }

  try {
    renderLoading(elements.genreResults);
    const res = await api("/recommend/genre", {
      method: "POST",
      owner:'genre-recommendations',
      body: JSON.stringify({
        genres,
        top_n: topN,
        min_rating: minRating,
      }),
    });
    elements.genreResults.innerHTML = "";
    renderMovies(elements.genreResults,res.movies,'No films meet your selected genres and rating threshold. Try a lower threshold.');
  } catch (err) {
    if(silentError(err))return;
    console.error("Failed to load genre recs:", err);
    renderStatus(elements.genreResults, "Genre recommendations could not be loaded.", loadGenrePage);
    showToast(err.message || "Could not load genre recommendations.", "error");
  }
}

/* ── 7. Search Overlay ─────────────────────────────────────── */

function openSearchModal(defaultQuery = "") {
  openModal(elements.searchModalShell, elements.mainSearchInput);
  if (defaultQuery) {
    elements.mainSearchInput.value = defaultQuery;
    executeMainSearch(defaultQuery);
  } else {
    elements.mainSearchInput.focus();
  }
}

function closeSearchModal() {
  closeModal(elements.searchModalShell);
}

async function executeMainSearch(query) {
  const q = query.trim();
  if (!q) return;

  elements.mainSearchSubmit.textContent = "Searching...";
  renderLoading(elements.mainSearchGrid);
  elements.searchFeedbackBanner.classList.add('hidden');
  try {
    const res = await api(`/search?q=${encodeURIComponent(q)}&limit=18`,{owner:'search'});
    elements.mainSearchSubmit.textContent = "Search";
    elements.mainSearchClear.classList.remove("hidden");

    if (res.match_type === "theme_genre_match" || res.exact_match === false) {
      elements.searchFeedbackBanner.classList.remove("hidden");
      elements.searchFeedbackBanner.textContent = res.message;
    } else {
      elements.searchFeedbackBanner.classList.add("hidden");
    }

    elements.mainSearchGrid.innerHTML = "";
    if (!res.movies || res.movies.length === 0) {
      elements.mainSearchGrid.innerHTML = `<p class="muted-copy">No results found for "${escapeHtml(q)}".</p>`;
      return;
    }

    res.movies.forEach((m) => {
      elements.mainSearchGrid.appendChild(renderMovieCard(m));
    });
  } catch (err) {
    if(silentError(err))return;
    elements.mainSearchSubmit.textContent = "Search";
    renderStatus(elements.mainSearchGrid,err.message,()=>executeMainSearch(q));
  }
}

/* ── 8. Data Export ────────────────────────────────────────── */

function exportData(format) {
  if (!state.token) {
    showToast("Please sign in to export your data.", "error");
    return;
  }
  const url = `/library/export?format=${format}`;
  fetch(url, {
    headers: { Authorization: `Bearer ${state.token}` },
  })
    .then(async (res) => {
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: "Export failed." }));
        throw new Error(error.detail || "Export failed.");
      }
      return res.blob();
    })
    .then((blob) => {
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = `cinematch_${state.username || "user"}_export.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
      showToast(`Exported ${format.toUpperCase()} successfully!`, "success");
    })
    .catch((err) => showToast(err.message || "Export failed.", "error"));
}

/* ── Global Event Bindings & Init ──────────────────────────── */

function initEventHandlers() {
  const bind = (id, event, handler) => document.getElementById(id)?.addEventListener(event, handler);
  elements.brandLink.onclick = event => {event.preventDefault();switchPage('explore');};
  document.querySelectorAll('[data-page]').forEach(link => link.onclick=()=>switchPage(link.dataset.page));
  bind('bottom-search','click',()=>openSearchModal());
  bind('spotlight-search','click',()=>openSearchModal());
  bind('bottom-more','click',openMobileNav);
  elements.navToggle.setAttribute('aria-expanded','false'); elements.navToggle.setAttribute('aria-controls','app-nav');
  elements.navToggle.onclick=openMobileNav;elements.navCloseButton.onclick=closeMobileNav;elements.navOverlay.onclick=closeMobileNav;
  window.addEventListener('resize',()=>{if(innerWidth>860)closeMobileNav();});
  elements.navSearchButton.onclick=()=>openSearchModal();elements.mobileSearchToggle.onclick=()=>openSearchModal();
  elements.searchModalClose.onclick=closeSearchModal;
  elements.mainSearchForm.onsubmit=event=>{event.preventDefault();executeMainSearch(elements.mainSearchInput.value);};
  elements.mainSearchClear.onclick=()=>{ownership.cancel('search');elements.mainSearchInput.value='';elements.mainSearchGrid.replaceChildren();elements.mainSearchClear.classList.add('hidden');elements.searchFeedbackBanner.classList.add('hidden');elements.mainSearchSubmit.textContent='Search';elements.mainSearchInput.focus();};
  document.querySelectorAll('.quick-tag').forEach(tag=>tag.onclick=()=>{elements.mainSearchInput.value=tag.dataset.searchTerm;executeMainSearch(tag.dataset.searchTerm);});
  elements.navAuthButton.onclick=()=>showAuth();elements.navDrawerAuthButton.onclick=()=>showAuth();
  const logout=()=>{clearAuth();showToast('Signed out on this browser.');};
  elements.navLogoutButton.onclick=logout;elements.navDrawerLogoutButton.onclick=logout;
  document.addEventListener('keydown',handleModalKeyboard);
  document.querySelectorAll('.auth-tab').forEach(tab=>tab.onclick=()=>{
    document.querySelectorAll('.auth-tab').forEach(item=>{item.classList.toggle('active',item===tab);item.setAttribute('aria-pressed',String(item===tab));});
    elements.loginPanel.classList.toggle('active',tab.dataset.authTab==='login');elements.signupPanel.classList.toggle('active',tab.dataset.authTab==='signup');
  });
  const authSubmit=async(event,signup)=>{
    event.preventDefault();const form=signup?elements.signupForm:elements.loginForm;
    await busy(form.querySelector('[type=submit]'),async()=>{
      elements.authAlert.classList.add('hidden');
      try {
        const body={username:form.elements.username.value.trim(),password:form.elements.password.value};
        if(signup){body.email=form.elements.email.value.trim()||undefined;body.genres=[...state.signupGenres];if(body.genres.length<2)throw new Error('Select at least two genres.');}
        const result=await api(signup?'/auth/signup':'/auth/login',{method:'POST',body:JSON.stringify(body),owner:'auth-submit'});
        setAuth(result.access_token,result.user_id,result.username,result.genres);form.reset();switchPage('for-you');
      }catch(error){if(!silentError(error)){elements.authAlert.textContent=error.message;elements.authAlert.classList.remove('hidden');}}
    });
  };
  elements.loginForm.onsubmit=event=>authSubmit(event,false);elements.signupForm.onsubmit=event=>authSubmit(event,true);
  elements.passwordForm.onsubmit=event=>{event.preventDefault();busy(elements.passwordForm.querySelector('[type=submit]'),async()=>{
    try{await api('/auth/password',{method:'PUT',body:JSON.stringify({current_password:elements.passwordForm.elements.currentPassword.value,new_password:elements.passwordForm.elements.newPassword.value})});elements.passwordForm.reset();clearAuth();showAuth();showToast('Password changed. Sign in again on each device.','success');}catch(error){if(!silentError(error))showToast(error.message,'error');}
  });};
  bind('revoke-sessions','click',event=>busy(event.currentTarget,async()=>{try{await api('/auth/revoke-sessions',{method:'POST'});clearAuth();showAuth();showToast('All sessions revoked. Sign in again.','success');}catch(error){showToast(error.message,'error');}}));
  document.querySelectorAll('#explore-decade-filters .filter-pill').forEach(pill=>pill.onclick=()=>{
    document.querySelectorAll('#explore-decade-filters .filter-pill').forEach(item=>{item.classList.toggle('active',item===pill);item.setAttribute('aria-pressed',String(item===pill));});state.exploreDecade=pill.dataset.decade;state.pages.archive=1;renderDecadeSection();
  });
  elements.exploreMinRating.onchange=event=>{state.exploreMinRating=Number(event.target.value);state.pages.archive=1;renderDecadeSection();};
  elements.exploreSortBy.onchange=event=>{state.exploreSortBy=event.target.value;state.pages.archive=1;renderDecadeSection();};
  bind('archive-genre','change',()=>{state.pages.archive=1;renderDecadeSection();});
  bind('watch-country','change',event=>{state.country=event.target.value;localStorage.setItem('cm_country',state.country);refreshWatchOptions();});
  elements.movieModalClose.onclick=closeMovieDetails;
  document.querySelectorAll('.modal-shell').forEach(shell=>shell.onclick=event=>{if(event.target===shell&&getOpenModal()===shell)closeModal(shell);});
  elements.openCreateListModal.onclick=()=>openModal(elements.createListModalShell,elements.createListTitle);
  elements.createListModalClose.onclick=()=>closeModal(elements.createListModalShell);
  elements.addToListModalClose.onclick=()=>closeModal(elements.addToListModalShell);
  bind('rating-modal-close','click',()=>closeModal(document.getElementById('rating-modal-shell')));
  elements.createListForm.onsubmit=event=>{event.preventDefault();busy(elements.createListForm.querySelector('[type=submit]'),async()=>{
    try{const title=elements.createListTitle.value.trim();if(!title)throw new Error('Enter a list title.');await api('/lists',{method:'POST',body:JSON.stringify({title,description:elements.createListDescription.value.trim(),is_public:elements.createListIsPublic.checked})});elements.createListForm.reset();closeModal(elements.createListModalShell);await fetchCustomLists();showToast('List created.','success');}catch(error){document.getElementById('create-list-error').textContent=error.message;}
  });};
  document.querySelectorAll('.library-tabs .lib-tab').forEach(tab=>tab.onclick=()=>{
    document.querySelectorAll('.lib-tab').forEach(item=>{item.classList.toggle('active',item===tab);item.setAttribute('aria-pressed',String(item===tab));});
    document.querySelectorAll('.lib-panel').forEach(panel=>panel.classList.toggle('active',panel.id===`lib-panel-${tab.dataset.libTab}`));refreshWatchOptions();
  });
  elements.exportCsvBtn.onclick=()=>exportData('csv');elements.exportJsonBtn.onclick=()=>exportData('json');
  bind('refresh-personalized','click',event=>busy(event.currentTarget,fetchPersonalized));elements.excludeWatchedToggle.onchange=fetchPersonalized;
  bind('save-genre-preferences','click',event=>busy(event.currentTarget,async()=>{
    try{await api('/genres/preferences',{method:'PUT',body:JSON.stringify({genres:[...state.genres]})});await fetchProfile();showToast('Preferences saved.','success');}catch(error){showToast(error.message,'error');}
  }));
  elements.runGenreRecommend.onclick=event=>busy(event.currentTarget,loadGenrePage);
  setupCombobox('history-search-input','history-search-results',addHistorySeed);
  setupCombobox('hybrid-search-input','hybrid-search-results',movie=>{if(!state.hybridSeeds.some(item=>item.id===movie.id))state.hybridSeeds.push(movie);renderHybridSummary();});
  setupCombobox('library-search-input','library-search-results',saveToLibrary);
  bind('run-history-recommend','click',event=>busy(event.currentTarget,async()=>{
    if(!state.historySeeds.length){renderStatus(elements.historyResults,'Add at least one seed movie.');return;}
    await runRecommendations('/recommend/history',{movie_ids:state.historySeeds.map(movie=>movie.id),top_n:12},elements.historyResults,'history-recommendations');
  }));
  bind('clear-history-seeds','click',()=>{ownership.cancel('history-recommendations');state.historySeeds=[];renderHistorySeeds();elements.historyResults.replaceChildren();});
  bind('hybrid-source','change',event=>{state.hybridSource=event.target.value;renderHybridSummary();});
  bind('weight-content','input',renderHybridSummary);
  bind('run-hybrid-recommend','click',event=>busy(event.currentTarget,async()=>{
    try {const ids=hybridMovieIds();const payload=blendInputs(ids,[...state.hybridGenres],Number(document.getElementById('weight-content').value));await runRecommendations('/recommend/hybrid',{...payload,top_n:12},elements.hybridResults,'hybrid-recommendations');}
    catch(error){renderStatus(elements.hybridResults,error.message);}
  }));
  elements.backToExploreBtn.onclick=()=>switchPage('explore');bind('owner-list-back','click',()=>switchPage('library'));
  const routed=()=>routeCurrentURL();window.addEventListener('popstate',routed);window.addEventListener('hashchange',routed);
}

function setupCombobox(inputId, resultsId, select) {
  const input=document.getElementById(inputId),list=document.getElementById(resultsId);if(!input||!list)return;
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls',resultsId);input.setAttribute('aria-expanded','false');list.setAttribute('role','listbox');
  let results=[],active=-1,generation=0;
  const close=()=>{list.classList.add('hidden');input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;};
  const choose=movie=>{select(movie);input.value='';generation++;ownership.cancel(inputId);close();};
  const highlight=()=>{[...list.children].forEach((row,index)=>row.setAttribute('aria-selected',String(index===active)));if(active>=0){input.setAttribute('aria-activedescendant',`${resultsId}-${active}`);list.children[active]?.scrollIntoView({block:'nearest'});}};
  const search=debounce(async(query,version)=>{
    if(version!==generation)return;
    if(query.length<2){close();return;}
    try{
      const data=await api(`/search?q=${encodeURIComponent(query)}&limit=5`,{owner:inputId});if(version!==generation||input.value.trim()!==query)return;
      results=data.movies||[];active=-1;list.replaceChildren();
      results.forEach((movie,index)=>{const row=document.createElement('div');row.id=`${resultsId}-${index}`;row.className='search-result-row';row.setAttribute('role','option');row.setAttribute('aria-selected','false');row.textContent=`${movie.title} (${movie.release_year||'year unknown'})`;row.onmousedown=event=>event.preventDefault();row.onclick=()=>choose(movie);list.append(row);});
      input.setAttribute('aria-expanded',String(results.length>0));list.classList.toggle('hidden',!results.length);document.getElementById('suggestion-announcer').textContent=`${results.length} suggestions. Use arrow keys, then Enter to select.`;
    }catch(error){if(!silentError(error)){close();document.getElementById('suggestion-announcer').textContent=error.message;showToast(error.message,'error');}}
  },250);
  input.oninput=()=>{generation++;ownership.cancel(inputId);close();search(input.value.trim(),generation);};
  input.onkeydown=event=>{
    if(event.key==='Escape'&&!list.classList.contains('hidden')){event.preventDefault();event.stopPropagation();generation++;ownership.cancel(inputId);close();}
    else if((event.key==='ArrowDown'||event.key==='ArrowUp')&&results.length&&!list.classList.contains('hidden')){event.preventDefault();active=event.key==='ArrowDown'?(active+1)%results.length:(active-1+results.length)%results.length;highlight();}
    else if(event.key==='Enter'&&active>=0&&!list.classList.contains('hidden')){event.preventDefault();choose(results[active]);}
  };
  input.onblur=()=>{generation++;ownership.cancel(inputId);close();};
}

async function runRecommendations(path,body,container,key) {
  renderLoading(container);
  try {const data=await api(path,{method:'POST',body:JSON.stringify(body),owner:key});renderMovies(container,data.movies);}
  catch(error){if(!silentError(error))renderStatus(container,error.message,()=>runRecommendations(path,body,container,key));}
}

function hybridMovieIds() {
  return state.hybridSource==='saved' ? (state.profile?.history||[]).map(item=>item.movie_id) : state.hybridSeeds.map(item=>item.id);
}

function renderHybridSummary() {
  const source=document.getElementById('hybrid-source');if(!source)return;
  source.value=state.hybridSource;source.querySelector('[value=saved]').disabled=!state.token;
  document.getElementById('hybrid-manual-inputs').classList.toggle('hidden',state.hybridSource!=='manual');
  const seeds=document.getElementById('hybrid-seeds');seeds.replaceChildren();
  const movies=state.hybridSource==='saved'?(state.profile?.history||[]).map(item=>({id:item.movie_id,title:item.movie_title})):state.hybridSeeds;
  movies.forEach(movie=>{const item=document.createElement(state.hybridSource==='manual'?'button':'span');item.className='genre-chip selected';item.textContent=movie.title;if(item.tagName==='BUTTON'){item.type='button';item.setAttribute('aria-label',`Remove ${movie.title} from blend`);item.onclick=()=>{state.hybridSeeds=state.hybridSeeds.filter(seed=>seed.id!==movie.id);renderHybridSummary();};}seeds.append(item);});
  const requested=Number(document.getElementById('weight-content').value);
  const historyWeight=!movies.length?0:!state.hybridGenres.size?1:requested;
  document.getElementById('weight-content-value').textContent=`${Math.round(historyWeight*100)}% movies`;
  document.getElementById('weight-genre-value').textContent=`${Math.round((1-historyWeight)*100)}% genres`;
  document.getElementById('hybrid-summary').textContent=`${state.hybridSource==='saved'?'Recent saved history':'Manual seeds'}: ${movies.length} films. ${state.hybridGenres.size} selected genres. ${movies.length&&state.hybridGenres.size?'Use the slider to balance both signals.':'A single available signal receives the full weight.'}`;
}

function routeCurrentURL() {
  state.modalStack.slice().reverse().forEach(entry=>closeModal(entry.shell));
  const route=routeFromHash(location.hash);
  if(route.page==='shared-list'){state.pages.shared=1;loadSharedList(route.slug);}
  else if(route.page==='owner-list'){state.pages.owner=1;loadOwnerList(route.id);}
  else switchPage(route.page,false);
}

function addHistorySeed(movie) {
  if (state.historySeeds.some(s => s.id === movie.id)) return;
  if(state.historySeeds.length>=200){showToast('You can use up to 200 films in one recommendation.','error');return;}
  state.historySeeds.push(movie);
  renderHistorySeeds();
}

function renderHistorySeeds() {
  if (!elements.historySeeds) return;
  elements.historySeeds.innerHTML = "";
  state.historySeeds.forEach((s) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "genre-chip selected";
    chip.textContent = `${s.title} ✕`;
    chip.setAttribute("aria-label", `Remove ${s.title} from recommendation seeds`);
    chip.addEventListener("click", () => {
      state.historySeeds = state.historySeeds.filter(item => item.id !== s.id);
      renderHistorySeeds();
    });
    elements.historySeeds.appendChild(chip);
  });
}

/* ── App Initialization ────────────────────────────────────── */

async function initApp() {
  initEventHandlers();updateNavAuthUI();syncModalIsolation();
  // Independent startup requests keep discovery usable if one subsystem is unavailable.
  const loadHealth=async()=>{try{const health=await api('/health',{owner:'health'});if(health.catalog){const catalog=health.catalog;document.getElementById('stat-total-movies').textContent=catalog.total_movies.toLocaleString();document.getElementById('stat-total-genres').textContent=catalog.total_genres;document.getElementById('stat-average-rating').textContent=Number(catalog.average_rating||0).toFixed(1);document.getElementById('stat-year-range').textContent=(catalog.year_range||[]).join('–');}}catch(error){if(!silentError(error))document.getElementById('catalog-freshness').textContent='Catalogue status temporarily unavailable. Discovery can still be retried below.';}};
  const loadGenres=async()=>{try{const data=await api('/genres',{owner:'genres'});state.allGenres=data.genres||[];renderProfileGenreChips();const select=document.getElementById('archive-genre');select.innerHTML='<option value="">Every genre</option>';state.allGenres.forEach(genre=>{const option=document.createElement('option');option.value=genre;option.textContent=genre;select.append(option);});document.getElementById('genre-startup-status').replaceChildren();}catch(error){if(!silentError(error))renderStatus(document.getElementById('genre-startup-status'),error.message,loadGenres);}};
  const loadCountries=async()=>{try{const data=await api('/watch/countries',{owner:'countries'});const select=document.getElementById('watch-country');select.replaceChildren();data.countries.forEach(country=>{const option=document.createElement('option');option.value=country.code;option.textContent=country.name;select.append(option);});if(!data.countries.some(country=>country.code===state.country))state.country=data.default_country||'IN';select.value=state.country;refreshWatchOptions();document.getElementById('country-status').replaceChildren();}catch(error){if(!silentError(error))renderStatus(document.getElementById('country-status'),'Region list unavailable. India watch options can still be checked.',loadCountries);}};
  const loadProvenance=async()=>{try{state.catalogMetadata=await api('/catalog/metadata',{owner:'catalog-metadata'});renderCatalogProvenance();}catch(error){if(!silentError(error))document.getElementById('catalog-freshness').textContent='Catalogue snapshot date unavailable. Popularity comes from stored TMDB data.';}};
  if(state.token){state.hybridSource='saved';hydratePersonal();}
  renderHybridSummary();routeCurrentURL();
  await Promise.allSettled([loadHealth(),loadGenres(),loadCountries(),loadProvenance()]);
}

// Start app on DOM ready
document.addEventListener("DOMContentLoaded", initApp);
