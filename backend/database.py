from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime

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
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import settings

logger = logging.getLogger(__name__)


def configure_sqlite(connection, _record) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def _get_engine():
    # Registration precedes every checkout, including the very first connection.
    db_url = settings.database_url
    url = make_url(db_url)
    pool_options = (
        {"poolclass": StaticPool}
        if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:")
        else {}
    )
    eng = create_engine(
        db_url,
        connect_args={"check_same_thread": False, "timeout": 5} if db_url.startswith("sqlite") else {},
        pool_pre_ping=True,
        future=True,
        **pool_options,
    )
    if eng.dialect.name == "sqlite":
        event.listen(eng, "connect", configure_sqlite)
    return eng


engine = _get_engine()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False, default="")
    session_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    watch_history = relationship(
        "WatchHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="WatchHistory.watched_at.desc()",
    )
    watchlist = relationship(
        "Watchlist",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Watchlist.added_at.desc()",
    )
    genre_prefs = relationship(
        "GenrePreference",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="GenrePreference.genre.asc()",
    )
    custom_lists = relationship(
        "CustomList",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="CustomList.created_at.desc()",
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
    watched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_user_movie"),)

    user = relationship("User", back_populates="watch_history")


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    movie_id = Column(Integer, nullable=False, index=True)
    movie_title = Column(String(300), nullable=False)
    poster_path = Column(String(200), nullable=True, default="")
    genres = Column(String(300), nullable=True, default="")
    vote_average = Column(Float, nullable=True)
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_user_watchlist_movie"),)

    user = relationship("User", back_populates="watchlist")


class CustomList(Base):
    __tablename__ = "custom_lists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True, default="")
    share_slug = Column(String(64), unique=True, index=True, nullable=False)
    is_public = Column(Integer, default=1)  # 1 = public, 0 = private
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="custom_lists")
    items = relationship(
        "CustomListItem",
        back_populates="custom_list",
        cascade="all, delete-orphan",
        order_by="CustomListItem.added_at.asc()",
    )


class CustomListItem(Base):
    __tablename__ = "custom_list_items"

    id = Column(Integer, primary_key=True, index=True)
    list_id = Column(Integer, ForeignKey("custom_lists.id"), nullable=False, index=True)
    movie_id = Column(Integer, nullable=False, index=True)
    movie_title = Column(String(300), nullable=False)
    poster_path = Column(String(200), nullable=True, default="")
    genres = Column(String(300), nullable=True, default="")
    vote_average = Column(Float, nullable=True)
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (UniqueConstraint("list_id", "movie_id", name="uq_list_movie"),)

    custom_list = relationship("CustomList", back_populates="items")


class GenrePreference(Base):
    __tablename__ = "genre_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    genre = Column(String(80), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "genre", name="uq_user_genre"),)

    user = relationship("User", back_populates="genre_prefs")


SCHEMA_VERSION = 1


def _backup_sqlite(bind) -> str | None:
    """SQLite online backup includes committed WAL pages without touching the source."""
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    db_path = bind.url.database
    if bind.dialect.name != "sqlite" or not db_path or db_path == ":memory:":
        return None
    path = Path(db_path)
    if not path.exists():
        return None
    backup = path.with_name(
        path.name + ".pre-migration-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".bak"
    )
    with closing(sqlite3.connect(str(path))) as source, closing(sqlite3.connect(str(backup))) as destination:
        source.backup(destination)
    logger.info("Saved a personal-database backup before schema migration.")
    return str(backup)


