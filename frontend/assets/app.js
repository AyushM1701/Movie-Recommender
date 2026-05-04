const TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500";

const state = {
  token: localStorage.getItem("cm_token"),
  userId: localStorage.getItem("cm_user_id"),
  username: localStorage.getItem("cm_username"),
  genres: new Set(JSON.parse(localStorage.getItem("cm_genres") || "[]")),
  catalog: null,
  allGenres: [],
  profile: null,
  personalized: [],
  historySeeds: [],
  activeMovie: null,
};

const elements = {
  authView: document.getElementById("auth-view"),
  appView: document.getElementById("app-view"),
  navAuthButton: document.getElementById("nav-auth-button"),
  navLogoutButton: document.getElementById("nav-logout-button"),
  navMenu: document.getElementById("app-nav"),
  authAlert: document.getElementById("auth-alert"),
  loginPanel: document.getElementById("login-panel"),
  signupPanel: document.getElementById("signup-panel"),
  loginForm: document.getElementById("login-form"),
  signupForm: document.getElementById("signup-form"),
  signupGenreGrid: document.getElementById("signup-genre-grid"),
  signupGenreCount: document.getElementById("signup-genre-count"),
  profileGenreGrid: document.getElementById("profile-genre-grid"),
  personalizedGrid: document.getElementById("personalized-grid"),
  personalReason: document.getElementById("personal-reason"),
  genreResults: document.getElementById("genre-grid-results"),
  historyResults: document.getElementById("history-grid-results"),
  hybridResults: document.getElementById("hybrid-grid-results"),
  historySeeds: document.getElementById("history-seeds"),
  libraryList: document.getElementById("library-list"),
  libraryBadge: document.getElementById("library-badge"),
  toastStack: document.getElementById("toast-stack"),
  movieModalShell: document.getElementById("movie-modal-shell"),
  movieModalClose: document.getElementById("movie-modal-close"),
  movieModalPoster: document.getElementById("movie-modal-poster"),
  movieModalTitle: document.getElementById("movie-modal-title"),
  movieModalMeta: document.getElementById("movie-modal-meta"),
  movieModalOverview: document.getElementById("movie-modal-overview"),
  movieModalGenres: document.getElementById("movie-modal-genres"),
  movieModalSave: document.getElementById("movie-modal-save"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function createPosterMarkup(movie, size = "card") {
  const title = escapeHtml(movie.title || "Unknown title");
  if (movie.poster_path) {
    return `
      <img
        src="${TMDB_IMAGE_BASE}${movie.poster_path}"
        alt="${title}"
        loading="lazy"
      />
    `;
  }
  const initials = title
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] || "")
    .join("")
    .toUpperCase();
  return `<div class="movie-poster-fallback ${size}">${initials || "CM"}</div>`;
}

function scoreLabel(movie) {
  if (typeof movie.hybrid_score === "number") {
    return `Hybrid ${movie.hybrid_score.toFixed(3)}`;
  }
  if (typeof movie.similarity_score === "number") {
    return `${Math.round(movie.similarity_score * 100)}% match`;
  }
  if (typeof movie.bayesian_score === "number") {
    return `Score ${movie.bayesian_score.toFixed(2)}`;
  }
  return "";
}

function setStoredSession(payload) {
  state.token = payload.access_token;
  state.userId = String(payload.user_id);
  state.username = payload.username;
  state.genres = new Set(payload.genres || []);
  localStorage.setItem("cm_token", payload.access_token);
  localStorage.setItem("cm_user_id", String(payload.user_id));
  localStorage.setItem("cm_username", payload.username);
  localStorage.setItem("cm_genres", JSON.stringify(payload.genres || []));
}

function clearSession() {
  state.token = null;
  state.userId = null;
  state.username = null;
  state.profile = null;
  state.personalized = [];
  state.historySeeds = [];
  state.genres = new Set();
  localStorage.removeItem("cm_token");
  localStorage.removeItem("cm_user_id");
  localStorage.removeItem("cm_username");
  localStorage.removeItem("cm_genres");
  renderGenreGrid(elements.signupGenreGrid, state.genres, updateSignupGenreCount);
  renderGenreGrid(elements.profileGenreGrid, state.genres, async () => {
    document.getElementById("profile-genre-count").textContent = String(state.genres.size);
  });
  updateSignupGenreCount();
}

