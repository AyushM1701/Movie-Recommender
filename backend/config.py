from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_ASSETS_DIR = FRONTEND_DIR / "assets"
MODEL_DIR = PROJECT_ROOT / "models"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DATABASE_PATH = DATA_DIR / "movie_recommender.db"

DEFAULT_DEV_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
)


def _default_database_url() -> str:
    return f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


def _parse_csv_list(raw_value: str | None, fallback: tuple[str, ...]) -> list[str]:
    if raw_value is None:
        return list(fallback)
    values = [value.strip() for value in raw_value.split(",")]
    return [value for value in values if value]


@dataclass(frozen=True)
class Settings:
    app_name: str = "CineMatch"
    api_title: str = "CineMatch API"
    api_version: str = "3.0.0"
    database_url: str = _default_database_url()
    secret_key: str = os.getenv(
        "CINEMATCH_SECRET_KEY",
        "cinematch-development-secret-change-me",
    )
    token_expire_days: int = int(os.getenv("CINEMATCH_TOKEN_EXPIRE_DAYS", "30"))
    cors_origins: list[str] = None  # type: ignore[assignment]
    frontend_dir: Path = FRONTEND_DIR
    frontend_assets_dir: Path = FRONTEND_ASSETS_DIR
    model_dir: Path = MODEL_DIR
    data_dir: Path = DATA_DIR
    tmdb_api_key: str = os.getenv("TMDB_API_KEY", "b7e0ee4b33e7c9bb2552547f2806d383")
    enable_poster_lookup: bool = os.getenv("CINEMATCH_ENABLE_POSTER_LOOKUP", "1").strip() not in {"0", "false", "False"}

    def __post_init__(self) -> None:
        db_url = os.getenv("CINEMATCH_DATABASE_URL", self.database_url)
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        
        object.__setattr__(
            self,
            "database_url",
            db_url,
        )
        object.__setattr__(
            self,
            "cors_origins",
            _parse_csv_list(os.getenv("CINEMATCH_CORS_ORIGINS"), DEFAULT_DEV_ORIGINS),
        )


settings = Settings()
