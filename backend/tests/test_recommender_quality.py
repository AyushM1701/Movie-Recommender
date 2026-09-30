from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("CINEMATCH_ENABLE_POSTER_LOOKUP", "0")

from backend.tests.recommender_fixtures import make_engine  # noqa: E402


class RecommendationQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = make_engine()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.close()

    def movie_id(self, title: str) -> int:
        matches = self.engine.movies[self.engine.movies["title"].str.casefold() == title.casefold()]
        self.assertFalse(matches.empty, f"Missing quality-test seed: {title}")
        return int(matches.iloc[0]["id"])

    def test_artifacts_are_aligned_and_normalized(self) -> None:
        self.assertEqual(len(self.engine.movies), self.engine.tfidf_matrix.shape[0])
        norms = np.sqrt(self.engine.tfidf_matrix.multiply(self.engine.tfidf_matrix).sum(axis=1)).A1
        self.assertTrue(np.allclose(norms, 1.0, atol=1e-4))
        if self.engine.semantic_embeddings is not None:
            self.assertEqual(len(self.engine.movies), self.engine.semantic_embeddings.shape[0])
            semantic_norms = np.linalg.norm(np.asarray(self.engine.semantic_embeddings), axis=1)
            self.assertTrue(np.allclose(semantic_norms, 1.0, atol=1e-3))

    def test_golden_franchise_neighbours(self) -> None:
        cases = {
            "The Dark Knight": ("batman", "dark knight"),
            "The Godfather": ("godfather",),
            "Toy Story": ("toy story",),
        }
        for seed, expected_terms in cases.items():
            recommendations = self.engine.get_similar_movies(self.movie_id(seed), top_n=10)
            titles = " | ".join(item["title"].casefold() for item in recommendations)
            self.assertTrue(
                any(term in titles for term in expected_terms),
                f"Expected a known neighbour for {seed}; received {titles}",
            )

    def test_personalized_ranking_is_deterministic_and_rating_aware(self) -> None:
        interstellar = self.movie_id("Interstellar")
        godfather = self.movie_id("The Godfather")
        first = self.engine.recommend_for_user(
            [interstellar, godfather],
            [],
            top_n=8,
            ratings={interstellar: 5.0, godfather: 1.0},
        )[2]
        repeated = self.engine.recommend_for_user(
            [interstellar, godfather],
            [],
            top_n=8,
            ratings={interstellar: 5.0, godfather: 1.0},
        )[2]
        reversed_preferences = self.engine.recommend_for_user(
            [interstellar, godfather],
            [],
            top_n=8,
            ratings={interstellar: 1.0, godfather: 5.0},
        )[2]
        first_ids = [item["id"] for item in first]
        self.assertEqual(first_ids, [item["id"] for item in repeated])
        self.assertNotEqual(first_ids, [item["id"] for item in reversed_preferences])
        self.assertNotIn(interstellar, first_ids)
        self.assertNotIn(godfather, first_ids)


if __name__ == "__main__":
    unittest.main()