function showAuthMessage(message) {
  elements.authAlert.textContent = message;
  elements.authAlert.classList.remove("hidden");
}

function clearAuthMessage() {
  elements.authAlert.textContent = "";
  elements.authAlert.classList.add("hidden");
}

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  elements.toastStack.appendChild(toast);
  window.setTimeout(() => toast.remove(), 3600);
}

function skeletonGrid(count = 6) {
  const card = `
    <article class="skeleton-card">
      <div class="skeleton-poster skeleton"></div>
      <div class="skeleton-body">
        <div class="skeleton-line wide skeleton"></div>
        <div class="skeleton-line med skeleton"></div>
        <div class="skeleton-line short skeleton"></div>
      </div>
    </article>`;
  return Array(count).fill(card).join("");
}

function setLoadingState(container, _message) {
  container.innerHTML = skeletonGrid(6);
}

function setEmptyState(container, message) {
  container.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function setErrorState(container, message) {
  container.innerHTML = `<div class="error-state">${escapeHtml(message)}</div>`;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (state.token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }

  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let payload = null;

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }

  if (response.status === 401) {
    clearSession();
    showAuthView();
    throw new Error("Your session expired. Please sign in again.");
  }

  if (!response.ok) {
    throw new Error(payload?.detail || "Something went wrong.");
  }

  return payload;
}

function showAuthView() {
  elements.authView.classList.remove("hidden");
  elements.appView.classList.add("hidden");
  elements.navAuthButton.classList.remove("hidden");
  elements.navLogoutButton.classList.add("hidden");
  if (elements.navMenu) elements.navMenu.classList.add("hidden");
  elements.navAuthButton.textContent = "Sign in";
}

function showAppView() {
  elements.authView.classList.add("hidden");
  elements.appView.classList.remove("hidden");
  elements.navAuthButton.classList.add("hidden");
  elements.navLogoutButton.classList.remove("hidden");
  if (elements.navMenu) elements.navMenu.classList.remove("hidden");
}

function switchAuthTab(tabName) {
  clearAuthMessage();
  document.querySelectorAll(".auth-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.authTab === tabName);
  });
  elements.loginPanel.classList.toggle("active", tabName === "login");
  elements.signupPanel.classList.toggle("active", tabName === "signup");
}

