"""Indexed, read-only catalog repository independent of personal library storage."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.sqlite3"


def _text(value):
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)


def _number(value, default=0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _list(value):
    if isinstance(value, list):
        return value
    if not _text(value).strip():
        return []
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return parsed
    except (TypeError, ValueError):
        pass
    return [name.strip() for name in str(value).split(",") if name.strip()]


def movie_record(row):
    genres = [
        item.get("name", "") if isinstance(item, dict) else str(item)
        for item in _list(row.get("genres_list", row.get("genres")))
    ]
    cast = _list(row.get("cast"))
    directors = [
        item for item in _list(row.get("crew")) if isinstance(item, dict) and item.get("job") == "Director"
    ]
    if not cast:
        cast = [{"name": name} for name in _list(row.get("cast_list"))]
    if not directors:
        directors = [{"name": name, "job": "Director"} for name in _list(row.get("director_list"))]
    release = _text(row.get("release_date"))
    return {
        "id": int(row["id"]),
        "title": _text(row.get("title")).strip(),
        "overview": _text(row.get("overview")),
        "genres": [name for name in genres if name],
        "vote_average": min(10, max(0, _number(row.get("vote_average")))),
        "vote_count": max(0, int(_number(row.get("vote_count")))),
        "release_year": release[:4] if release[:4].isdigit() else None,
        "release_date": release or None,
        "runtime": int(_number(row.get("runtime"))) or None,
        "popularity": max(0, _number(row.get("popularity"))),
        "poster_path": _text(row.get("poster_path")),
        "backdrop_path": _text(row.get("backdrop_path")),
        "tagline": _text(row.get("tagline")),
        "cast": cast[:20],
        "directors": directors,
        "credits": {"cast": cast[:20], "crew": directors},
    }


def publish_catalog(movies, path: Path, metadata: dict):
    """Validate/build a complete replacement; no live user database is involved."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(
            "CREATE TABLE movies(id INTEGER PRIMARY KEY,title TEXT NOT NULL,title_key TEXT NOT NULL,release_date TEXT,release_year INTEGER,popularity REAL,vote_average REAL,vote_count INTEGER,poster_path TEXT,payload TEXT NOT NULL); CREATE INDEX movie_titles ON movies(title_key); CREATE INDEX movie_dates ON movies(release_date,id); CREATE INDEX movie_popularity ON movies(popularity DESC,id); CREATE TABLE genres(movie_id INTEGER,genre TEXT,PRIMARY KEY(movie_id,genre)); CREATE INDEX genre_names ON genres(genre,movie_id); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
        )
        inserted = 0
        for row in movies.to_dict(orient="records"):
            if _number(row.get("id")) < 1 or not _text(row.get("title")).strip():
                continue
            record = movie_record(row)
            connection.execute(
                "INSERT OR REPLACE INTO movies VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record["id"],
                    record["title"],
                    record["title"].casefold(),
                    record["release_date"],
                    int(record["release_year"]) if record["release_year"] else None,
                    record["popularity"],
                    record["vote_average"],
                    record["vote_count"],
                    record["poster_path"],
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO genres VALUES (?,?)",
                ((record["id"], name) for name in record["genres"]),
            )
            inserted += 1
        if not inserted:
            raise RuntimeError("Cannot publish an empty catalog; previous catalog retained.")
        connection.executemany(
            "INSERT INTO metadata VALUES (?,?)",
            ((key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()),
        )
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Catalog integrity validation failed.")
    finally:
        connection.close()
    os.replace(temporary, path)


class CatalogRepository:
    def __init__(self, path: Path | None = None):
        configured = path or os.environ.get("CINEMATCH_CATALOG_PATH")
        self.path = Path(configured or CATALOG_PATH)
        if not configured:
            model_root = Path(__file__).resolve().parent.parent / "models"
            pointer = model_root / "active.json"
            if pointer.exists():
                generation = json.loads(pointer.read_text(encoding="utf-8"))["generation"]
                if Path(generation).name != generation or generation in (".", ".."):
                    raise RuntimeError("Invalid active catalog generation.")
                self.path = model_root / "generations" / generation / "catalog.sqlite3"

    @contextmanager
    def _connection(self):
        if not self.path.exists():
            raise RuntimeError("Catalog is not provisioned. Run python -m backend.data_preprocessing.")
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()

    def get_movie(self, movie_id: int) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM movies WHERE id=?", (movie_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def search_titles(self, query: str, limit: int = 12) -> list[dict]:
        query = query.strip().casefold()
        if not query:
            return []
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM movies WHERE title_key LIKE ? ESCAPE '\\' ORDER BY (title_key=?) DESC,(title_key LIKE ? ESCAPE '\\') DESC,popularity DESC,id LIMIT ?",
                (f"%{escaped}%", query, f"{escaped}%", max(1, min(limit, 100))),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def browse(
        self, page=1, page_size=24, genre=None, year_from=None, year_to=None, sort="popular", min_rating=0
    ):
        page, page_size = max(1, int(page)), max(1, min(100, int(page_size)))
        orders = {
            "popular": "m.popularity DESC,m.id",
            "newest": "m.release_date DESC,m.id",
            "oldest": "m.release_date ASC,m.id",
            "year_desc": "m.release_date DESC,m.id",
            "year_asc": "m.release_date ASC,m.id",
            "highest_rated": "m.vote_average DESC,m.vote_count DESC,m.id",
            "rating": "m.vote_average DESC,m.vote_count DESC,m.id",
            "title": "m.title_key,m.id",
        }
        if sort not in orders:
            raise ValueError("Unknown catalog sort.")
        conditions, params = [], []
        if not 0 <= float(min_rating) <= 10:
            raise ValueError("Minimum rating must be between zero and ten.")
        if min_rating:
            conditions.append("m.vote_average>=?")
            params.append(float(min_rating))
        if genre:
            conditions.append(
                "EXISTS (SELECT 1 FROM genres g WHERE g.movie_id=m.id AND g.genre=? COLLATE NOCASE)"
            )
            params.append(genre)
        if year_from is not None:
            conditions.append("m.release_year>=?")
            params.append(int(year_from))
        if year_to is not None:
            conditions.append("m.release_year<=?")
            params.append(int(year_to))
        # Upcoming titles cannot be presented as released films.
        metadata = self.metadata()
        if metadata.get("cutoff"):
            conditions.append("(m.release_date IS NULL OR m.release_date<=?)")
            params.append(metadata["cutoff"])
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM movies m" + where, params).fetchone()[0]
            rows = connection.execute(
                "SELECT m.payload FROM movies m" + where + " ORDER BY " + orders[sort] + " LIMIT ? OFFSET ?",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "movies": [json.loads(row[0]) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": math.ceil(total / page_size),
        }

    def stats(self):
        with self._connection() as connection:
            total, average, posters, oldest, newest = connection.execute(
                "SELECT COUNT(*),AVG(vote_average),SUM(poster_path!=''),MIN(release_year),MAX(release_year) FROM movies"
            ).fetchone()
            genres = connection.execute("SELECT COUNT(DISTINCT genre) FROM genres").fetchone()[0]
        return {
            "total_movies": total,
            "total_genres": genres,
            "average_rating": round(average or 0, 2),
            "posters_available": posters or 0,
            "year_range": [oldest, newest] if oldest is not None else None,
        }

    def metadata(self):
        with self._connection() as connection:
            return {
                key: json.loads(value) for key, value in connection.execute("SELECT key,value FROM metadata")
            }
