"""Run only against an explicitly supplied disposable PostgreSQL service."""

import os
import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend import database, main
from backend.auth import create_access_token, hash_password
from backend.database import User, Watchlist, get_db


@unittest.skipUnless(
    os.getenv("CINEMATCH_TEST_POSTGRES_URL"), "No explicit disposable PostgreSQL test service."
)
class PostgresMigrationTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["CINEMATCH_TEST_POSTGRES_URL"]
        self.schema = "cinematch_test_" + uuid4().hex
        self.admin = create_engine(self.url, pool_pre_ping=True)
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(
            self.url, connect_args={"options": f"-csearch_path={self.schema}"}, pool_pre_ping=True
        )

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.engine.dispose()
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin.dispose()

    def test_fresh_schema_auth_nullable_patch_and_foreign_keys(self):
        database.create_tables(self.engine)
        database.create_tables(self.engine)
        Session = sessionmaker(bind=self.engine)
        with Session() as db:
            user = User(username="pg-user", password_hash=hash_password("oldpassword"))
            db.add(user)
            db.commit()
            db.refresh(user)
            headers = {
                "Authorization": "Bearer " + create_access_token(user.id, user.username, user.session_version)
            }

        def dependency():
            with Session() as db:
                yield db

        main.app.dependency_overrides[get_db] = dependency
        main.app.state.catalog = SimpleNamespace(
            get_movie=lambda _: {
                "id": 1,
                "title": "Postgres movie",
                "genres": ["Drama"],
                "vote_average": 7,
                "poster_path": "",
            }
        )
        client = TestClient(main.app)
        try:
            from backend.rate_limiter import limiter

            with limiter._lock:
                limiter._history.clear()
            entry = client.post(
                "/watched",
                headers=headers,
                json={"movie_id": 1, "movie_title": "Forged", "rating": 4, "notes": "Clear"},
            ).json()["entry"]
            self.assertEqual(entry["movie_title"], "Postgres movie")
            result = client.patch(
                f"/watched/{entry['id']}", headers=headers, json={"rating": None, "notes": None}
            )
            self.assertIsNone(result.json()["entry"]["rating"])
            self.assertIsNone(result.json()["entry"]["notes"])
            self.assertEqual(
                client.put(
                    "/auth/password",
                    headers=headers,
                    json={"current_password": "oldpassword", "new_password": "newpassword"},
                ).status_code,
                200,
            )
            self.assertEqual(client.get("/auth/me", headers=headers).status_code, 401)
        finally:
            client.close()
        with Session() as db:
            db.add(Watchlist(user_id=999, movie_id=2, movie_title="Orphan"))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar(), 1)
            self.assertIn("PostgreSQL 17", connection.execute(text("SELECT version()")).scalar())

    def test_legacy_schema_preserves_saved_entries_and_constraints(self):
        with self.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(50) NOT NULL)")
            )
            connection.execute(text("INSERT INTO users (username) VALUES ('legacy')"))
            connection.execute(
                text(
                    "CREATE TABLE watch_history (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL, movie_title VARCHAR(300) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO watch_history (user_id,movie_id,movie_title) VALUES (1,123,'Preserved title')"
                )
            )
        database.create_tables(self.engine)
        database.create_tables(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT movie_title FROM watch_history")).scalar(), "Preserved title"
            )
            self.assertEqual(connection.execute(text("SELECT session_version FROM users")).scalar(), 0)
            self.assertIsNotNone(connection.execute(text("SELECT watched_at FROM watch_history")).scalar())
        self.assertTrue(inspect(self.engine).get_foreign_keys("watch_history"))
        for statement in (
            "INSERT INTO users (username) VALUES ('legacy')",
            "INSERT INTO watch_history (user_id,movie_id,movie_title) VALUES (999,999,'Orphan')",
            "INSERT INTO watch_history (user_id,movie_id,movie_title) VALUES (1,123,'Duplicate')",
        ):
            with self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(text(statement))
