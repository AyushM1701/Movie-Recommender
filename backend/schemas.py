from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
POSTER_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._-]+\.(?:jpe?g|png|webp)$", re.IGNORECASE)


def _clean_genre_list(genres: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for genre in genres:
        normalized = genre.strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        cleaned.append(normalized)
        seen.add(lowered)
    return cleaned


class SignupRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_\-]+$",
    )
    email: str | None = Field(default=None, max_length=100)
    password: str = Field(..., min_length=6, max_length=100)
    genres: list[str] = Field(default_factory=list, max_length=19)

    @field_validator("username")
    @classmethod
    def username_not_reserved(cls, value: str) -> str:
        if value.lower() in {"admin", "root", "api", "null", "undefined"}:
            raise ValueError("That username is reserved.")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not EMAIL_PATTERN.match(value):
            raise ValueError("Please enter a valid email address.")
        return value

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        return _clean_genre_list(value)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


def validate_password(value: str) -> str:
    if value.isdigit():
        raise ValueError("Password cannot be all numbers.")
    return value


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=100)

    _password_strength = field_validator("new_password")(validate_password)


class SaveGenresRequest(BaseModel):
    genres: list[str] = Field(default_factory=list, max_length=19)

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        return _clean_genre_list(value)


class GenreRecommendRequest(BaseModel):
    genres: list[str] = Field(..., min_length=1, max_length=19)
    top_n: int = Field(default=10, ge=1, le=50)
    min_rating: float = Field(default=6.0, ge=0.0, le=10.0, allow_inf_nan=False)
    min_votes: int = Field(default=100, ge=0)

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        cleaned = _clean_genre_list(value)
        if not cleaned:
            raise ValueError("Select at least one genre.")
        return cleaned


class HistoryRecommendRequest(BaseModel):
    movie_ids: list[int] = Field(..., min_length=1, max_length=200)
    top_n: int = Field(default=10, ge=1, le=50)


class HybridRecommendRequest(BaseModel):
    movie_ids: list[int] = Field(default_factory=list, max_length=200)
    genres: list[str] = Field(default_factory=list, max_length=19)
    top_n: int = Field(default=10, ge=1, le=50)
    weight_content: float = Field(default=0.7, ge=0.0, le=1.0)
    weight_genre: float = Field(default=0.3, ge=0.0, le=1.0)

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        return _clean_genre_list(value)

    @model_validator(mode="after")
    def validate_weights(self) -> HybridRecommendRequest:
        if not ((self.movie_ids and self.weight_content > 0) or (self.genres and self.weight_genre > 0)):
            raise ValueError("Supply movie seeds or genres with a positive corresponding weight.")
        if self.weight_content + self.weight_genre <= 0:
            raise ValueError("At least one recommendation weight must be greater than zero.")
        return self


class MovieLibraryPayload(BaseModel):
    """Catalog metadata stored alongside a user's personal library records."""

    movie_id: int = Field(..., ge=1, description="TMDB movie ID")
    movie_title: str = Field(..., min_length=1, max_length=300)
    poster_path: str = Field(default="", max_length=200)
    genres: str = Field(default="", max_length=300)
    vote_average: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)

    @field_validator("movie_title")
    @classmethod
    def clean_movie_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Movie title cannot be blank.")
        return value

    @field_validator("poster_path")
    @classmethod
    def validate_poster_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not POSTER_PATH_PATTERN.fullmatch(value):
            raise ValueError("poster_path must be a TMDB image path such as /poster.jpg.")
        return value

    @field_validator("genres")
    @classmethod
    def clean_genres_text(cls, value: str) -> str:
        return value.strip()


class AddWatchedRequest(MovieLibraryPayload):
    rating: float | None = Field(default=None, ge=1.0, le=5.0, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=500)


class UpdateWatchedRequest(BaseModel):
    rating: float | None = Field(default=None, ge=1.0, le=5.0, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=500)