def migrate(bind=None) -> None:
    """One additive, recorded migration; compile types using the actual dialect."""
    import uuid

    from sqlalchemy.schema import CreateColumn

    target = bind or engine
    existing = set(inspect(target).get_table_names())
    if "schema_migrations" in existing:
        with target.connect() as connection:
            version = connection.execute(text("SELECT MAX(version) FROM schema_migrations")).scalar() or 0
        if version >= SCHEMA_VERSION:
            return
    if existing:
        _backup_sqlite(target)
    with target.begin() as connection:
        inspector = inspect(connection)
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                # Required identity columns cannot be inferred without losing data.
                if column.primary_key or column.name in {
                    "user_id",
                    "movie_id",
                    "movie_title",
                    "list_id",
                    "username",
                    "title",
                }:
                    raise RuntimeError(
                        "Legacy database is missing required identity columns; restore its backup and migrate explicitly."
                    )
                addition = Column(
                    column.name, column.type, nullable=True, server_default=column.server_default
                )
                sql = str(CreateColumn(addition).compile(dialect=target.dialect))
                connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {sql}'))
            for column in table.columns:
                if isinstance(column.type, DateTime):
                    connection.execute(
                        text(
                            f'UPDATE "{table.name}" SET "{column.name}" = CURRENT_TIMESTAMP WHERE "{column.name}" IS NULL'
                        )
                    )
            if table.name == "users":
                connection.execute(text("UPDATE users SET password_hash = '' WHERE password_hash IS NULL"))
                connection.execute(text("UPDATE users SET session_version = 0 WHERE session_version IS NULL"))
            if table.name == "custom_lists":
                rows = connection.execute(
                    text("SELECT id FROM custom_lists WHERE share_slug IS NULL OR share_slug = ''")
                ).fetchall()
                for row in rows:
                    connection.execute(
                        text("UPDATE custom_lists SET share_slug=:slug WHERE id=:id"),
                        {"slug": uuid.uuid4().hex, "id": row[0]},
                    )
        Base.metadata.create_all(connection)
        # Enforce parent references for legacy tables as well as fresh schemas.
        after = inspect(connection)
        for table in Base.metadata.sorted_tables:
            existing_fks = {tuple(item["constrained_columns"]) for item in after.get_foreign_keys(table.name)}
            for column in table.columns:
                for foreign_key in column.foreign_keys:
                    parent = foreign_key.column.table.name
                    parent_column = foreign_key.column.name
                    orphan = connection.execute(
                        text(
                            f'SELECT 1 FROM "{table.name}" child LEFT JOIN "{parent}" parent ON child."{column.name}" = parent."{parent_column}" WHERE child."{column.name}" IS NULL OR parent."{parent_column}" IS NULL LIMIT 1'
                        )
                    ).first()
                    if orphan:
                        raise RuntimeError(
                            "Legacy database contains orphaned personal records; backup preserved."
                        )
                    if (column.name,) in existing_fks:
                        continue
                    name = f"fk_{table.name}_{column.name}"
                    if target.dialect.name == "sqlite":
                        for operation in ("INSERT", "UPDATE"):
                            connection.execute(
                                text(
                                    f"""CREATE TRIGGER IF NOT EXISTS "{name}_{operation.lower()}" BEFORE {operation} ON "{table.name}" WHEN NEW."{column.name}" IS NULL OR NOT EXISTS (SELECT 1 FROM "{parent}" WHERE "{parent_column}" = NEW."{column.name}") BEGIN SELECT RAISE(ABORT, 'Invalid parent reference'); END"""
                                )
                            )
                        connection.execute(
                            text(
                                f"""CREATE TRIGGER IF NOT EXISTS "{name}_delete" BEFORE DELETE ON "{parent}" WHEN EXISTS (SELECT 1 FROM "{table.name}" WHERE "{column.name}" = OLD."{parent_column}") BEGIN SELECT RAISE(ABORT, 'Parent still has saved records'); END"""
                            )
                        )
                    else:
                        connection.execute(
                            text(
                                f'ALTER TABLE "{table.name}" ADD CONSTRAINT "{name}" FOREIGN KEY ("{column.name}") REFERENCES "{parent}" ("{parent_column}")'
                            )
                        )
        # Legacy tables need the same uniqueness guarantees as fresh tables.
        for table in Base.metadata.sorted_tables:
            for constraint in table.constraints:
                if not isinstance(constraint, UniqueConstraint):
                    continue
                columns = ", ".join(f'"{column.name}"' for column in constraint.columns)
                name = constraint.name or "uq_" + table.name + "_" + "_".join(
                    column.name for column in constraint.columns
                )
                connection.execute(
                    text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{name}" ON "{table.name}" ({columns})')
                )
        from sqlalchemy.schema import CreateIndex

        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                if index.unique:
                    columns = ", ".join(f'"{column.name}"' for column in index.columns)
                    # Use a separate name if a legacy nonunique index already occupied it.
                    connection.execute(
                        text(
                            f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_legacy_{index.name}" ON "{table.name}" ({columns})'
                        )
                    )
                else:
                    connection.execute(CreateIndex(index, if_not_exists=True))
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": SCHEMA_VERSION}
        )
        if target.dialect.name == "sqlite":
            if connection.execute(text("PRAGMA foreign_key_check")).fetchone():
                raise RuntimeError("Legacy database contains orphaned personal records; backup preserved.")


def create_tables(bind=None) -> None:
    migrate(bind)


def get_db() -> Iterator[Session]:
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError

    db = SessionLocal()
    try:
        yield db
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This change conflicts with an existing record. Refresh and try again."
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.warning("A personal-database operation failed; its transaction was rolled back.")
        raise HTTPException(
            status_code=503, detail="The personal library is temporarily unavailable. Please try again."
        ) from None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
