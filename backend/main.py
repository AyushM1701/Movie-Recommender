from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

try:
    from .auth import create_access_token, get_current_user, hash_password, verify_password
    from .config import settings
    from .database import GenrePreference, User, WatchHistory, create_tables, get_db
    from .recommender import RecommendationEngine
    from .schemas import (
        AddWatchedRequest,
        CatalogStatsOut,
        ChangePasswordRequest,
        GenreListOut,
        GenreRecommendRequest,
        HealthOut,
        HistoryRecommendRequest,
        HybridRecommendRequest,
        LoginRequest,
        MessageOut,
        MovieOut,
        PersonalRecommendationOut,
        RecommendationOut,
        SaveGenresRequest,
        SearchOut,
        SignupRequest,
        TokenResponse,
        UpdateWatchedRequest,
        UserProfileOut,
        WatchHistoryEntryOut,
        WatchHistoryListOut,
        WatchHistoryMutationOut,
    )
except ImportError:  # pragma: no cover - fallback for direct script execution
    from auth import create_access_token, get_current_user, hash_password, verify_password
    from config import settings
    from database import GenrePreference, User, WatchHistory, create_tables, get_db
    from recommender import RecommendationEngine
    from schemas import (
        AddWatchedRequest,
        CatalogStatsOut,
        ChangePasswordRequest,
        GenreListOut,
        GenreRecommendRequest,
        HealthOut,
        HistoryRecommendRequest,
        HybridRecommendRequest,
        LoginRequest,
        MessageOut,
        MovieOut,
        PersonalRecommendationOut,
        RecommendationOut,
        SaveGenresRequest,
        SearchOut,
        SignupRequest,
        TokenResponse,
        UpdateWatchedRequest,
        UserProfileOut,
        WatchHistoryEntryOut,
        WatchHistoryListOut,
        WatchHistoryMutationOut,
    )


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    app.state.engine = RecommendationEngine()
    logger.info("Recommendation engine ready with %s titles.", len(app.state.engine.movies))
    yield


app = FastAPI(
    title=settings.api_title,
    description="Movie recommendation and personal library API.",
    version=settings.api_version,
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if settings.frontend_assets_dir.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(settings.frontend_assets_dir)),
        name="assets",
    )


def get_engine(request: Request) -> RecommendationEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation engine is still starting up.",
        )
    return engine


def serialize_history_entry(entry: WatchHistory) -> WatchHistoryEntryOut:
    watched_at = entry.watched_at.isoformat() if entry.watched_at else ""
    return WatchHistoryEntryOut(
        id=entry.id,
        movie_id=entry.movie_id,
        movie_title=entry.movie_title,
        poster_path=entry.poster_path or "",
        genres=entry.genres or "",
        vote_average=entry.vote_average,
        rating=entry.rating,
        notes=entry.notes,
        watched_at=watched_at,
    )


def build_token_response(user: User, db: Session) -> TokenResponse:
    genres = [preference.genre for preference in user.genre_prefs]
    watched_total = db.query(WatchHistory).filter(WatchHistory.user_id == user.id).count()
    return TokenResponse(
        access_token=create_access_token(user.id, user.username),
        user_id=user.id,
        username=user.username,
        genres=genres,
        total_watched=watched_total,
    )


def sync_user_genres(user: User, genres: list[str], db: Session) -> list[str]:
    db.query(GenrePreference).filter(GenrePreference.user_id == user.id).delete()
    for genre in genres:
        db.add(GenrePreference(user_id=user.id, genre=genre))
    return genres


@app.get("/", include_in_schema=False)
def serve_home() -> FileResponse:
    return FileResponse(settings.frontend_dir / "index.html")


@app.get("/login", include_in_schema=False)
@app.get("/login.html", include_in_schema=False)
def serve_login() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/Login.html", include_in_schema=False)
def serve_legacy_login() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(
        settings.frontend_assets_dir / "favicon.svg",
        media_type="image/svg+xml",
    )