function countUp(el, target, duration = 900, decimals = 0) {
  const start = performance.now();
  const from = 0;
  function step(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = from + (target - from) * eased;
    el.textContent = decimals ? value.toFixed(decimals) : Math.round(value).toLocaleString();
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function renderCatalogStats(catalog) {
  const elMovies = document.getElementById("stat-total-movies");
  const elGenres = document.getElementById("stat-total-genres");
  const elRating = document.getElementById("stat-average-rating");
  countUp(elMovies, catalog.total_movies, 1000, 0);
  countUp(elGenres, catalog.total_genres, 700, 0);
  countUp(elRating, catalog.average_rating, 800, 2);
  document.getElementById("stat-year-range").textContent = catalog.year_range
    ? `${catalog.year_range[0]}–${catalog.year_range[1]}`
    : "N/A";
}

function renderGenreGrid(container, selectedSet, onToggle) {
  container.innerHTML = state.allGenres
    .map(
      (genre) => `
        <button
          class="genre-chip ${selectedSet.has(genre) ? "selected" : ""}"
          type="button"
          data-genre="${escapeHtml(genre)}"
        >
          ${escapeHtml(genre)}
        </button>
      `
    )
    .join("");

  container.querySelectorAll("[data-genre]").forEach((button) => {
    button.addEventListener("click", () => {
      const genre = button.dataset.genre;
      if (selectedSet.has(genre)) {
        selectedSet.delete(genre);
      } else {
        selectedSet.add(genre);
      }
      button.classList.toggle("selected", selectedSet.has(genre));
      onToggle?.();
    });
  });
}

function updateSignupGenreCount() {
  const count = state.genres.size;
  elements.signupGenreCount.textContent =
    count >= 2 ? `${count} genres selected.` : "Select at least 2 genres.";
}

function renderMovieGrid(container, movies, emptyMessage, actionLabel = "Details") {
  if (!movies?.length) {
    setEmptyState(container, emptyMessage);
    return;
  }

  container.innerHTML = movies
    .map((movie) => {
      const score = scoreLabel(movie);
      const genres = (movie.genres || [])
        .slice(0, 3)
        .map((genre) => `<span class="meta-chip">${escapeHtml(genre)}</span>`)
        .join("");
      const meta = [
        movie.release_year || null,
        movie.runtime ? `${movie.runtime} min` : null,
        typeof movie.vote_average === "number" ? `TMDB ${movie.vote_average.toFixed(1)}` : null,
      ]
        .filter(Boolean)
        .join(" | ");

      return `
        <article class="movie-card">
          <div class="movie-poster">
            ${createPosterMarkup(movie)}
          </div>
          <div class="movie-body">
            <div class="movie-heading">
              <div>
                <h3 class="movie-title">${escapeHtml(movie.title)}</h3>
                <div class="movie-meta">${escapeHtml(meta)}</div>
              </div>
              ${score ? `<span class="score-pill">${escapeHtml(score)}</span>` : ""}
            </div>
            <div class="chip-row">${genres}</div>
            <p class="movie-overview">${escapeHtml(movie.overview || "No synopsis available.")}</p>
            <div class="movie-actions">
              <button class="button button-ghost" type="button" data-open-movie="${movie.id}">
                ${actionLabel}
              </button>
              <button class="button button-secondary" type="button" data-save-movie="${movie.id}">
                Save to library
              </button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  container.querySelectorAll("[data-open-movie]").forEach((button) => {
    button.addEventListener("click", () => {
      const movie = movies.find((entry) => entry.id === Number(button.dataset.openMovie));
      if (movie) {
        openMovieModal(movie);
      }
    });
  });

  container.querySelectorAll("[data-save-movie]").forEach((button) => {
    button.addEventListener("click", async () => {
      const movie = movies.find((entry) => entry.id === Number(button.dataset.saveMovie));
      if (movie) {
        await saveMovieToLibrary(movie);
      }
    });
  });
}

function openMovieModal(movie) {
  state.activeMovie = movie;
  elements.movieModalPoster.innerHTML = createPosterMarkup(movie, "modal");
  elements.movieModalTitle.textContent = movie.title || "Untitled";
  elements.movieModalMeta.textContent = [
    movie.release_year || null,
    movie.runtime ? `${movie.runtime} min` : null,
    typeof movie.vote_average === "number" ? `TMDB ${movie.vote_average.toFixed(1)}` : null,
    typeof movie.vote_count === "number" ? `${movie.vote_count.toLocaleString()} votes` : null,
  ]
    .filter(Boolean)
    .join(" | ");
  elements.movieModalOverview.textContent = movie.overview || "No synopsis available.";
  elements.movieModalGenres.innerHTML = (movie.genres || [])
    .map((genre) => `<span class="meta-chip">${escapeHtml(genre)}</span>`)
    .join("");
  elements.movieModalSave.textContent = state.token ? "Save to library" : "Sign in to save";
  elements.movieModalShell.classList.remove("hidden");
}

function closeMovieModal() {
  state.activeMovie = null;
  elements.movieModalShell.classList.add("hidden");
}

async function saveMovieToLibrary(movie) {
  if (!state.token) {
    switchAuthTab("login");
    showAuthView();
    showToast("Sign in to save movies to your library.", "error");
    return;
  }

  try {
    await api("/watched", {
      method: "POST",
      body: JSON.stringify({
        movie_id: movie.id,
        movie_title: movie.title,
        poster_path: movie.poster_path || "",
        genres: (movie.genres || []).join(", "),
        vote_average: movie.vote_average || null,
      }),
    });
    showToast(`Saved "${movie.title}" to your library.`);
    closeMovieModal();
    await loadLibrary();
    await loadPersonalizedRecommendations();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function renderHistorySeeds() {
  if (!state.historySeeds.length) {
    elements.historySeeds.innerHTML = `<div class="empty-state">No seed titles selected yet.</div>`;
    return;
  }

  elements.historySeeds.innerHTML = state.historySeeds
    .map(
      (movie) => `
        <div class="seed-chip">
          <span>${escapeHtml(movie.title)}</span>
          <button type="button" data-remove-seed="${movie.id}">Remove</button>
        </div>
      `
    )
    .join("");

  elements.historySeeds.querySelectorAll("[data-remove-seed]").forEach((button) => {
    button.addEventListener("click", () => {
      state.historySeeds = state.historySeeds.filter(
        (movie) => movie.id !== Number(button.dataset.removeSeed),
      );
      renderHistorySeeds();
    });
  });
}

function renderProfile() {
  if (!state.profile) {
    return;
  }
  const username = state.profile.username || "?";
  document.getElementById("profile-username").textContent = `Hello, ${username}`;
  const avatarEl = document.getElementById("profile-avatar");
  if (avatarEl) {
    avatarEl.textContent = username.slice(0, 2).toUpperCase();
  }
  document.getElementById("password-form-username").value = username;
  document.getElementById("profile-summary").textContent = `${state.profile.total_watched} saved film(s) across ${state.profile.genres.length} favorite genre(s).`;
  document.getElementById("profile-library-count").textContent = String(state.profile.total_watched);
  document.getElementById("profile-genre-count").textContent = String(state.profile.genres.length);
  elements.libraryBadge.textContent = `${state.profile.total_watched} saved`;
  renderGenreGrid(elements.profileGenreGrid, state.genres, async () => {});
}

function createSearchController(input, results, onPick) {
  let timerId = null;

  async function runSearch() {
    const query = input.value.trim();
    if (query.length < 2) {
      results.classList.add("hidden");
      results.innerHTML = "";
      return;
    }

    try {
      const payload = await api(`/search?q=${encodeURIComponent(query)}&limit=6`);
      if (!payload.movies.length) {
        results.classList.remove("hidden");
        results.innerHTML = `<div class="empty-state">No matches found for "${escapeHtml(query)}".</div>`;
        return;
      }

      results.classList.remove("hidden");
      results.innerHTML = payload.movies
        .map(
          (movie) => `
            <div class="search-result">
              <div>
                <strong>${escapeHtml(movie.title)}</strong>
                <small>${escapeHtml(
                  [movie.release_year, `TMDB ${movie.vote_average}`].filter(Boolean).join(" | "),
                )}</small>
              </div>
              <button class="button button-secondary" type="button" data-pick-movie="${movie.id}">
                Add
              </button>
            </div>
          `
        )
        .join("");

      results.querySelectorAll("[data-pick-movie]").forEach((button) => {
        button.addEventListener("click", () => {
          const movie = payload.movies.find((entry) => entry.id === Number(button.dataset.pickMovie));
          if (movie) {
            onPick(movie);
            input.value = "";
            results.classList.add("hidden");
            results.innerHTML = "";
          }
        });
      });
    } catch (error) {
      results.classList.remove("hidden");
      results.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
    }
  }

  input.addEventListener("input", () => {
    window.clearTimeout(timerId);
    timerId = window.setTimeout(runSearch, 220);
  });

  document.addEventListener("click", (event) => {
    if (!results.contains(event.target) && event.target !== input) {
      results.classList.add("hidden");
    }
  });
}

async function loadPersonalizedRecommendations() {
  setLoadingState(elements.personalizedGrid, "Building your personalized shortlist...");
  try {
    const payload = await api("/recommend/for-me?top_n=12");
    state.personalized = payload.movies;
    elements.personalReason.textContent = payload.reason;
    renderMovieGrid(
      elements.personalizedGrid,
      payload.movies,
      "Save a few movies or choose genres to unlock more tailored picks.",
    );
  } catch (error) {
    setErrorState(elements.personalizedGrid, error.message);
    elements.personalReason.textContent = "We could not calculate your picks just yet.";
  }
}

async function loadGenreRecommendations() {
  if (!state.genres.size) {
    setEmptyState(elements.genreResults, "Choose at least one preferred genre first.");
    return;
  }

  setLoadingState(elements.genreResults, "Generating genre recommendations...");
  try {
    const payload = await api("/recommend/genres", {
      method: "POST",
      body: JSON.stringify({
        genres: [...state.genres],
        top_n: Number(document.getElementById("genre-top-n").value),
        min_rating: Number(document.getElementById("genre-min-rating").value),
        min_votes: 100,
      }),
    });
    renderMovieGrid(
      elements.genreResults,
      payload.movies,
      "Choose at least one genre to preview recommendations.",
    );
  } catch (error) {
    setErrorState(elements.genreResults, error.message);
  }
}

async function runHistoryRecommendations() {
  if (!state.historySeeds.length) {
    setEmptyState(elements.historyResults, "Add at least one seed title first.");
    return;
  }

  setLoadingState(elements.historyResults, "Scanning related titles...");
  try {
    const payload = await api("/recommend/history", {
      method: "POST",
      body: JSON.stringify({
        movie_ids: state.historySeeds.map((movie) => movie.id),
        top_n: 12,
      }),
    });
    renderMovieGrid(elements.historyResults, payload.movies, "No history-based matches found.");
  } catch (error) {
    setErrorState(elements.historyResults, error.message);
  }
}

async function runHybridRecommendations() {
  if (!state.historySeeds.length && !state.genres.size) {
    setEmptyState(elements.hybridResults, "Add seed titles or select genres first.");
    return;
  }

  setLoadingState(elements.hybridResults, "Blending explicit taste with history...");
  try {
    const payload = await api("/recommend/hybrid", {
      method: "POST",
      body: JSON.stringify({
        movie_ids: state.historySeeds.length ? state.historySeeds.map((movie) => movie.id) : [603],
        genres: [...state.genres],
        top_n: 12,
        weight_content: Number(document.getElementById("weight-content").value),
        weight_genre: Number(document.getElementById("weight-genre").value),
      }),
    });
    renderMovieGrid(elements.hybridResults, payload.movies, "No hybrid matches found.");
  } catch (error) {
    setErrorState(elements.hybridResults, error.message);
  }
}

async function loadLibrary() {
  setLoadingState(elements.libraryList, "Loading your saved library...");
  try {
    const payload = await api("/watched");
    if (!state.profile) {
      state.profile = { total_watched: payload.total, genres: [...state.genres], username: state.username };
    }
    state.profile.total_watched = payload.total;
    elements.libraryBadge.textContent = `${payload.total} saved`;

    if (!payload.history.length) {
      setEmptyState(
        elements.libraryList,
        "Your library is empty. Search above or save movies from recommendation cards.",
      );
      return;
    }

    elements.libraryList.innerHTML = payload.history
      .map((entry) => {
        const genreChips = (entry.genres || "")
          .split(",")
          .map((genre) => genre.trim())
          .filter(Boolean)
          .slice(0, 3)
          .map((genre) => `<span class="meta-chip">${escapeHtml(genre)}</span>`)
          .join("");

        return `
          <article class="library-card">
            <div class="movie-poster">
              ${createPosterMarkup(
                {
                  title: entry.movie_title,
                  poster_path: entry.poster_path,
                },
                "library",
              )}
            </div>
            <div class="library-meta">
              <div class="library-title-row">
                <div>
                  <h3>${escapeHtml(entry.movie_title)}</h3>
                  <div class="movie-meta">
                    Saved ${escapeHtml((entry.watched_at || "").slice(0, 10) || "recently")}
                    ${entry.vote_average ? ` | TMDB ${entry.vote_average.toFixed(1)}` : ""}
                  </div>
                </div>
                <div class="chip-row">${genreChips}</div>
              </div>

              <div class="mini-grid">
                <label class="field">
                  <span>Your rating</span>
                  <select data-rating-entry="${entry.id}">
                    <option value="">Unrated</option>
                    <option value="1" ${entry.rating === 1 ? "selected" : ""}>1</option>
                    <option value="2" ${entry.rating === 2 ? "selected" : ""}>2</option>
                    <option value="3" ${entry.rating === 3 ? "selected" : ""}>3</option>
                    <option value="4" ${entry.rating === 4 ? "selected" : ""}>4</option>
                    <option value="5" ${entry.rating === 5 ? "selected" : ""}>5</option>
                  </select>
                </label>
                <label class="field">
                  <span>Saved entry ID</span>
                  <input value="${entry.id}" disabled />
                </label>
              </div>

              <label class="field">
                <span>Notes</span>
                <textarea data-note-entry="${entry.id}" placeholder="What stood out about this film?">${escapeHtml(entry.notes || "")}</textarea>
              </label>

              <div class="library-actions">
                <button class="button button-secondary" type="button" data-save-entry="${entry.id}">
                  Save notes
                </button>
                <button class="button button-ghost" type="button" data-seed-entry="${entry.id}">
                  Use as seed
                </button>
                <button class="button button-ghost" type="button" data-remove-entry="${entry.id}">
                  Remove
                </button>
              </div>
            </div>
          </article>
        `;
      })
      .join("");

    elements.libraryList.querySelectorAll("[data-save-entry]").forEach((button) => {
      button.addEventListener("click", async () => {
        const entryId = Number(button.dataset.saveEntry);
        const ratingField = elements.libraryList.querySelector(`[data-rating-entry="${entryId}"]`);
        const noteField = elements.libraryList.querySelector(`[data-note-entry="${entryId}"]`);

        try {
          await api(`/watched/${entryId}`, {
            method: "PATCH",
            body: JSON.stringify({
              rating: ratingField.value ? Number(ratingField.value) : null,
              notes: noteField.value.trim() || null,
            }),
          });
          showToast("Library entry updated.");
          await loadLibrary();
        } catch (error) {
          showToast(error.message, "error");
        }
      });
    });

    elements.libraryList.querySelectorAll("[data-seed-entry]").forEach((button) => {
      button.addEventListener("click", () => {
        const entryId = Number(button.dataset.seedEntry);
        const entry = payload.history.find((item) => item.id === entryId);
        if (!entry) {
          return;
        }
        if (!state.historySeeds.find((movie) => movie.id === entry.movie_id)) {
          state.historySeeds.push({
            id: entry.movie_id,
            title: entry.movie_title,
            poster_path: entry.poster_path,
            vote_average: entry.vote_average,
            genres: (entry.genres || "").split(",").map((genre) => genre.trim()).filter(Boolean),
          });
          renderHistorySeeds();
          showToast(`Added "${entry.movie_title}" as a history seed.`);
        }
      });
    });

    elements.libraryList.querySelectorAll("[data-remove-entry]").forEach((button) => {
      button.addEventListener("click", async () => {
        const entryId = Number(button.dataset.removeEntry);
        try {
          await api(`/watched/entry/${entryId}`, { method: "DELETE" });
          showToast("Removed from your library.");
          await refreshAuthenticatedData();
        } catch (error) {
          showToast(error.message, "error");
        }
      });
    });
  } catch (error) {
    setErrorState(elements.libraryList, error.message);
  }
}

async function updateGenrePreferences() {
  try {
    const payload = await api("/genres/preferences", {
      method: "PUT",
      body: JSON.stringify({ genres: [...state.genres] }),
    });
    localStorage.setItem("cm_genres", JSON.stringify(payload.genres));
    showToast("Genre preferences saved.");
    await refreshAuthenticatedData();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function refreshAuthenticatedData() {
  const profile = await api("/auth/me");
  state.profile = profile;
  state.username = profile.username;
  state.genres = new Set(profile.genres || []);
  localStorage.setItem("cm_username", profile.username);
  localStorage.setItem("cm_genres", JSON.stringify(profile.genres || []));
  renderProfile();
  renderGenreGrid(elements.profileGenreGrid, state.genres, async () => {});
  await Promise.all([
    loadPersonalizedRecommendations(),
    loadGenreRecommendations(),
    loadLibrary(),
  ]);
}

async function handleLogin(event) {
  event.preventDefault();
  clearAuthMessage();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;

  if (!username || !password) {
    showAuthMessage("Enter both username and password.");
    return;
  }

  try {
    const payload = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setStoredSession(payload);
    showToast("Welcome back.");
    showAppView();
    await refreshAuthenticatedData();
  } catch (error) {
    showAuthMessage(error.message);
  }
}

async function handleSignup(event) {
  event.preventDefault();
  clearAuthMessage();
  const username = document.getElementById("signup-username").value.trim();
  const email = document.getElementById("signup-email").value.trim();
  const password = document.getElementById("signup-password").value;

  if (state.genres.size < 2) {
    showAuthMessage("Choose at least 2 genres to create a taste profile.");
    return;
  }

  try {
    const payload = await api("/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        username,
        email: email || null,
        password,
        genres: [...state.genres],
      }),
    });
    setStoredSession(payload);
    showToast("Account created.");
    showAppView();
    await refreshAuthenticatedData();
  } catch (error) {
    showAuthMessage(error.message);
  }
}

async function handlePasswordChange(event) {
  event.preventDefault();
  const currentPassword = document.getElementById("current-password").value;
  const newPassword = document.getElementById("new-password").value;

  if (!currentPassword || !newPassword) {
    showToast("Enter both the current and new password.", "error");
    return;
  }

  try {
    await api("/auth/password", {
      method: "PUT",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    event.target.reset();
    showToast("Password updated.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function bootstrapPublicData() {
  try {
    const [healthPayload, genrePayload] = await Promise.all([api("/health"), api("/genres")]);
    state.catalog = healthPayload.catalog;
    state.allGenres = genrePayload.genres || [];
    renderCatalogStats(state.catalog);
    renderGenreGrid(elements.signupGenreGrid, state.genres, updateSignupGenreCount);
    renderGenreGrid(elements.profileGenreGrid, state.genres, async () => {});
    updateSignupGenreCount();
  } catch (error) {
    showAuthMessage("The API is not reachable yet. Start the backend and refresh.");
  }
}

function bindEvents() {
  document.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.addEventListener("click", () => switchAuthTab(button.dataset.authTab));
  });

  elements.navAuthButton.addEventListener("click", () => {
    showAuthView();
    switchAuthTab("login");
  });

  elements.navLogoutButton.addEventListener("click", () => {
    clearSession();
    showAuthView();
    showToast("You have been logged out.");
  });

  elements.loginForm.addEventListener("submit", handleLogin);
  elements.signupForm.addEventListener("submit", handleSignup);
  document.getElementById("password-form").addEventListener("submit", handlePasswordChange);
  document.getElementById("refresh-personalized").addEventListener("click", loadPersonalizedRecommendations);
  document.getElementById("run-genre-recommend").addEventListener("click", loadGenreRecommendations);
  document.getElementById("run-history-recommend").addEventListener("click", runHistoryRecommendations);
  document.getElementById("run-hybrid-recommend").addEventListener("click", runHybridRecommendations);
  document.getElementById("save-genre-preferences").addEventListener("click", updateGenrePreferences);
  document.getElementById("clear-history-seeds").addEventListener("click", () => {
    state.historySeeds = [];
    renderHistorySeeds();
    setEmptyState(elements.historyResults, "Add a few seed titles to explore related recommendations.");
  });

  document.getElementById("weight-content").addEventListener("input", (event) => {
    document.getElementById("weight-content-value").textContent = event.target.value;
  });
  document.getElementById("weight-genre").addEventListener("input", (event) => {
    document.getElementById("weight-genre-value").textContent = event.target.value;
  });

  elements.movieModalClose.addEventListener("click", closeMovieModal);
  elements.movieModalShell.addEventListener("click", (event) => {
    if (event.target === elements.movieModalShell) {
      closeMovieModal();
    }
  });
  elements.movieModalSave.addEventListener("click", async () => {
    if (state.activeMovie) {
      await saveMovieToLibrary(state.activeMovie);
    }
  });

  createSearchController(
    document.getElementById("history-search-input"),
    document.getElementById("history-search-results"),
    (movie) => {
      if (!state.historySeeds.find((entry) => entry.id === movie.id)) {
        state.historySeeds.push(movie);
        renderHistorySeeds();
      }
    },
  );

  createSearchController(
    document.getElementById("library-search-input"),
    document.getElementById("library-search-results"),
    async (movie) => {
      await saveMovieToLibrary(movie);
    },
  );
}

async function init() {
  bindEvents();
  renderHistorySeeds();
  setEmptyState(elements.personalizedGrid, "Sign in to build a personalized recommendation stack.");
  setEmptyState(elements.genreResults, "Choose genres, then preview what they surface.");
  setEmptyState(elements.historyResults, "Add a few seed titles to explore related recommendations.");
  setEmptyState(elements.hybridResults, "Blend your seed titles with genre preference weights.");
  setEmptyState(elements.libraryList, "Sign in to start building your library.");

  await bootstrapPublicData();

  if (!state.token) {
    showAuthView();
    return;
  }

  showAppView();
  try {
    await refreshAuthenticatedData();
  } catch (error) {
    clearSession();
    showAuthView();
    showToast(error.message, "error");
  }
}

init();