class MessageOut(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    genres: list[str]
    total_watched: int


class MovieOut(BaseModel):
    id: int
    title: str
    overview: str
    genres: list[str]
    vote_average: float
    vote_count: int
    release_year: str | None = None
    runtime: int | None = None
    popularity: float
    poster_path: str | None = ""
    bayesian_score: float | None = None
    similarity_score: float | None = None
    hybrid_score: float | None = None


class RecommendationOut(BaseModel):
    strategy: str
    count: int
    movies: list[MovieOut]


class PersonalRecommendationOut(RecommendationOut):
    reason: str


class GenreListOut(BaseModel):
    genres: list[str]
    count: int


class SearchOut(BaseModel):
    query: str
    match_type: str = "title_match"  # "title_match" | "theme_genre_match"
    exact_match: bool = True
    message: str | None = None
    detected_genres: list[str] = Field(default_factory=list)
    count: int
    movies: list[MovieOut]


class CatalogStatsOut(BaseModel):
    total_movies: int
    total_genres: int
    average_rating: float
    posters_available: int
    year_range: list[int] | None = None


class WatchHistoryEntryOut(BaseModel):
    id: int
    movie_id: int
    movie_title: str
    poster_path: str | None = ""
    genres: str | None = ""
    vote_average: float | None = None
    rating: float | None = None
    notes: str | None = None
    watched_at: str


class PaginationOut(BaseModel):
    total: int
    page: int = 1
    page_size: int = 50
    pages: int = 0


class WatchHistoryListOut(PaginationOut):
    history: list[WatchHistoryEntryOut]


class WatchHistoryMutationOut(BaseModel):
    message: str
    entry: WatchHistoryEntryOut | None = None


class UserProfileOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    total_watched: int
    genres: list[str]
    history: list[WatchHistoryEntryOut]
    created_at: str


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    catalog: CatalogStatsOut


class CastMemberOut(BaseModel):
    id: int | None = None
    name: str
    character: str | None = ""
    profile_path: str | None = None
    profile_url: str | None = None


class DirectorOut(BaseModel):
    id: int | None = None
    name: str
    job: str = "Director"
    profile_url: str | None = None


class TrailerOut(BaseModel):
    key: str
    name: str
    embed_url: str
    watch_url: str


class RichMovieDetailsOut(BaseModel):
    id: int
    title: str
    tagline: str | None = ""
    overview: str
    genres: list[str]
    vote_average: float
    vote_count: int
    release_year: str | None = None
    release_date: str | None = None
    runtime: int | None = None
    popularity: float
    poster_path: str | None = ""
    backdrop_path: str | None = ""
    backdrop_url: str | None = None
    budget: int | None = 0
    revenue: int | None = 0
    imdb_id: str | None = None
    imdb_url: str | None = None
    tmdb_url: str | None = None
    trailer: TrailerOut | None = None
    cast: list[CastMemberOut] = Field(default_factory=list)
    directors: list[DirectorOut] = Field(default_factory=list)
    similar_movies: list[MovieOut] = Field(default_factory=list)


class ExploreCatalogOut(BaseModel):
    trending: list[MovieOut]
    top_rated: list[MovieOut]
    by_decade: dict[str, list[MovieOut]]


class AddWatchlistRequest(MovieLibraryPayload):
    pass


class WatchlistEntryOut(BaseModel):
    id: int
    movie_id: int
    movie_title: str
    poster_path: str | None = ""
    genres: str | None = ""
    vote_average: float | None = None
    added_at: str


class WatchlistListOut(PaginationOut):
    watchlist: list[WatchlistEntryOut]


def validate_list_title(value: str) -> str:
    value = value.strip()
    if len(value) < 2:
        raise ValueError("List title must contain at least two characters.")
    return value


class CreateCustomListRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=190)
    description: str | None = Field(default="", max_length=1000)
    is_public: bool = Field(default=True)

    _title_clean = field_validator("title")(validate_list_title)


class UpdateCustomListRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    is_public: bool | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if value is None:
            raise ValueError("List title cannot be null.")
        return validate_list_title(value)

    @field_validator("is_public")
    @classmethod
    def validate_visibility(cls, value):
        if value is None:
            raise ValueError("List visibility cannot be null.")
        return value


class AddListItemRequest(MovieLibraryPayload):
    pass


class CustomListItemOut(BaseModel):
    id: int
    movie_id: int
    movie_title: str
    poster_path: str | None = ""
    genres: str | None = ""
    vote_average: float | None = None
    added_at: str


class CustomListOut(PaginationOut):
    total: int = 0
    id: int
    title: str
    description: str | None = ""
    share_slug: str
    is_public: bool
    created_at: str
    item_count: int
    items: list[CustomListItemOut] = Field(default_factory=list)


class CustomListsOut(PaginationOut):
    lists: list[CustomListOut]


class ShareableListOut(PaginationOut):
    id: int
    title: str
    description: str | None = ""
    creator_username: str
    share_slug: str
    created_at: str
    items: list[CustomListItemOut]


class LibraryExportDataOut(BaseModel):
    exported_at: str
    username: str
    total_watched: int
    total_watchlist: int
    watched_history: list[dict[str, Any]]
    watchlist: list[dict[str, Any]]


class WatchOptionsRequest(BaseModel):
    movie_ids: list[Annotated[int, Field(ge=1)]] = Field(..., min_length=1, max_length=50)
    country: str = Field(default="IN", pattern=r"^[A-Z]{2}$")


class WatchProviderOut(BaseModel):
    id: int
    name: str
    logo_path: str | None = None
    types: list[Literal["flatrate", "free", "ads", "rent", "buy"]]


class MovieWatchOptionsOut(BaseModel):
    movie_id: int
    country: str
    status: Literal["available", "not_listed", "unavailable"]
    link: str
    providers: list[WatchProviderOut]
    checked_at: str


class WatchOptionsOut(BaseModel):
    country: str
    movies: list[MovieWatchOptionsOut]


class CatalogPageOut(PaginationOut):
    movies: list[MovieOut]
