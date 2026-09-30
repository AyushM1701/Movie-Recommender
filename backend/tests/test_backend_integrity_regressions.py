import os

os.environ["CINEMATCH_DATABASE_URL"] = "sqlite://"
os.environ["TMDB_API_KEY"] = ""
os.environ["CINEMATCH_ENABLE_POSTER_LOOKUP"] = "false"

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import database, main
from backend.auth import create_access_token, hash_password
from backend.database import Base, User, WatchHistory, Watchlist, get_db
from backend.schemas import (
    AddWatchedRequest,
    ChangePasswordRequest,
    CreateCustomListRequest,
    HybridRecommendRequest,
    SaveGenresRequest,
)


class SchemaIntegrityTests(unittest.TestCase):
    def test_numeric_changed_password_rejected(self):
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(current_password="oldpass", new_password="123456")

    def test_whitespace_list_title_rejected(self):
        with self.assertRaises(ValidationError):
            CreateCustomListRequest(title="   ")

    def test_nonfinite_catalog_rating_rejected(self):
        for value in (float("nan"), float("inf"), -1, 11):
            with self.assertRaises(ValidationError):
                AddWatchedRequest(movie_id=1, movie_title="Title", vote_average=value)

    def test_genre_only_hybrid_and_all_supported_genres(self):
        self.assertEqual(HybridRecommendRequest(movie_ids=[], genres=["Drama"]).movie_ids, [])
        self.assertEqual(len(SaveGenresRequest(genres=[str(i) for i in range(19)]).genres), 19)


class BackendIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.Session() as db:
            user = User(username="regression", password_hash=hash_password("oldpassword"))
            db.add(user)
            db.commit()
            db.refresh(user)
            self.user_id = user.id
            self.token = create_access_token(user.id, user.username)

        def dependency():
            with self.Session() as db:
                yield db

        main.app.dependency_overrides[get_db] = dependency
        self.movie = {
            "id": 1,
            "title": "Canonical title",
            "overview": "",
            "genres": ["Drama"],
            "vote_average": 7.0,
            "vote_count": 50,
            "popularity": 1.0,
            "poster_path": "/real.jpg",
            "release_year": "2001",
            "runtime": 90,
        }
        main.app.state.catalog = SimpleNamespace(
            stats=lambda: {"total_movies": 1},
            metadata=lambda: {"cutoff": "2026-09-30"},
            get_movie=lambda movie_id: self.movie if movie_id == 1 else None,
        )
        main.app.dependency_overrides[main.get_engine] = lambda: SimpleNamespace(
            normalize_genres=lambda genres: genres
        )
        self.client = TestClient(main.app)
        self.headers = {"Authorization": "Bearer " + self.token}
        from backend.rate_limiter import limiter

        with limiter._lock:
            limiter._history.clear()

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()

    def add(self, **extra):
        return self.client.post(
            "/watched",
            headers=self.headers,
            json={"movie_id": 1, "movie_title": "Forged title", "vote_average": 9.0, **extra},
        )

    def test_pre_migration_token_without_version_claim_is_rejected(self):
        from jose import jwt

        from backend.auth import ALGORITHM, decode_token
        from backend.config import settings

        payload = decode_token(self.token)
        payload.pop("sv")
        headers = {"Authorization": "Bearer " + jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)}
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_ready_does_not_pass_after_migration_failure(self):
        main.app.state.database_ready = False
        main.app.state.engine = SimpleNamespace()
        try:
            self.assertEqual(self.client.get("/ready").status_code, 503)
        finally:
            main.app.state.database_ready = True

    def test_watch_batch_preserves_known_cards_when_legacy_id_is_missing(self):
        def options(movie_id, country):
            return {
                "movie_id": movie_id,
                "country": country,
                "status": "not_listed" if movie_id == 1 else "unavailable",
                "link": f"https://www.themoviedb.org/movie/{movie_id}/watch?locale={country}",
                "providers": [],
                "checked_at": "2026-09-30T00:00:00Z",
            }

        with (
            patch.object(main.tmdb_client, "get_countries", return_value=[{"code": "IN", "name": "India"}]),
            patch.object(main.tmdb_client, "get_watch_options", side_effect=options),
        ):
            response = self.client.post("/watch/options", json={"movie_ids": [1, 999]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["status"] for row in response.json()["movies"]], ["not_listed", "unavailable"])

    def test_password_change_revokes_old_token(self):
        response = self.client.put(
            "/auth/password",
            headers=self.headers,
            json={"current_password": "oldpassword", "new_password": "newpassword"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers).status_code, 401)
        self.assertEqual(
            self.client.post(
                "/auth/login", json={"username": "regression", "password": "newpassword"}
            ).status_code,
            200,
        )

    def test_new_library_write_uses_canonical_metadata_and_rejects_unknown(self):
        response = self.add()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["entry"]["movie_title"], "Canonical title")
        self.assertEqual(response.json()["entry"]["vote_average"], 7.0)
        response = self.client.post(
            "/watchlist", headers=self.headers, json={"movie_id": 999, "movie_title": "Unknown"}
        )
        self.assertEqual(response.status_code, 404)

    def test_nullable_patch_clears_only_supplied_fields(self):
        entry = self.add(rating=4, notes="Keep me").json()["entry"]
        response = self.client.patch(f"/watched/{entry['id']}", headers=self.headers, json={"rating": None})
        self.assertIsNone(response.json()["entry"]["rating"])
        self.assertEqual(response.json()["entry"]["notes"], "Keep me")
        response = self.client.patch(f"/watched/{entry['id']}", headers=self.headers, json={"notes": None})
        self.assertIsNone(response.json()["entry"]["notes"])

    def test_watched_cannot_be_added_to_watchlist_and_repeated_move_is_safe(self):
        self.add()
        response = self.client.post(
            "/watchlist", headers=self.headers, json={"movie_id": 1, "movie_title": "Title"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post("/watchlist/1/watched", headers=self.headers).status_code, 200)

    def test_update_existing_watched_removes_legacy_overlap(self):
        self.add()
        with self.Session() as db:
            db.add(Watchlist(user_id=self.user_id, movie_id=1, movie_title="Legacy overlap"))
            db.commit()
        self.add()
        self.assertEqual(self.client.get("/watchlist", headers=self.headers).json()["total"], 0)

    def test_collections_paginate_and_profile_is_bounded(self):
        with self.Session() as db:
            db.add_all(
                [
                    WatchHistory(user_id=self.user_id, movie_id=i + 10, movie_title=f"Legacy {i}")
                    for i in range(205)
                ]
            )
            db.commit()
        response = self.client.get("/watched?page=2&page_size=10", headers=self.headers)
        self.assertEqual(len(response.json()["history"]), 10)
        self.assertEqual(response.json()["total"], 205)
        self.assertEqual(response.json()["pages"], 21)
        profile = self.client.get("/auth/me", headers=self.headers).json()
        self.assertEqual(profile["total_watched"], 205)
        self.assertLessEqual(len(profile["history"]), 200)

    def test_visible_movie_library_status(self):
        self.add()
        response = self.client.get("/library/status?movie_ids=1,2", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["movies"],
            [
                {"movie_id": 1, "watched": True, "watchlisted": False},
                {"movie_id": 2, "watched": False, "watchlisted": False},
            ],
        )
        self.assertEqual(
            self.client.get("/library/status?movie_ids=bad", headers=self.headers).status_code, 422
        )

    def test_full_exclusions_are_separate_from_bounded_profile(self):
        with self.Session() as db:
            db.add_all(
                [
                    WatchHistory(user_id=self.user_id, movie_id=i + 10, movie_title=f"Old {i}", rating=1)
                    for i in range(205)
                ]
            )
            db.commit()
        seen = {}

        def recommend(movie_ids, genres, **kwargs):
            seen.update(kwargs)
            seen["profile_ids"] = movie_ids
            return "popular", "No positive ratings", []

        main.app.dependency_overrides[main.get_engine] = lambda: SimpleNamespace(recommend_for_user=recommend)
        response = self.client.get("/recommend/me", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(seen["profile_ids"]), 200)
        self.assertEqual(len(seen["excluded_movie_ids"]), 205)

    def test_catalog_exposes_actual_generation_provenance(self):
        main.app.state.catalog.metadata = lambda: {
            "cutoff": "2026-09-30",
            "scope": "released films",
            "retrieved_at": "2026-09-30T00:00:00Z",
        }
        response = self.client.get("/catalog/metadata")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cutoff"], "2026-09-30")

    def test_watch_batch_validates_country_and_batch_size(self):
        with (
            patch.object(main.tmdb_client, "get_countries", return_value=[{"code": "IN", "name": "India"}]),
            patch.object(
                main.tmdb_client,
                "get_watch_options",
                return_value={
                    "movie_id": 1,
                    "country": "IN",
                    "status": "not_listed",
                    "link": "https://www.themoviedb.org/movie/1/watch?locale=IN",
                    "providers": [],
                    "checked_at": "2026-09-30T00:00:00Z",
                },
            ),
        ):
            response = self.client.post("/watch/options", json={"movie_ids": [1, 1]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["movies"]), 1)
            self.assertEqual(
                self.client.post("/watch/options", json={"movie_ids": [1], "country": "ZZ"}).status_code, 422
            )
            self.assertEqual(
                self.client.post("/watch/options", json={"movie_ids": [1] * 51}).status_code, 422
            )

    def test_ready_does_not_pass_with_missing_personal_schema(self):
        empty_engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        EmptySession = sessionmaker(bind=empty_engine)

        def empty_db():
            with EmptySession() as db:
                yield db

        main.app.dependency_overrides[get_db] = empty_db
        main.app.state.engine = SimpleNamespace()
        try:
            self.assertEqual(self.client.get("/ready").status_code, 503)
        finally:
            empty_engine.dispose()

    def test_list_summaries_use_a_bounded_number_of_queries(self):
        from sqlalchemy import event

        from backend.database import CustomList, CustomListItem

        with self.Session() as db:
            for index in range(10):
                row = CustomList(user_id=self.user_id, title=f"List {index}", share_slug=f"slug-{index}")
                db.add(row)
                db.flush()
                db.add(CustomListItem(list_id=row.id, movie_id=1, movie_title="Canonical"))
            db.commit()
        statements = []

        def count(connection, cursor, statement, parameters, context, many):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", count)
        try:
            response = self.client.get("/lists/my?page_size=10", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["lists"]), 10)
            self.assertTrue(all(row["item_count"] == 1 for row in response.json()["lists"]))
            self.assertLessEqual(len(statements), 4)
        finally:
            event.remove(self.engine, "before_cursor_execute", count)

    def test_ready_reports_database_failure_and_recovery(self):
        from sqlalchemy.exc import OperationalError

        broken = SimpleNamespace(
            execute=lambda statement: (_ for _ in ()).throw(
                OperationalError("probe", {}, Exception("offline"))
            ),
            rollback=lambda: None,
        )
        main.app.dependency_overrides[get_db] = lambda: broken
        self.assertEqual(self.client.get("/ready").status_code, 503)
        main.app.state.engine = SimpleNamespace()
        main.app.dependency_overrides[get_db] = lambda: self.Session()
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "available")

    def test_other_user_cannot_manage_private_list(self):
        data = self.client.post(
            "/lists", headers=self.headers, json={"title": "Private list", "is_public": False}
        ).json()
        with self.Session() as db:
            other = User(username="other", password_hash="hashed")
            db.add(other)
            db.commit()
            db.refresh(other)
            headers = {"Authorization": "Bearer " + create_access_token(other.id, other.username)}
        for method, path, kwargs in [
            ("get", f"/lists/{data['id']}", {}),
            ("patch", f"/lists/{data['id']}", {"json": {"title": "Stolen list"}}),
            ("delete", f"/lists/{data['id']}", {}),
        ]:
            self.assertEqual(getattr(self.client, method)(path, headers=headers, **kwargs).status_code, 404)

    def test_private_list_owner_manage_nonowner_and_summary(self):
        data = self.client.post(
            "/lists", headers=self.headers, json={"title": "Private list", "is_public": False}
        ).json()
        response = self.client.get(f"/lists/{data['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(
            f"/lists/{data['id']}", headers=self.headers, json={"title": "Updated title", "description": None}
        )
        self.assertEqual(response.json()["title"], "Updated title")
        self.assertEqual(self.client.get(f"/lists/share/{data['share_slug']}").status_code, 404)
        summary = self.client.get("/lists/my", headers=self.headers).json()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["lists"][0]["items"], [])


