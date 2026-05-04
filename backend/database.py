from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from backend.config import settings


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
    future=True,
)


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _record) -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    watch_history = relationship(
        "WatchHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="WatchHistory.watched_at.desc()",
    )
    genre_prefs = relationship(
        "GenrePreference",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="GenrePreference.genre.asc()",
    )


class WatchHistory(Base):
    __tablename__ = "watch_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    movie_id = Column(Integer, nullable=False, index=True)
    movie_title = Column(String(300), nullable=False)
    poster_path = Column(String(200), nullable=True, default="")
    genres = Column(String(300), nullable=True, default="")
    vote_average = Column(Float, nullable=True)
    rating = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    watched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_user_movie"),)

    user = relationship("User", back_populates="watch_history")


class GenrePreference(Base):
    __tablename__ = "genre_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    genre = Column(String(80), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "genre", name="uq_user_genre"),)

    user = relationship("User", back_populates="genre_prefs")


MIGRATION_COLUMNS = {
    "users": {
        "email": "VARCHAR(100)",
        "password_hash": "VARCHAR(255) NOT NULL DEFAULT ''",
        "created_at": "DATETIME",
    },
    "watch_history": {
        "poster_path": "VARCHAR(200) DEFAULT ''",
        "genres": "VARCHAR(300) DEFAULT ''",
        "vote_average": "FLOAT",
        "rating": "FLOAT",
        "notes": "TEXT",
        "watched_at": "DATETIME",
    },
    "genre_preferences": {
        "genre": "VARCHAR(80)",
    },
}


def migrate() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table_name, columns in MIGRATION_COLUMNS.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_sql in columns.items():
                if column_name in existing_columns:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                )


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    migrate()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
