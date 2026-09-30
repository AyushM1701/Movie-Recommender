from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CINEMATCH_ENABLE_POSTER_LOOKUP", "0")

from backend.evaluate_recommender import evaluate_catalog, evaluate_comparison
from backend.tests.recommender_fixtures import make_engine


class RecommenderRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = make_engine()

    def tearDown(self) -> None:
        self.engine.close()

    def test_theme_search_is_numeric_and_only_returns_content_matches(self) -> None:
        result = self.engine.search_movies("time travel thriller", limit=12)
        self.assertEqual(result["match_type"], "theme_genre_match")
        self.assertGreater(result["count"], 0)
        self.assertIn(27205, [movie["id"] for movie in result["movies"]])

    def test_unknown_query_does_not_claim_a_theme_match(self) -> None:
        result = self.engine.search_movies("zzzzxyqfoobar")
        self.assertEqual(result["match_type"], "no_match")
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["exact_match"])

    def test_partial_title_is_not_an_exact_match(self) -> None:
        self.assertFalse(self.engine.search_movies("Godfat")["exact_match"])
        self.assertTrue(self.engine.search_movies("The Godfather")["exact_match"])

    def test_runtime_metadata_from_csv_float_strings_is_normalized(self) -> None:
        self.engine.movies["runtime"] = self.engine.movies["runtime"].astype(object)
        self.engine.movies.loc[0, "runtime"] = "94.0"
        self.assertEqual(self.engine.get_movie_by_id(27205)["runtime"], 94)

    def test_title_search_and_details_include_catalog_only_movies(self) -> None:
        record = {"id": 987654, "title": "New Documentary", "poster_path": "", "genres": []}
        repository = unittest.mock.Mock()
        repository.search_titles.return_value = [record]
        repository.get_movie.return_value = record
        repository.stats.return_value = {"total_movies": 13}
        self.engine.catalog_repository = repository
        result = self.engine.search_movies("New Documentary")
        self.assertEqual(result["movies"], [record])
        self.assertTrue(result["exact_match"])
        self.assertEqual(self.engine.get_movie_by_id(987654), record)
        self.assertEqual(self.engine.get_catalog_stats()["total_movies"], 13)

    def test_evaluation_compares_same_sample_against_simple_baselines(self) -> None:
        report = evaluate_comparison(self.engine, sample_size=3, top_k=2, seed=42)
        self.assertEqual(set(report), {"hybrid", "popularity", "genre"})
        for metrics in report.values():
            self.assertEqual(metrics["sample_movies"], 3)
            self.assertEqual(metrics["evaluation_type"], "attribute_proxy_not_human_relevance")
        self.assertEqual(report, evaluate_comparison(self.engine, sample_size=3, top_k=2, seed=42))

    def test_explicit_thresholds_are_never_relaxed(self) -> None:
        self.assertEqual(self.engine.recommend_by_genres(["Drama"], min_rating=10, min_votes=1_000_000), [])
        result = self.engine.recommend_by_genres(["Science Fiction"], top_n=10, min_rating=8, min_votes=1000)
        self.assertEqual([movie["id"] for movie in result], [27205])

    def test_negative_only_history_respects_watched_exclusion_in_all_fallbacks(self) -> None:
        ids = [movie["id"] for movie in self.engine.recommend_popular(top_n=10)]
        for genres in ([], ["Drama"]):
            result = self.engine.recommend_for_user(ids, genres, top_n=10, ratings={i: 1 for i in ids})
            self.assertFalse(set(ids) & {movie["id"] for movie in result[2]})

    def test_negative_only_profile_demotes_similar_unwatched_content(self) -> None:
        self.engine._quality_scores[:] = 0.75
        self.engine._popularity_scores[:] = 0.5
        self.engine._novelty_scores[:] = 0.5
        result = self.engine.recommend_for_user([27205], [], top_n=10, ratings={27205: 1})
        ids = [movie["id"] for movie in result[2]]
        self.assertNotIn(27205, ids)
        self.assertIn(238, ids)
        self.assertGreater(ids.index(1002) if 1002 in ids else len(ids), ids.index(238))
        self.assertIn("dislike", result[1].lower())

    def test_complete_exclusions_are_independent_of_profile_sample(self) -> None:
        result = self.engine.recommend_for_user([157336], [], excluded_movie_ids=[27205, 1002, 157336, 1004])
        self.assertFalse({27205, 1002, 157336, 1004} & {movie["id"] for movie in result[2]})

    def test_genre_only_hybrid_has_no_phantom_content_signal(self) -> None:
        result = self.engine.recommend_hybrid([], ["Crime"], top_n=12)
        self.assertGreater(len(result), 0)
        self.assertTrue(all("Crime" in movie["genres"] for movie in result))

    def test_seed_only_hybrid_ignores_unused_genre_weight(self) -> None:
        one = self.engine.recommend_hybrid([27205], [], top_n=8, weight_content=0.7, weight_genre=0.3)
        two = self.engine.recommend_hybrid([27205], [], top_n=8, weight_content=1, weight_genre=0)
        self.assertEqual(one, two)
        self.assertNotIn(27205, [movie["id"] for movie in one])

    def test_recall_uses_all_relevant_candidates_not_k(self) -> None:
        self.engine.movies["genres_list"] = [["Drama"] for _ in range(len(self.engine.movies))]
        self.engine.movies["keywords_list"] = [[] for _ in range(len(self.engine.movies))]
        with patch.object(self.engine, "get_similar_movies", return_value=[{"id": 27205}]):
            report = evaluate_catalog(self.engine, sample_size=1, top_k=1, seed=42)
        self.assertEqual(report["attribute_recall_at_k"], round(1 / (len(self.engine.movies) - 1), 4))
        self.assertEqual(report["attribute_precision_at_k"], 1)
        self.assertIn("proxy", report["evaluation_type"])

    def test_old_films_are_present_in_explore_archive(self) -> None:
        result = self.engine.get_explore_catalog()
        self.assertIn("Before 1970", result["by_decade"])
        self.assertIn(1012, [movie["id"] for movie in result["by_decade"]["Before 1970"]])


if __name__ == "__main__":
    unittest.main()
