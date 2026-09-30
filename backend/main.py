from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.auth import create_access_token, get_current_user, hash_password, verify_password
from backend.config import settings
from backend.database import (
    CustomList,
    CustomListItem,
    GenrePreference,
    User,
    WatchHistory,
    Watchlist,
    create_tables,
    get_db,
)
from backend.rate_limiter import RateLimitMiddleware
from backend.recommender import RecommendationEngine
from backend.schemas import (
    AddListItemRequest,
    AddWatchedRequest,
    AddWatchlistRequest,
    CastMemberOut,
    CatalogPageOut,
    CatalogStatsOut,
    ChangePasswordRequest,
    CreateCustomListRequest,
    CustomListItemOut,
    CustomListOut,
    CustomListsOut,
    DirectorOut,
    ExploreCatalogOut,
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
    RichMovieDetailsOut,
    SaveGenresRequest,
    SearchOut,
    ShareableListOut,
    SignupRequest,
    TokenResponse,
    TrailerOut,
    UpdateCustomListRequest,
    UpdateWatchedRequest,
    UserProfileOut,
    WatchHistoryEntryOut,
    WatchHistoryListOut,
    WatchHistoryMutationOut,
    WatchlistEntryOut,
    WatchlistListOut,
    WatchOptionsOut,
    WatchOptionsRequest,
)
from backend.tmdb import tmdb_client

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        create_tables()
        app.state.database_ready = True
    except (SQLAlchemyError, RuntimeError):
        app.state.database_ready = False
        logger.warning("Personal database is unavailable; discovery can continue while it recovers.")
    engine = RecommendationEngine()
    app.state.engine = engine
    from backend.catalog import CatalogRepository

    app.state.catalog = getattr(engine, "catalog_repository", None) or CatalogRepository()
    logger.info("Recommendation engine ready with %s titles.", len(engine.movies))
    try:
        yield
    finally:
        engine.close()


app = FastAPI(
    title=settings.api_title,
    description="Movie recommendation and personal library API.",
    version=settings.api_version,
    lifespan=lifespan,
)