class MigrationIntegrityTests(unittest.TestCase):
    def test_in_memory_sqlite_schema_is_shared_with_request_threads(self):
        with patch.object(database, "settings", SimpleNamespace(database_url="sqlite://")):
            engine = database._get_engine()
        try:
            database.create_tables(engine)

            def read_schema():
                with engine.connect() as connection:
                    return connection.execute(text("SELECT COUNT(*) FROM users")).scalar()

            with ThreadPoolExecutor(max_workers=1) as workers:
                self.assertEqual(workers.submit(read_schema).result(), 0)
        finally:
            engine.dispose()

    def test_first_pooled_connection_has_sqlite_pragmas(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                database, "settings", SimpleNamespace(database_url=f"sqlite:///{Path(directory) / 'test.db'}")
            ):
                engine = database._get_engine()
            try:
                for _ in range(2):
                    with engine.connect() as connection:
                        self.assertEqual(connection.execute(text("PRAGMA foreign_keys")).scalar(), 1)
                        self.assertEqual(connection.execute(text("PRAGMA journal_mode")).scalar(), "wal")
            finally:
                engine.dispose()

    def test_legacy_migration_preserves_entries_backups_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            engine = create_engine(f"sqlite:///{path}")
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL)")
                    )
                    connection.execute(text("INSERT INTO users VALUES (1, 'legacy')"))
                    connection.execute(
                        text(
                            "CREATE TABLE watch_history (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL, movie_title VARCHAR(300) NOT NULL)"
                        )
                    )
                    connection.execute(text("INSERT INTO watch_history VALUES (1,1,123,'Preserved title')"))
                database.create_tables(engine)
                database.create_tables(engine)
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.execute(text("SELECT movie_title FROM watch_history")).scalar(),
                        "Preserved title",
                    )
                    self.assertEqual(
                        connection.execute(text("SELECT session_version FROM users")).scalar(), 0
                    )
                    self.assertEqual(
                        connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar(), 1
                    )
                from sqlalchemy.exc import IntegrityError

                with self.assertRaises(IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            text(
                                "INSERT INTO watch_history (user_id,movie_id,movie_title) VALUES (999,456,'Orphan')"
                            )
                        )
                self.assertEqual(len(list(Path(directory).glob("*.bak"))), 1)
                from sqlalchemy.exc import IntegrityError

                with self.assertRaises(IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(
                            text("INSERT INTO users (username,password_hash) VALUES ('legacy','hashed')")
                        )
                backup = create_engine(f"sqlite:///{next(Path(directory).glob('*.bak'))}")
                with backup.connect() as connection:
                    self.assertEqual(
                        connection.execute(text("SELECT movie_title FROM watch_history")).scalar(),
                        "Preserved title",
                    )
                backup.dispose()
            finally:
                engine.dispose()

    def test_transaction_failure_rolls_back_and_next_request_can_write(self):
        from fastapi import HTTPException
        from sqlalchemy.exc import IntegrityError

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        try:
            with Session() as db:
                db.add(User(username="duplicate", password_hash="hashed"))
                db.commit()
            with patch.object(database, "SessionLocal", Session):
                dependency = database.get_db()
                db = next(dependency)
                db.add(User(username="duplicate", password_hash="hashed"))
                try:
                    db.commit()
                except IntegrityError as error:
                    with self.assertRaises(HTTPException) as caught:
                        dependency.throw(error)
                    self.assertEqual(caught.exception.status_code, 409)
                dependency = database.get_db()
                db = next(dependency)
                db.add(User(username="next-request", password_hash="hashed"))
                db.commit()
                dependency.close()
            with Session() as db:
                self.assertEqual(db.query(User).count(), 2)
        finally:
            engine.dispose()

    def test_postgres_date_columns_compile_using_timestamp_type(self):
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateColumn

        sql = str(CreateColumn(WatchHistory.__table__.c.watched_at).compile(dialect=postgresql.dialect()))
        self.assertIn("TIMESTAMP WITH TIME ZONE", sql)
        self.assertNotIn("DATETIME", sql)


class LibraryRaceTests(unittest.TestCase):
    def test_parallel_watched_and_bookmark_writes_never_overlap(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                database, "settings", SimpleNamespace(database_url=f"sqlite:///{Path(directory) / 'race.db'}")
            ):
                engine = database._get_engine()
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            with Session() as db:
                user = User(username="race-user", password_hash="hashed")
                db.add(user)
                db.commit()
                db.refresh(user)
                user_id = user.id
                headers = {"Authorization": "Bearer " + create_access_token(user.id, user.username)}
            main.app.state.catalog = SimpleNamespace(
                get_movie=lambda _: {
                    "id": 1,
                    "title": "Canonical",
                    "genres": ["Drama"],
                    "vote_average": 7,
                    "poster_path": "",
                }
            )
            main.app.dependency_overrides[get_db] = database.get_db
            try:
                with patch.object(database, "SessionLocal", Session):
                    client = TestClient(main.app)
                    for _ in range(3):
                        with Session() as db:
                            db.query(WatchHistory).delete()
                            db.query(Watchlist).delete()
                            db.commit()
                        barrier = threading.Barrier(2)

                        def write(path, gate=barrier):
                            gate.wait(timeout=3)
                            return client.post(
                                path, headers=headers, json={"movie_id": 1, "movie_title": "Title"}
                            ).status_code

                        with ThreadPoolExecutor(max_workers=2) as workers:
                            futures = [workers.submit(write, path) for path in ("/watched", "/watchlist")]
                            statuses = [future.result(timeout=10) for future in futures]
                        self.assertTrue(all(code in (200, 409, 503) for code in statuses), statuses)
                        self.assertIn(200, statuses)
                        with Session() as db:
                            watched = db.query(WatchHistory).filter_by(user_id=user_id, movie_id=1).count()
                            watchlisted = db.query(Watchlist).filter_by(user_id=user_id, movie_id=1).count()
                            self.assertLessEqual(watched + watchlisted, 1)
                    client.close()
            finally:
                main.app.dependency_overrides.clear()
                engine.dispose()