@app.get("/health", response_model=HealthOut, tags=["System"])
def health(engine: RecommendationEngine = Depends(get_engine)) -> HealthOut:
    return HealthOut(
        status="ok",
        app=settings.app_name,
        version=settings.api_version,
        catalog=CatalogStatsOut(**engine.get_catalog_stats()),
    )


@app.get("/stats/catalog", response_model=CatalogStatsOut, tags=["Discovery"])
def catalog_stats(engine: RecommendationEngine = Depends(get_engine)) -> CatalogStatsOut:
    return CatalogStatsOut(**engine.get_catalog_stats())


@app.post("/auth/signup", response_model=TokenResponse, tags=["Auth"], status_code=201)
def signup(
    body: SignupRequest,
    db: Session = Depends(get_db),
    engine: RecommendationEngine = Depends(get_engine),
) -> TokenResponse:
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail=f"Username '{body.username}' is already taken.")

    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="That email is already registered.")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()

    clean_genres = engine.normalize_genres(body.genres)
    sync_user_genres(user, clean_genres, db)

    db.commit()
    db.refresh(user)
    logger.info("Registered user %s (%s).", user.username, user.id)
    return build_token_response(user, db)


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    logger.info("User logged in: %s", user.username)
    return build_token_response(user, db)


@app.get("/auth/me", response_model=UserProfileOut, tags=["Auth"])
def get_me(current_user: User = Depends(get_current_user)) -> UserProfileOut:
    history = [serialize_history_entry(entry) for entry in current_user.watch_history]
    genres = [preference.genre for preference in current_user.genre_prefs]
    created_at = current_user.created_at.isoformat() if current_user.created_at else ""
    return UserProfileOut(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        total_watched=len(history),
        genres=genres,
        history=history,
        created_at=created_at,
    )


@app.put("/auth/password", response_model=MessageOut, tags=["Auth"])
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    current_user.password_hash = hash_password(body.new_password)
    db.commit()
    return MessageOut(message="Password updated successfully.")


@app.get("/genres", response_model=GenreListOut, tags=["Discovery"])
def list_genres(engine: RecommendationEngine = Depends(get_engine)) -> GenreListOut:
    genres = engine.get_all_genres()
    return GenreListOut(genres=genres, count=len(genres))


@app.get("/search", response_model=SearchOut, tags=["Discovery"])
def search_movies(
    q: str = Query(..., min_length=2, description="Movie title to search for."),
    limit: int = Query(default=10, ge=1, le=20),
    engine: RecommendationEngine = Depends(get_engine),
) -> SearchOut:
    movies = engine.search_movies(q, limit=limit)
    return SearchOut(query=q, count=len(movies), movies=movies)


@app.get("/movies/{movie_id}", response_model=MovieOut, tags=["Discovery"])
def get_movie(movie_id: int, engine: RecommendationEngine = Depends(get_engine)) -> MovieOut:
    movie = engine.get_movie_by_id(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail=f"Movie {movie_id} was not found.")
    return MovieOut(**movie)