app.add_middleware(
    RateLimitMiddleware,
    auth_limit=15,
    general_limit=180,
    window_seconds=60,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
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


def get_catalog(request: Request):
    catalog = getattr(request.app.state, "catalog", None)
    if catalog is None:
        from backend.catalog import CatalogRepository

        catalog = CatalogRepository()
        request.app.state.catalog = catalog
    return catalog


def canonical_metadata(movie_id: int, catalog) -> dict:
    movie = catalog.get_movie(movie_id)
    if not movie:
        raise HTTPException(
            status_code=404, detail="Movie not found in catalog. Existing saved entries remain accessible."
        )
    genres = movie.get("genres") or []
    return {
        "movie_title": movie["title"],
        "poster_path": movie.get("poster_path") or "",
        "genres": ", ".join(genres) if isinstance(genres, list) else genres,
        "vote_average": movie.get("vote_average"),
    }


def lock_library_user(db: Session, user_id: int) -> None:
    # The same parent-row write serializes library mutations in both dialects.
    db.query(User).filter(User.id == user_id).update(
        {User.session_version: User.session_version}, synchronize_session=False
    )


def pagination(total: int, page: int, page_size: int) -> dict:
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def owned_list(list_id: int, current_user: User, db: Session) -> CustomList:
    result = (
        db.query(CustomList).filter(CustomList.id == list_id, CustomList.user_id == current_user.id).first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Custom list not found.")
    return result


def list_page(c_list: CustomList, db: Session, page: int = 1, page_size: int = 50) -> CustomListOut:
    query = db.query(CustomListItem).filter(CustomListItem.list_id == c_list.id)
    total = query.count()
    items = (
        query.order_by(CustomListItem.added_at.asc(), CustomListItem.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return CustomListOut(
        id=c_list.id,
        title=c_list.title,
        description=c_list.description,
        share_slug=c_list.share_slug,
        is_public=bool(c_list.is_public),
        created_at=c_list.created_at.isoformat() if c_list.created_at else "",
        item_count=total,
        items=[serialize_custom_list_item(item) for item in items],
        **pagination(total, page, page_size),
    )


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


def serialize_watchlist_entry(entry: Watchlist) -> WatchlistEntryOut:
    added_at = entry.added_at.isoformat() if entry.added_at else ""
    return WatchlistEntryOut(
        id=entry.id,
        movie_id=entry.movie_id,
        movie_title=entry.movie_title,
        poster_path=entry.poster_path or "",
        genres=entry.genres or "",
        vote_average=entry.vote_average,
        added_at=added_at,
    )


def serialize_custom_list_item(item: CustomListItem) -> CustomListItemOut:
    added_at = item.added_at.isoformat() if item.added_at else ""
    return CustomListItemOut(
        id=item.id,
        movie_id=item.movie_id,
        movie_title=item.movie_title,
        poster_path=item.poster_path or "",
        genres=item.genres or "",
        vote_average=item.vote_average,
        added_at=added_at,
    )


def serialize_custom_list(c_list: CustomList) -> CustomListOut:
    created_at = c_list.created_at.isoformat() if c_list.created_at else ""
    items = [serialize_custom_list_item(item) for item in c_list.items]
    return CustomListOut(
        id=c_list.id,
        title=c_list.title,
        description=c_list.description or "",
        share_slug=c_list.share_slug,
        is_public=bool(c_list.is_public),
        created_at=created_at,
        item_count=len(items),
        items=items,
    )


def build_token_response(user: User, db: Session) -> TokenResponse:
    genres = [preference.genre for preference in user.genre_prefs]
    watched_total = db.query(WatchHistory).filter(WatchHistory.user_id == user.id).count()
    return TokenResponse(
        access_token=create_access_token(user.id, user.username, user.session_version),
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


def csv_safe_cell(value: Any) -> Any:
    """Prevent spreadsheet applications from treating exported text as formulas."""
    if not isinstance(value, str):
        return value
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


@app.get("/", include_in_schema=False)
def serve_frontend():
    index_file = settings.frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    favicon = settings.frontend_assets_dir / "favicon.svg"
    if favicon.exists():
        return FileResponse(favicon, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Favicon not found.")


@app.get("/health", response_model=HealthOut, tags=["System"])
def health_check(engine: RecommendationEngine = Depends(get_engine)) -> HealthOut:
    stats = CatalogStatsOut(**engine.get_catalog_stats())
    return HealthOut(
        status="healthy",
        app=settings.app_name,
        version=settings.api_version,
        catalog=stats,
    )


@app.get("/explore", response_model=ExploreCatalogOut, tags=["Discovery"])
def get_explore_catalog(engine: RecommendationEngine = Depends(get_engine)) -> ExploreCatalogOut:
    """Public discovery showcase: Trending Now, Top Rated, and By Decade."""
    data = engine.get_explore_catalog()
    return ExploreCatalogOut(
        trending=[MovieOut(**m) for m in data["trending"]],
        top_rated=[MovieOut(**m) for m in data["top_rated"]],
        by_decade={decade: [MovieOut(**m) for m in movies] for decade, movies in data["by_decade"].items()},
    )


@app.get("/movies/{movie_id}/details", response_model=RichMovieDetailsOut, tags=["Discovery"])
def get_movie_details(
    movie_id: int,
    engine: RecommendationEngine = Depends(get_engine),
    catalog=Depends(get_catalog),
) -> RichMovieDetailsOut:
    """Get rich movie details including YouTube trailer, cast photos, director, financials, and similar titles."""
    local_movie = catalog.get_movie(movie_id) or engine.get_movie_by_id(movie_id)
    if not local_movie:
        raise HTTPException(status_code=404, detail="Movie not found in catalog.")

    tmdb_data = dict(tmdb_client.get_details_and_credits(movie_id) or {})
    for credit_field in ("cast", "directors"):
        if not tmdb_data.get(credit_field):
            tmdb_data[credit_field] = (
                local_movie.get(credit_field) or (local_movie.get("credits") or {}).get(credit_field) or []
            )
    similar_raw = engine.get_similar_movies(movie_id, top_n=6) if engine.get_movie_by_id(movie_id) else []

    # Cast parsing
    cast_list = []
    for c in tmdb_data.get("cast", []):
        cast_list.append(
            CastMemberOut(
                id=c.get("id"),
                name=c.get("name") or "",
                character=c.get("character") or "",
                profile_path=c.get("profile_path"),
                profile_url=c.get("profile_url"),
            )
        )

    directors_list = []
    for d in tmdb_data.get("directors", []):
        directors_list.append(
            DirectorOut(
                id=d.get("id"),
                name=d.get("name") or "",
                job="Director",
                profile_url=d.get("profile_url"),
            )
        )

    trailer_obj = None
    if tmdb_data.get("trailer"):
        t = tmdb_data["trailer"]
        trailer_obj = TrailerOut(
            key=t.get("key", ""),
            name=t.get("name", "Trailer"),
            embed_url=t.get("embed_url", ""),
            watch_url=t.get("watch_url", ""),
        )

    return RichMovieDetailsOut(
        id=local_movie["id"],
        title=local_movie["title"],
        tagline=tmdb_data.get("tagline") or "",
        overview=local_movie["overview"],
        genres=local_movie["genres"],
        vote_average=local_movie["vote_average"],
        vote_count=local_movie["vote_count"],
        release_year=local_movie["release_year"],
        release_date=tmdb_data.get("release_date") or "",
        runtime=local_movie["runtime"] or tmdb_data.get("runtime"),
        popularity=local_movie["popularity"],
        poster_path=local_movie["poster_path"] or tmdb_data.get("poster_path") or "",
        backdrop_path=tmdb_data.get("backdrop_path") or "",
        backdrop_url=tmdb_data.get("backdrop_url"),
        budget=tmdb_data.get("budget", 0),
        revenue=tmdb_data.get("revenue", 0),
        imdb_id=tmdb_data.get("imdb_id"),
        imdb_url=tmdb_data.get("imdb_url"),
        tmdb_url=tmdb_data.get("tmdb_url") or f"https://www.themoviedb.org/movie/{movie_id}",
        trailer=trailer_obj,
        cast=cast_list,
        directors=directors_list,
        similar_movies=[MovieOut(**m) for m in similar_raw],
    )


@app.get("/movies/{movie_id}/similar", response_model=list[MovieOut], tags=["Discovery"])
def get_similar_movies(
    movie_id: int,
    top_n: int = Query(default=6, ge=1, le=20),
    engine: RecommendationEngine = Depends(get_engine),
) -> list[MovieOut]:
    """Get nearest neighbor similar movies via TF-IDF cosine similarity."""
    results = engine.get_similar_movies(movie_id, top_n=top_n)
    return [MovieOut(**m) for m in results]


@app.post("/auth/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, tags=["Auth"])
def signup(
    body: SignupRequest,
    db: Session = Depends(get_db),
    engine: RecommendationEngine = Depends(get_engine),
) -> TokenResponse:
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with that username already exists.",
        )

    if body.email:
        email_existing = db.query(User).filter(User.email == body.email).first()
        if email_existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with that email already exists.",
            )

    clean_genres = engine.normalize_genres(body.genres)
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()

    sync_user_genres(user, clean_genres, db)
    db.commit()
    db.refresh(user)

    return build_token_response(user, db)


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    return build_token_response(user, db)


@app.get("/auth/me", response_model=UserProfileOut, tags=["Auth"])
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileOut:
    history = (
        db.query(WatchHistory)
        .filter(WatchHistory.user_id == current_user.id)
        .order_by(WatchHistory.watched_at.desc(), WatchHistory.id.desc())
        .limit(200)
        .all()
    )
    genres = [preference.genre for preference in current_user.genre_prefs]
    return UserProfileOut(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        total_watched=db.query(WatchHistory).filter(WatchHistory.user_id == current_user.id).count(),
        genres=genres,
        history=[serialize_history_entry(entry) for entry in history],
        created_at=current_user.created_at.isoformat() if current_user.created_at else "",
    )


@app.put("/auth/password", response_model=MessageOut, tags=["Auth"])
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is not correct.",
        )
    current_user.password_hash = hash_password(body.new_password)
    db.query(User).filter(User.id == current_user.id).update(
        {User.session_version: User.session_version + 1}, synchronize_session=False
    )
    db.commit()
    return MessageOut(message="Password updated. All sessions have ended; please sign in again.")


@app.get("/genres", response_model=GenreListOut, tags=["Genres"])
def get_genres(engine: RecommendationEngine = Depends(get_engine)) -> GenreListOut:
    genres = engine.get_all_genres()
    return GenreListOut(genres=genres, count=len(genres))


@app.get("/search", response_model=SearchOut, tags=["Search"])
def search_movies(
    q: str = Query(..., min_length=1, description="Movie title, theme, plot, or keyword to search for"),
    limit: int = Query(default=12, ge=1, le=50),
    engine: RecommendationEngine = Depends(get_engine),
) -> SearchOut:
    payload = engine.search_movies(q, limit=limit)
    return SearchOut(**payload)


@app.post("/recommend/popular", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_popular(
    top_n: int = Query(default=10, ge=1, le=50),
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    movies = engine.recommend_popular(top_n=top_n)
    return RecommendationOut(
        strategy="popular",
        count=len(movies),
        movies=[MovieOut(**movie) for movie in movies],
    )


@app.post("/recommend/genre", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_genre(
    body: GenreRecommendRequest,
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    clean_genres = engine.normalize_genres(body.genres)
    if not clean_genres:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the selected genres were recognized.",
        )

    movies = engine.recommend_by_genres(
        clean_genres,
        top_n=body.top_n,
        min_rating=body.min_rating,
        min_votes=body.min_votes,
    )
    return RecommendationOut(
        strategy="genre_bayesian",
        count=len(movies),
        movies=[MovieOut(**movie) for movie in movies],
    )


@app.post("/recommend/history", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_history(
    body: HistoryRecommendRequest,
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    validate_seed_features(body.movie_ids, engine)
    movies = engine.recommend_by_history(body.movie_ids, top_n=body.top_n)
    if not movies:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not generate recommendations from the supplied movies.",
        )
    return RecommendationOut(
        strategy="content_cosine",
        count=len(movies),
        movies=[MovieOut(**movie) for movie in movies],
    )


@app.post("/recommend/hybrid", response_model=RecommendationOut, tags=["Recommendations"])
def recommend_hybrid(
    body: HybridRecommendRequest,
    engine: RecommendationEngine = Depends(get_engine),
) -> RecommendationOut:
    validate_seed_features(body.movie_ids, engine)
    clean_genres = engine.normalize_genres(body.genres)
    movies = engine.recommend_hybrid(
        body.movie_ids,
        clean_genres,
        top_n=body.top_n,
        weight_content=body.weight_content,
        weight_genre=body.weight_genre,
    )
    if not movies:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not generate hybrid recommendations with supplied inputs.",
        )
    return RecommendationOut(
        strategy="hybrid_content_genre",
        count=len(movies),
        movies=[MovieOut(**movie) for movie in movies],
    )


def validate_seed_features(movie_ids: list[int], engine: RecommendationEngine) -> None:
    missing = [movie_id for movie_id in movie_ids if movie_id not in engine.id_to_index.index]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Selected movies lack recommendation features: {', '.join(map(str, missing))}. Choose another title or browse by genre.",
        )


@app.get("/recommend/me", response_model=PersonalRecommendationOut, tags=["Recommendations"])
def recommend_for_user(
    top_n: int = Query(default=10, ge=1, le=30),
    exclude_watched: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    engine: RecommendationEngine = Depends(get_engine),
) -> PersonalRecommendationOut:
    genres = [preference.genre for preference in current_user.genre_prefs]
    history_records = (
        db.query(WatchHistory)
        .filter(WatchHistory.user_id == current_user.id)
        .order_by(WatchHistory.watched_at.desc())
        .limit(200)
        .all()
    )
    movie_ids = [entry.movie_id for entry in history_records]
    ratings = {entry.movie_id: entry.rating for entry in history_records}
    watched_at = {entry.movie_id: entry.watched_at for entry in history_records}
    base_strategy, reason, movies = engine.recommend_for_user(
        movie_ids,
        genres,
        top_n=top_n,
        ratings=ratings,
        watched_at=watched_at,
        exclude_watched=exclude_watched,
        excluded_movie_ids=[
            row[0]
            for row in db.query(WatchHistory.movie_id).filter(WatchHistory.user_id == current_user.id).all()
        ]
        if exclude_watched
        else [],
    )
    strategy = {
        "hybrid": "personalized_hybrid",
        "content_based": "personalized_history",
        "genre_based": "personalized_genre",
        "popular": "catalog_popular",
        "negative_profile": "personalized_negative_profile",
    }[base_strategy]

    return PersonalRecommendationOut(
        strategy=strategy,
        count=len(movies),
        movies=[MovieOut(**movie) for movie in movies],
        reason=reason,
    )


# Watched library


@app.post("/watched", response_model=WatchHistoryMutationOut, tags=["Library"])
def add_watched(
    body: AddWatchedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    catalog=Depends(get_catalog),
) -> WatchHistoryMutationOut:
    metadata = canonical_metadata(body.movie_id, catalog)
    lock_library_user(db, current_user.id)
    entry = (
        db.query(WatchHistory)
        .filter(WatchHistory.user_id == current_user.id, WatchHistory.movie_id == body.movie_id)
        .first()
    )
    if not entry:
        entry = WatchHistory(user_id=current_user.id, movie_id=body.movie_id, **metadata)
        db.add(entry)
    for key, value in metadata.items():
        setattr(entry, key, value)
    for key in ("rating", "notes"):
        if key in body.model_fields_set:
            setattr(entry, key, getattr(body, key))
    entry.watched_at = datetime.now(UTC)
    db.query(Watchlist).filter(
        Watchlist.user_id == current_user.id, Watchlist.movie_id == body.movie_id
    ).delete(synchronize_session=False)
    db.commit()
    db.refresh(entry)
    return WatchHistoryMutationOut(
        message=f"Saved '{entry.movie_title}' to your library.", entry=serialize_history_entry(entry)
    )


@app.get("/watched", response_model=WatchHistoryListOut, tags=["Library"])
def get_watched(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchHistoryListOut:
    query = db.query(WatchHistory).filter(WatchHistory.user_id == current_user.id)
    total = query.count()
    history = (
        query.order_by(WatchHistory.watched_at.desc(), WatchHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return WatchHistoryListOut(
        history=[serialize_history_entry(entry) for entry in history], **pagination(total, page, page_size)
    )


@app.patch("/watched/{entry_id}", response_model=WatchHistoryMutationOut, tags=["Library"])
def update_watched(
    entry_id: int,
    body: UpdateWatchedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchHistoryMutationOut:
    entry = (
        db.query(WatchHistory)
        .filter(
            WatchHistory.id == entry_id,
            WatchHistory.user_id == current_user.id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Library entry not found.")

    if "rating" in body.model_fields_set:
        entry.rating = body.rating
    if "notes" in body.model_fields_set:
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
    entry = (
        db.query(WatchHistory)
        .filter(
            WatchHistory.id == entry_id,
            WatchHistory.user_id == current_user.id,
        )
        .first()
    )
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
    entry = (
        db.query(WatchHistory)
        .filter(
            WatchHistory.user_id == current_user.id,
            WatchHistory.movie_id == movie_id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Movie not found in your library.")

    movie_title = entry.movie_title
    db.delete(entry)
    db.commit()
    return MessageOut(message=f"Removed '{movie_title}' from your library.")


# Watchlist (want to watch)


@app.get("/watchlist", response_model=WatchlistListOut, tags=["Watchlist"])
def get_watchlist(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistListOut:
    query = db.query(Watchlist).filter(Watchlist.user_id == current_user.id)
    total = query.count()
    items = (
        query.order_by(Watchlist.added_at.desc(), Watchlist.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return WatchlistListOut(
        watchlist=[serialize_watchlist_entry(item) for item in items], **pagination(total, page, page_size)
    )


@app.post("/watchlist", response_model=WatchlistEntryOut, tags=["Watchlist"])
def add_to_watchlist(
    body: AddWatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    catalog=Depends(get_catalog),
) -> WatchlistEntryOut:
    metadata = canonical_metadata(body.movie_id, catalog)
    lock_library_user(db, current_user.id)
    if (
        db.query(WatchHistory.id)
        .filter(WatchHistory.user_id == current_user.id, WatchHistory.movie_id == body.movie_id)
        .first()
    ):
        raise HTTPException(
            status_code=409,
            detail="This movie is already watched. Remove it from your watched library before bookmarking it.",
        )
    item = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id, Watchlist.movie_id == body.movie_id)
        .first()
    )
    if not item:
        item = Watchlist(user_id=current_user.id, movie_id=body.movie_id, **metadata)
        db.add(item)
    else:
        for key, value in metadata.items():
            setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return serialize_watchlist_entry(item)


@app.delete("/watchlist/{movie_id}", response_model=MessageOut, tags=["Watchlist"])
def remove_from_watchlist(
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    item = (
        db.query(Watchlist)
        .filter(
            Watchlist.user_id == current_user.id,
            Watchlist.movie_id == movie_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Movie not found in your watchlist.")

    db.delete(item)
    db.commit()
    return MessageOut(message=f"Removed '{item.movie_title}' from your watchlist.")


@app.post("/watchlist/{movie_id}/watched", response_model=WatchHistoryMutationOut, tags=["Watchlist"])
def move_watchlist_to_watched(
    movie_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> WatchHistoryMutationOut:
    lock_library_user(db, current_user.id)
    item = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id, Watchlist.movie_id == movie_id)
        .first()
    )
    entry = (
        db.query(WatchHistory)
        .filter(WatchHistory.user_id == current_user.id, WatchHistory.movie_id == movie_id)
        .first()
    )
    if not item and not entry:
        raise HTTPException(status_code=404, detail="Movie not found in your watchlist.")
    if not entry:
        # Preserve legacy saved metadata even if this movie is no longer in the catalog.
        entry = WatchHistory(
            user_id=current_user.id,
            movie_id=movie_id,
            movie_title=item.movie_title,
            poster_path=item.poster_path,
            genres=item.genres,
            vote_average=item.vote_average,
        )
        db.add(entry)
    if item:
        db.delete(item)
    db.commit()
    db.refresh(entry)
    return WatchHistoryMutationOut(
        message=f"Saved '{entry.movie_title}' to your library.", entry=serialize_history_entry(entry)
    )


@app.post("/lists", response_model=CustomListOut, tags=["Lists"])
def create_custom_list(
    body: CreateCustomListRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CustomListOut:
    share_slug = uuid.uuid4().hex[:12]
    c_list = CustomList(
        user_id=current_user.id,
        title=body.title.strip(),
        description=(body.description or "").strip(),
        share_slug=share_slug,
        is_public=1 if body.is_public else 0,
    )
    db.add(c_list)
    db.commit()
    db.refresh(c_list)
    return serialize_custom_list(c_list)


@app.get("/lists/my", response_model=CustomListsOut, tags=["Lists"])
def get_my_custom_lists(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CustomListsOut:
    query = db.query(CustomList).filter(CustomList.user_id == current_user.id)
    total = query.count()
    rows = (
        query.order_by(CustomList.created_at.desc(), CustomList.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    ids = [row.id for row in rows]
    counts = (
        dict(
            db.query(CustomListItem.list_id, func.count(CustomListItem.id))
            .filter(CustomListItem.list_id.in_(ids))
            .group_by(CustomListItem.list_id)
            .all()
        )
        if ids
        else {}
    )
    summaries = [
        CustomListOut(
            id=row.id,
            title=row.title,
            description=row.description,
            share_slug=row.share_slug,
            is_public=bool(row.is_public),
            created_at=row.created_at.isoformat() if row.created_at else "",
            item_count=counts.get(row.id, 0),
            total=counts.get(row.id, 0),
            items=[],
        )
        for row in rows
    ]
    return CustomListsOut(lists=summaries, **pagination(total, page, page_size))


@app.post("/lists/{list_id}/items", response_model=CustomListItemOut, tags=["Lists"])
def add_item_to_custom_list(
    list_id: int,
    body: AddListItemRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    catalog=Depends(get_catalog),
) -> CustomListItemOut:
    c_list = (
        db.query(CustomList)
        .filter(
            CustomList.id == list_id,
            CustomList.user_id == current_user.id,
        )
        .first()
    )
    if not c_list:
        raise HTTPException(status_code=404, detail="Custom list not found.")

    metadata = canonical_metadata(body.movie_id, catalog)
    lock_library_user(db, current_user.id)
    existing_item = (
        db.query(CustomListItem)
        .filter(
            CustomListItem.list_id == list_id,
            CustomListItem.movie_id == body.movie_id,
        )
        .first()
    )
    if existing_item:
        return serialize_custom_list_item(existing_item)

    item = CustomListItem(
        list_id=list_id,
        movie_id=body.movie_id,
        **metadata,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_custom_list_item(item)


@app.delete("/lists/{list_id}/items/{movie_id}", response_model=MessageOut, tags=["Lists"])
def remove_item_from_custom_list(
    list_id: int,
    movie_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    c_list = (
        db.query(CustomList)
        .filter(
            CustomList.id == list_id,
            CustomList.user_id == current_user.id,
        )
        .first()
    )
    if not c_list:
        raise HTTPException(status_code=404, detail="Custom list not found.")

    item = (
        db.query(CustomListItem)
        .filter(
            CustomListItem.list_id == list_id,
            CustomListItem.movie_id == movie_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Movie not found in list.")

    db.delete(item)
    db.commit()
    return MessageOut(message=f"Removed '{item.movie_title}' from '{c_list.title}'.")


@app.delete("/lists/{list_id}", response_model=MessageOut, tags=["Lists"])
def delete_custom_list(
    list_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    c_list = (
        db.query(CustomList)
        .filter(
            CustomList.id == list_id,
            CustomList.user_id == current_user.id,
        )
        .first()
    )
    if not c_list:
        raise HTTPException(status_code=404, detail="Custom list not found.")

    title = c_list.title
    db.delete(c_list)
    db.commit()
    return MessageOut(message=f"Deleted list '{title}'.")


@app.get("/lists/share/{share_slug}", response_model=ShareableListOut, tags=["Lists"])
def get_shared_list(
    share_slug: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ShareableListOut:
    c_list = (
        db.query(CustomList).filter(CustomList.share_slug == share_slug, CustomList.is_public == 1).first()
    )
    if not c_list:
        raise HTTPException(status_code=404, detail="Curated list not found or private.")
    result = list_page(c_list, db, page, page_size)
    return ShareableListOut(
        id=c_list.id,
        title=c_list.title,
        description=c_list.description,
        creator_username=c_list.user.username,
        share_slug=c_list.share_slug,
        created_at=result.created_at,
        items=result.items,
        **pagination(result.total, page, page_size),
    )


@app.get("/library/export", tags=["Library"])
def export_library_data(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export complete user library and watchlist as CSV or JSON download."""
    watched_entries = (
        db.query(WatchHistory)
        .filter(WatchHistory.user_id == current_user.id)
        .order_by(WatchHistory.watched_at.desc())
        .all()
    )
    watchlist_entries = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id)
        .order_by(Watchlist.added_at.desc())
        .all()
    )

    watched_data = [
        {
            "movie_id": e.movie_id,
            "title": e.movie_title,
            "genres": e.genres or "",
            "vote_average": e.vote_average,
            "user_rating": e.rating,
            "user_notes": e.notes or "",
            "watched_at": e.watched_at.isoformat() if e.watched_at else "",
        }
        for e in watched_entries
    ]

    watchlist_data = [
        {
            "movie_id": w.movie_id,
            "title": w.movie_title,
            "genres": w.genres or "",
            "vote_average": w.vote_average,
            "added_at": w.added_at.isoformat() if w.added_at else "",
        }
        for w in watchlist_entries
    ]

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["Type", "Movie ID", "Title", "Genres", "Vote Average", "User Rating", "Notes", "Date"]
        )

        for item in watched_data:
            writer.writerow(
                [
                    "Watched",
                    item["movie_id"],
                    csv_safe_cell(item["title"]),
                    csv_safe_cell(item["genres"]),
                    item["vote_average"],
                    item["user_rating"],
                    csv_safe_cell(item["user_notes"]),
                    item["watched_at"],
                ]
            )

        for item in watchlist_data:
            writer.writerow(
                [
                    "Watchlist",
                    item["movie_id"],
                    csv_safe_cell(item["title"]),
                    csv_safe_cell(item["genres"]),
                    item["vote_average"],
                    "",
                    "",
                    item["added_at"],
                ]
            )

        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="cinematch_{current_user.username}_export.csv"'
            },
        )

    # Default JSON
    export_payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "username": current_user.username,
        "total_watched": len(watched_data),
        "total_watchlist": len(watchlist_data),
        "watched_history": watched_data,
        "watchlist": watchlist_data,
    }
    return Response(
        content=json.dumps(export_payload, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="cinematch_{current_user.username}_export.json"'
        },
    )


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


@app.get("/lists/{list_id}", response_model=CustomListOut, tags=["Lists"])
def get_custom_list(
    list_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_page(owned_list(list_id, current_user, db), db, page, page_size)


@app.patch("/lists/{list_id}", response_model=CustomListOut, tags=["Lists"])
def update_custom_list(
    list_id: int,
    body: UpdateCustomListRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    c_list = owned_list(list_id, current_user, db)
    for key in body.model_fields_set:
        value = getattr(body, key)
        setattr(c_list, key, int(value) if key == "is_public" else value)
    db.commit()
    db.refresh(c_list)
    return list_page(c_list, db)


@app.post("/auth/revoke-sessions", response_model=MessageOut, tags=["Auth"])
def revoke_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == current_user.id).update(
        {User.session_version: User.session_version + 1}, synchronize_session=False
    )
    db.commit()
    return MessageOut(message="All sessions have ended. Please sign in again.")


@app.get("/ready", tags=["System"])
def readiness(request: Request, db: Session = Depends(get_db)):
    if getattr(request.app.state, "database_ready", True) is False:
        return Response(
            content=json.dumps({"status": "degraded", "database": "migration_required"}),
            media_type="application/json",
            status_code=503,
        )
    try:
        db.execute(text("SELECT 1"))
        for model in (User, WatchHistory, Watchlist, CustomList, CustomListItem, GenrePreference):
            db.query(model).limit(0).all()
    except SQLAlchemyError:
        db.rollback()
        return Response(
            content=json.dumps({"status": "degraded", "database": "unavailable"}),
            media_type="application/json",
            status_code=503,
        )
    available = getattr(request.app.state, "engine", None) is not None
    catalog_available = False
    try:
        catalog = getattr(request.app.state, "catalog", None)
        catalog_available = catalog is not None and catalog.stats()["total_movies"] > 0
        if catalog_available:
            catalog.metadata()
    except (sqlite3.Error, RuntimeError, OSError):
        catalog_available = False
    available = available and catalog_available
    return Response(
        content=json.dumps(
            {
                "status": "ready" if available else "starting",
                "database": "available",
                "recommendations": "available" if available else "starting",
                "catalog": "available" if catalog_available else "unavailable",
            }
        ),
        media_type="application/json",
        status_code=200 if available else 503,
    )


@app.get("/catalog", response_model=CatalogPageOut, tags=["Discovery"])
def browse_catalog(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = None,
    min_rating: float = Query(default=0, ge=0, le=10),
    year_from: int | None = Query(default=None, ge=1800, le=2100),
    year_to: int | None = Query(default=None, ge=1800, le=2100),
    sort: str = Query(default="popular", pattern="^(popular|rating|year_desc|year_asc|title)$"),
    catalog=Depends(get_catalog),
):
    if year_from and year_to and year_from > year_to:
        raise HTTPException(status_code=422, detail="Start year must be before end year.")
    return catalog.browse(
        page=page,
        page_size=page_size,
        genre=genre,
        year_from=year_from,
        year_to=year_to,
        sort=sort,
        min_rating=min_rating,
    )


@app.get("/watch/countries", tags=["Watch"])
def watch_countries():
    return {"countries": tmdb_client.get_countries(), "default_country": "IN"}


@app.post("/watch/options", response_model=WatchOptionsOut, tags=["Watch"])
def watch_options(body: WatchOptionsRequest):
    if body.country not in {row["code"] for row in tmdb_client.get_countries()}:
        raise HTTPException(status_code=422, detail="Select a supported country.")
    ids = list(dict.fromkeys(body.movie_ids))
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(
            workers.map(lambda movie_id: tmdb_client.get_watch_options(movie_id, body.country), ids)
        )
    return WatchOptionsOut(country=body.country, movies=results)


@app.get("/library/status", tags=["Library"])
def library_status(
    movie_ids: str = Query(..., max_length=600),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ids = list(dict.fromkeys(int(value) for value in movie_ids.split(",")))
        if not ids or len(ids) > 50 or any(movie_id <= 0 for movie_id in ids):
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Supply between 1 and 50 positive movie IDs separated by commas."
        ) from None
    watched = {
        row[0]
        for row in db.query(WatchHistory.movie_id)
        .filter(WatchHistory.user_id == current_user.id, WatchHistory.movie_id.in_(ids))
        .all()
    }
    watchlisted = {
        row[0]
        for row in db.query(Watchlist.movie_id)
        .filter(Watchlist.user_id == current_user.id, Watchlist.movie_id.in_(ids))
        .all()
    }
    return {
        "movies": [
            {"movie_id": movie_id, "watched": movie_id in watched, "watchlisted": movie_id in watchlisted}
            for movie_id in ids
        ]
    }


@app.get("/catalog/metadata", tags=["Discovery"])
def catalog_metadata(catalog=Depends(get_catalog)):
    return catalog.metadata()
