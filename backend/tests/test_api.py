from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DB_PATH = Path(tempfile.gettempdir()) / "cinematch-test.db"

os.environ["CINEMATCH_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["CINEMATCH_SECRET_KEY"] = "cinematch-test-secret-key"
os.environ["CINEMATCH_ENABLE_POSTER_LOOKUP"] = "0"

import sys

sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from backend.database import engine
from backend.main import app


class CineMatchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{TEST_DB_PATH}{suffix}")
            if candidate.exists():
                candidate.unlink()

        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{TEST_DB_PATH}{suffix}")
            if candidate.exists():
                candidate.unlink()

    def make_username(self) -> str:
        return f"user_{uuid4().hex[:10]}"

    def signup(self, genres: list[str] | None = None) -> dict:
        username = self.make_username()
        response = self.client.post(
            "/auth/signup",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": "strongpass123",
                "genres": genres or ["Drama", "Science Fiction"],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_health_and_catalog_stats(self) -> None:
        health_response = self.client.get("/health")
        self.assertEqual(health_response.status_code, 200)
        health_payload = health_response.json()
        self.assertEqual(health_payload["status"], "ok")
        self.assertGreater(health_payload["catalog"]["total_movies"], 4000)

        stats_response = self.client.get("/stats/catalog")
        self.assertEqual(stats_response.status_code, 200)
        self.assertIn("average_rating", stats_response.json())

    def test_signup_login_and_profile(self) -> None:
        signup_payload = self.signup()

        login_response = self.client.post(
            "/auth/login",
            json={"username": signup_payload["username"], "password": "strongpass123"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        login_payload = login_response.json()
        self.assertIn("access_token", login_payload)

        profile_response = self.client.get(
            "/auth/me",
            headers=self.auth_headers(login_payload["access_token"]),
        )
        self.assertEqual(profile_response.status_code, 200, profile_response.text)
        profile_payload = profile_response.json()
        self.assertEqual(profile_payload["username"], signup_payload["username"])
        self.assertEqual(profile_payload["genres"], ["Drama", "Science Fiction"])

    def test_personalized_recommendations_after_signup(self) -> None:
        signup_payload = self.signup(["Action", "Thriller"])
        response = self.client.get(
            "/recommend/for-me?top_n=6",
            headers=self.auth_headers(signup_payload["access_token"]),
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreater(payload["count"], 0)
        self.assertIn(payload["strategy"], {"genre_based", "hybrid", "content_based", "popular"})

    def test_watch_history_crud_flow(self) -> None:
        signup_payload = self.signup()
        headers = self.auth_headers(signup_payload["access_token"])

        search_response = self.client.get("/search?q=matrix&limit=1")
        self.assertEqual(search_response.status_code, 200, search_response.text)
        movie = search_response.json()["movies"][0]

        add_response = self.client.post(
            "/watched",
            headers=headers,
            json={
                "movie_id": movie["id"],
                "movie_title": movie["title"],
                "poster_path": movie.get("poster_path", ""),
                "genres": ", ".join(movie.get("genres", [])),
                "vote_average": movie.get("vote_average"),
            },
        )
        self.assertEqual(add_response.status_code, 201, add_response.text)
        entry = add_response.json()["entry"]

        update_response = self.client.patch(
            f"/watched/{entry['id']}",
            headers=headers,
            json={"rating": 4, "notes": "Still holds up."},
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(update_response.json()["entry"]["rating"], 4.0)

        library_response = self.client.get("/watched", headers=headers)
        self.assertEqual(library_response.status_code, 200, library_response.text)
        self.assertEqual(library_response.json()["total"], 1)

        recommend_response = self.client.post(
            "/recommend/history",
            json={"movie_ids": [movie["id"]], "top_n": 5},
        )
        self.assertEqual(recommend_response.status_code, 200, recommend_response.text)
        self.assertGreater(recommend_response.json()["count"], 0)

        delete_response = self.client.delete(f"/watched/entry/{entry['id']}", headers=headers)
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertIn("Removed", delete_response.json()["message"])


if __name__ == "__main__":
    unittest.main()