@app.post("/recommend/genres", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_by_genres(
    body: GenreRecommendRequest,
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    clean_genres = engine.normalize_genres(body.genres)
    if not clean_genres:
        raise HTTPException(status_code=400, detail="No valid genres were supplied.")

    movies = engine.recommend_by_genres(
        genres=clean_genres,
        top_n=body.top_n,
        min_votes=body.min_votes,
        min_rating=body.min_rating,
    )
    if not movies:
        raise HTTPException(status_code=404, detail="No movies found for the selected genres.")
    return RecommendationOut(strategy="genre_based", count=len(movies), movies=movies)


@app.post("/recommend/history", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_by_history(
    body: HistoryRecommendRequest,
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    movies = engine.recommend_by_history(movie_ids=body.movie_ids, top_n=body.top_n)
    if not movies:
        raise HTTPException(status_code=404, detail="No recommendations found for that history.")
    return RecommendationOut(strategy="content_based", count=len(movies), movies=movies)


@app.post("/recommend/hybrid", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_hybrid(
    body: HybridRecommendRequest,
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    movies = engine.recommend_hybrid(
        movie_ids=body.movie_ids,
        genres=body.genres,
        top_n=body.top_n,
        weight_content=body.weight_content,
        weight_genre=body.weight_genre,
    )
    if not movies:
        raise HTTPException(status_code=404, detail="No hybrid recommendations found.")
    return RecommendationOut(strategy="hybrid", count=len(movies), movies=movies)


@app.get("/recommend/for-me", response_model=PersonalRecommendationOut, tags=["Recommendations"])
def recommend_for_me(
    top_n: int = Query(default=12, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    engine: RecommendationEngine = Depends(get_engine),
) -> PersonalRecommendationOut:
    history_ids = [entry.movie_id for entry in current_user.watch_history]
    genres = [preference.genre for preference in current_user.genre_prefs]
    strategy, reason, movies = engine.recommend_for_user(history_ids, genres, top_n=top_n)
    return PersonalRecommendationOut(
        strategy=strategy,
        reason=reason,
        count=len(movies),
        movies=movies,
    )


@app.post("/watched", response_model=WatchHistoryMutationOut, tags=["Library"], status_code=201)
def add_watched(
    body: AddWatchedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchHistoryMutationOut:
    existing = db.query(WatchHistory).filter(
        WatchHistory.user_id == current_user.id,
        WatchHistory.movie_id == body.movie_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"'{body.movie_title}' is already in your library.")

    entry = WatchHistory(
        user_id=current_user.id,
        movie_id=body.movie_id,
        movie_title=body.movie_title,
        poster_path=body.poster_path or "",
        genres=body.genres or "",
        vote_average=body.vote_average,
        rating=body.rating,
        notes=body.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return WatchHistoryMutationOut(
        message=f"Saved '{body.movie_title}' to your library.",
        entry=serialize_history_entry(entry),
    )


@app.get("/watched", response_model=WatchHistoryListOut, tags=["Library"])
def get_watched(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchHistoryListOut:
    history = (
        db.query(WatchHistory)
        .filter(WatchHistory.user_id == current_user.id)
        .order_by(WatchHistory.watched_at.desc())
        .all()
    )
    return WatchHistoryListOut(
        total=len(history),
        history=[serialize_history_entry(entry) for entry in history],
    )


@app.patch("/watched/{entry_id}", response_model=WatchHistoryMutationOut, tags=["Library"])
def update_watched(
    entry_id: int,
    body: UpdateWatchedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchHistoryMutationOut:
    entry = db.query(WatchHistory).filter(
        WatchHistory.id == entry_id,
        WatchHistory.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Library entry not found.")

    if body.rating is not None:
        entry.rating = body.rating
    if body.notes is not None:
        entry.notes = body.notes

    db.commit()
    db.refresh(entry)
    return WatchHistoryMutationOut(
        message=f"Updated '{entry.movie_title}'.",
        entry=serialize_history_entry(entry),
    )


@app.delete("/watched/entry/{entry_id}", response_model=MessageOut, tags=["Library"])
def remove_watched_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    entry = db.query(WatchHistory).filter(
        WatchHistory.id == entry_id,
        WatchHistory.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Library entry not found.")

    movie_title = entry.movie_title
    db.delete(entry)
    db.commit()
    return MessageOut(message=f"Removed '{movie_title}' from your library.")


@app.delete("/watched/{movie_id}", response_model=MessageOut, tags=["Library"])
def remove_watched_by_movie(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    entry = db.query(WatchHistory).filter(
        WatchHistory.user_id == current_user.id,
        WatchHistory.movie_id == movie_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Movie not found in your library.")

    movie_title = entry.movie_title
    db.delete(entry)
    db.commit()
    return MessageOut(message=f"Removed '{movie_title}' from your library.")


@app.put("/genres/preferences", response_model=GenreListOut, tags=["Genres"])
def update_genres(
    body: SaveGenresRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    engine: RecommendationEngine = Depends(get_engine),
) -> GenreListOut:
    clean_genres = engine.normalize_genres(body.genres)
    sync_user_genres(current_user, clean_genres, db)
    db.commit()
    return GenreListOut(genres=clean_genres, count=len(clean_genres))
