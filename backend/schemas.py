from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    genres: list[str] = Field(default_factory=list, max_length=15)

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
        if value.isdigit():
            raise ValueError("Password cannot be all numbers.")
        return value

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        return _clean_genre_list(value)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=100)


class SaveGenresRequest(BaseModel):
    genres: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        return _clean_genre_list(value)


class GenreRecommendRequest(BaseModel):
    genres: list[str] = Field(..., min_length=1, max_length=10)
    top_n: int = Field(default=10, ge=1, le=50)
    min_rating: float = Field(default=6.0, ge=0.0, le=10.0)
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
    movie_ids: list[int] = Field(..., min_length=1, max_length=200)
    genres: list[str] = Field(default_factory=list, max_length=10)
    top_n: int = Field(default=10, ge=1, le=50)
    weight_content: float = Field(default=0.7, ge=0.0, le=1.0)
    weight_genre: float = Field(default=0.3, ge=0.0, le=1.0)

    @field_validator("genres")
    @classmethod
    def clean_genres(cls, value: list[str]) -> list[str]:
        return _clean_genre_list(value)

    @model_validator(mode="after")
    def validate_weights(self) -> "HybridRecommendRequest":
        if self.weight_content + self.weight_genre <= 0:
            raise ValueError("At least one recommendation weight must be greater than zero.")
        return self


class AddWatchedRequest(BaseModel):
    movie_id: int = Field(..., description="TMDB movie ID")
    movie_title: str = Field(..., min_length=1, max_length=300)
    poster_path: str | None = Field(default="")
    genres: str | None = Field(default="")
    vote_average: float | None = Field(default=None)
    rating: float | None = Field(default=None, ge=1.0, le=5.0)
    notes: str | None = Field(default=None, max_length=500)


class UpdateWatchedRequest(BaseModel):
    rating: float | None = Field(default=None, ge=1.0, le=5.0)
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


class WatchHistoryListOut(BaseModel):
    total: int
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
