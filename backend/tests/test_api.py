from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DB_PATH = Path(tempfile.gettempdir()) / f"cinematch-test-{uuid4().hex[:8]}.db"

os.environ["CINEMATCH_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["CINEMATCH_SECRET_KEY"] = "cinematch-test-secret-key"
os.environ["CINEMATCH_ENABLE_POSTER_LOOKUP"] = "0"
os.environ["TMDB_API_KEY"] = ""

sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from backend.database import engine
from backend.main import app
from backend.tests.recommender_fixtures import FixtureCatalog, make_engine


class CineMatchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model_patch = patch("backend.main.RecommendationEngine", side_effect=make_engine)
        cls.model_patch.start()
        cls.catalog_patch = patch("backend.catalog.CatalogRepository", side_effect=FixtureCatalog)
        cls.catalog_patch.start()
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        cls.model_patch.stop()
        cls.catalog_patch.stop()
        engine.dispose()
        try:
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(f"{TEST_DB_PATH}{suffix}")
                if candidate.exists():
                    candidate.unlink(missing_ok=True)
        except Exception:
            pass

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
        payload = response.json()
        payload["password"] = "strongpass123"
        return payload

    def auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_health_and_catalog_stats(self) -> None:
        health_resp = self.client.get("/health")
        self.assertEqual(health_resp.status_code, 200)
        health_data = health_resp.json()
        self.assertEqual(health_data["status"], "healthy")
        self.assertGreater(health_data["catalog"]["total_movies"], 0)

    def test_readiness_rejects_unusable_catalog(self) -> None:
        with patch.object(
            self.client.app.state.catalog, "stats", side_effect=RuntimeError("Missing catalog")
        ):
            result = self.client.get("/ready")
            self.assertEqual(result.status_code, 503)

    def test_explore_catalog(self) -> None:
        resp = self.client.get("/explore")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("trending", data)
        self.assertIn("top_rated", data)
        self.assertIn("by_decade", data)
        self.assertGreater(len(data["trending"]), 0)
        self.assertGreater(len(data["top_rated"]), 0)

    def test_movie_details_and_similar(self) -> None:
        explore_resp = self.client.get("/explore")
        movie_id = explore_resp.json()["trending"][0]["id"]

        details_resp = self.client.get(f"/movies/{movie_id}/details")
        self.assertEqual(details_resp.status_code, 200)
        details = details_resp.json()
        self.assertEqual(details["id"], movie_id)
        self.assertIn("similar_movies", details)
        self.assertIn("cast", details)

        sim_resp = self.client.get(f"/movies/{movie_id}/similar?top_n=4")
        self.assertEqual(sim_resp.status_code, 200)
        self.assertLessEqual(len(sim_resp.json()), 4)

    def test_history_hybrid_and_personal_recommendations(self) -> None:
        user_info = self.signup(genres=["Action", "Science Fiction"])
        headers = self.auth_headers(user_info["access_token"])

        history_resp = self.client.post(
            "/recommend/history",
            json={"movie_ids": [27205], "top_n": 4},
        )
        self.assertEqual(history_resp.status_code, 200, history_resp.text)
        self.assertGreater(len(history_resp.json()["movies"]), 0)
        self.assertIn("similarity_score", history_resp.json()["movies"][0])

        hybrid_resp = self.client.post(
            "/recommend/hybrid",
            json={"movie_ids": [27205], "genres": ["Action"], "top_n": 4},
        )
        self.assertEqual(hybrid_resp.status_code, 200, hybrid_resp.text)
        self.assertGreater(len(hybrid_resp.json()["movies"]), 0)

        self.client.post(
            "/watched",
            headers=headers,
            json={"movie_id": 27205, "movie_title": "Inception", "rating": 5},
        )
        personal_resp = self.client.get("/recommend/me", headers=headers)
        self.assertEqual(personal_resp.status_code, 200, personal_resp.text)
        self.assertGreater(len(personal_resp.json()["movies"]), 0)

    def test_negative_only_history_returns_personal_recommendations(self) -> None:
        user_info = self.signup()
        headers = self.auth_headers(user_info["access_token"])
        response = self.client.post(
            "/watched", headers=headers, json={"movie_id": 27205, "movie_title": "Inception", "rating": 1}
        )
        self.assertEqual(response.status_code, 200)
        result = self.client.get("/recommend/me", headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["strategy"], "personalized_negative_profile")
        self.assertNotIn(27205, [movie["id"] for movie in result.json()["movies"]])

    def test_manual_blend_does_not_silently_drop_seed_signals(self) -> None:
        result = self.client.post(
            "/recommend/hybrid",
            json={"movie_ids": [999999], "genres": ["Drama"], "weight_content": 0.7, "weight_genre": 0.3},
        )
        self.assertEqual(result.status_code, 422)
        self.assertIn("recommendation features", result.json()["detail"])

    def test_signup_login_and_profile(self) -> None:
        user_info = self.signup(genres=["Action", "Thriller"])
        token = user_info["access_token"]
        headers = self.auth_headers(token)

        login_resp = self.client.post(
            "/auth/login",
            json={
                "username": user_info["username"],
                "password": user_info["password"],
            },
        )
        self.assertEqual(login_resp.status_code, 200)

        me_resp = self.client.get("/auth/me", headers=headers)
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["username"], user_info["username"])

    def test_watchlist_and_move_to_watched(self) -> None:
        user_info = self.signup()
        headers = self.auth_headers(user_info["access_token"])

        # Add to watchlist
        add_w = self.client.post(
            "/watchlist",
            headers=headers,
            json={
                "movie_id": 19995,
                "movie_title": "Avatar",
                "genres": "Action, Adventure, Fantasy",
                "vote_average": 7.2,
            },
        )
        self.assertEqual(add_w.status_code, 200)

        # Get watchlist
        w_list = self.client.get("/watchlist", headers=headers)
        self.assertEqual(w_list.status_code, 200)
        self.assertEqual(w_list.json()["total"], 1)

        # Move to watched
        move_resp = self.client.post("/watchlist/19995/watched", headers=headers)
        self.assertEqual(move_resp.status_code, 200)

        # Watchlist should now be 0
        w_list2 = self.client.get("/watchlist", headers=headers)
        self.assertEqual(w_list2.json()["total"], 0)

        # Watched library should have 1 item
        watched_resp = self.client.get("/watched", headers=headers)
        self.assertEqual(watched_resp.json()["total"], 1)

    def test_library_rejects_invalid_poster_and_missing_watchlist_move(self) -> None:
        user_info = self.signup()
        headers = self.auth_headers(user_info["access_token"])

        invalid_poster = self.client.post(
            "/watchlist",
            headers=headers,
            json={
                "movie_id": 27205,
                "movie_title": "Inception",
                "poster_path": 'x" onerror="alert(1)',
            },
        )
        self.assertEqual(invalid_poster.status_code, 422)

        missing_move = self.client.post("/watchlist/999999/watched", headers=headers)
        self.assertEqual(missing_move.status_code, 404)

    def test_custom_lists_and_public_sharing(self) -> None:
        user_info = self.signup()
        headers = self.auth_headers(user_info["access_token"])

        # Create list
        create_resp = self.client.post(
            "/lists",
            headers=headers,
            json={
                "title": "My Favorite Sci-Fi",
                "description": "The best sci-fi movies of all time",
                "is_public": True,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        list_data = create_resp.json()
        list_id = list_data["id"]
        share_slug = list_data["share_slug"]

        # Add item to list
        add_item_resp = self.client.post(
            f"/lists/{list_id}/items",
            headers=headers,
            json={
                "movie_id": 157336,
                "movie_title": "Interstellar",
                "genres": "Adventure, Drama, Science Fiction",
                "vote_average": 8.1,
            },
        )
        self.assertEqual(add_item_resp.status_code, 200)

        # Public share endpoint (NO auth required)
        public_resp = self.client.get(f"/lists/share/{share_slug}")
        self.assertEqual(public_resp.status_code, 200)
        public_data = public_resp.json()
        self.assertEqual(public_data["title"], "My Favorite Sci-Fi")
        self.assertEqual(len(public_data["items"]), 1)

    def test_library_export(self) -> None:
        user_info = self.signup()
        headers = self.auth_headers(user_info["access_token"])

        # Add a watched movie
        self.client.post(
            "/watched",
            headers=headers,
            json={
                "movie_id": 27205,
                "movie_title": "Inception",
                "genres": "Action, Sci-Fi",
                "vote_average": 8.1,
                "rating": 5.0,
                "notes": "Masterpiece",
            },
        )

        # Export JSON
        json_resp = self.client.get("/library/export?format=json", headers=headers)
        self.assertEqual(json_resp.status_code, 200)
        self.assertEqual(json_resp.headers["content-type"], "application/json")
        export_json = json_resp.json()
        self.assertEqual(export_json["total_watched"], 1)

        # Export CSV
        csv_resp = self.client.get("/library/export?format=csv", headers=headers)
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp.headers["content-type"])
        self.assertIn("Inception", csv_resp.text)


if __name__ == "__main__":
    unittest.main()
