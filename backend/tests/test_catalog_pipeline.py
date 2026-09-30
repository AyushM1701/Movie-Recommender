"""Data contracts use disposable sources and a deterministic network boundary."""

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class CatalogPipelineTests(unittest.TestCase):
    def test_discovery_walks_all_pages_deduplicates_and_splits_overflow(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")
        self.assertTrue(hasattr(refresh, "discover_movies"), "Exhaustive discovery is missing")

        def get(endpoint, **params):
            start, end, page = (
                params["primary_release_date.gte"],
                params["primary_release_date.lte"],
                params["page"],
            )
            if start != end:
                return {"total_pages": 501, "total_results": 10001, "results": []}
            rows = [{"id": page, "release_date": start, "title": f"Film {page}"}]
            return {"total_pages": 2, "total_results": 2, "results": rows}

        rows, coverage = refresh.discover_movies(get, "2026-09-01", "2026-09-02")
        self.assertEqual(set(rows), {1, 2})
        self.assertEqual(len(coverage["windows"]), 2)
        self.assertTrue(coverage["discovery_complete"])

    def test_failed_refresh_preserves_previous_supplement(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")
        self.assertTrue(hasattr(refresh, "run_refresh"), "Safe publication is missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "tmdb_latest_movies.csv"
            old.write_text("id,title\n1,Preserved\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                refresh.run_refresh(root, "2026-09-01", "2026-09-02", get=lambda *a, **k: None)
            self.assertEqual(old.read_text(), "id,title\n1,Preserved\n")
            self.assertFalse((root / "refresh_active.json").exists())

    def test_page_duplicates_are_reconciled_in_smaller_date_windows(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")

        def get(endpoint, **params):
            start, end = (
                params["primary_release_date.gte"],
                params["primary_release_date.lte"],
            )
            if start != end:
                return {"total_pages": 2, "total_results": 2, "results": [{"id": 1, "release_date": start}]}
            movie_id = 1 if start == "2026-09-01" else 2
            return {
                "total_pages": 1,
                "total_results": 1,
                "results": [{"id": movie_id, "release_date": start}],
            }

        rows, coverage = refresh.discover_movies(get, "2026-09-01", "2026-09-02")
        self.assertEqual(set(rows), {1, 2})
        self.assertTrue(coverage["discovery_complete"])

    def test_single_day_pagination_duplicates_reconcile_with_independent_sort(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")

        def get(endpoint, **params):
            movie_id = 2 if params["sort_by"] == "popularity.desc" else 1
            return {
                "total_pages": 2,
                "total_results": 2,
                "results": [{"id": movie_id, "release_date": "2026-09-01"}],
            }

        rows, coverage = refresh.discover_movies(get, "2026-09-01", "2026-09-01")
        self.assertEqual(set(rows), {1, 2})
        self.assertTrue(coverage["discovery_complete"])

    def test_catalog_retains_unrated_incomplete_recent_rows_and_browses_history(self):
        self.assertIsNotNone(importlib.util.find_spec("backend.catalog"), "Indexed catalog is missing")
        catalog = importlib.import_module("backend.catalog")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            rows = pd.DataFrame(
                [
                    {
                        "id": 1,
                        "title": "Recent Unrated",
                        "release_date": "2026-09-10",
                        "vote_count": 0,
                        "overview": "",
                        "genres": "",
                    },
                    {
                        "id": 2,
                        "title": "Old Film",
                        "release_date": "1930-01-01",
                        "genres": "Drama",
                        "vote_count": 500,
                    },
                ]
            )
            catalog.publish_catalog(rows, path, {"cutoff": "2026-09-30"})
            repo = catalog.CatalogRepository(path)
            self.assertEqual(repo.search_titles("recent")[0]["id"], 1)
            self.assertEqual(repo.get_movie(1)["genres"], [])
            self.assertEqual(repo.browse(year_to=1969)["movies"][0]["id"], 2)
            self.assertEqual(repo.stats()["total_movies"], 2)
            self.assertEqual(repo.metadata()["cutoff"], "2026-09-30")

    def test_catalog_rating_filter_applies_before_global_pagination(self):
        catalog = importlib.import_module("backend.catalog")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            rows = pd.DataFrame(
                [
                    {"id": i, "title": f"Film {i}", "vote_average": rating, "popularity": 100 - i}
                    for i, rating in ((1, 5), (2, 8.5), (3, 9))
                ]
            )
            catalog.publish_catalog(rows, path, {"cutoff": "2026-09-30"})
            result = catalog.CatalogRepository(path).browse(page=1, page_size=1, min_rating=8)
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["movies"][0]["id"], 2)

    def test_historical_and_supplement_credits_merge_without_erasing_good_data(self):
        source = importlib.import_module("backend.data_preprocessing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame(
                [{"id": 1, "title": "Historic", "vote_count": 500, "overview": "plot", "genres": "Drama"}]
            ).to_csv(root / "tmdb_5000_movies.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "movie_id": 1,
                        "cast": json.dumps([{"name": "Known Actor"}]),
                        "crew": json.dumps([{"name": "Known Director", "job": "Director"}]),
                    }
                ]
            ).to_csv(root / "tmdb_5000_credits.csv", index=False)
            pd.DataFrame([{"movie_id": 1, "cast": "[]", "crew": "[]"}]).to_csv(
                root / "tmdb_latest_credits.csv", index=False
            )
            with patch.object(source, "DATA_DIR", root):
                rows = source.load_movie_source()
            self.assertEqual(rows.iloc[0]["cast_list"], ["Known Actor"])
            self.assertEqual(rows.iloc[0]["director_list"], ["Known Director"])

    def test_small_offline_build_publishes_validated_generation_and_catalog(self):
        source = importlib.import_module("backend.data_preprocessing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, models = root / "data", root / "models"
            data.mkdir()
            pd.DataFrame(
                [
                    {
                        "id": 1,
                        "title": "Historical",
                        "vote_count": 500,
                        "overview": "space journey friendship",
                        "genres": "Drama",
                        "release_date": "1930-01-01",
                    },
                    {
                        "id": 2,
                        "title": "Recent New",
                        "vote_count": 0,
                        "overview": "space journey mystery",
                        "genres": "Drama",
                        "release_date": "2026-09-01",
                    },
                    {
                        "id": 3,
                        "title": "Recent Empty",
                        "vote_count": 0,
                        "overview": "",
                        "genres": "",
                        "release_date": "2026-09-02",
                    },
                    {
                        "id": 4,
                        "title": "Empty Arrays",
                        "vote_count": 0,
                        "overview": "",
                        "genres": "[]",
                        "keywords": "[]",
                        "release_date": "2026-09-02",
                    },
                ]
            ).to_csv(data / "tmdb_5000_movies.csv", index=False)
            with patch.object(source, "DATA_DIR", data), patch.object(source, "MODEL_DIR", models):
                movies, _ = source.load_and_preprocess()
            self.assertEqual(set(movies["id"]), {1, 2})
            self.assertTrue(
                (models / "active.json").exists(), "Build must atomically activate a complete generation"
            )
            self.assertTrue((data / "catalog_seed_v1.csv.gz").exists())
            catalog = importlib.import_module("backend.catalog")
            self.assertEqual(
                catalog.CatalogRepository(data / "catalog.sqlite3").get_movie(3)["title"], "Recent Empty"
            )

    def test_failed_model_build_preserves_active_pair_and_delivered_seed(self):
        source = importlib.import_module("backend.data_preprocessing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, models = root / "data", root / "models"
            data.mkdir()
            movies = pd.DataFrame(
                [
                    {
                        "id": 1,
                        "title": "A",
                        "vote_count": 500,
                        "overview": "space journey friendship",
                        "genres": "Drama",
                    },
                    {
                        "id": 2,
                        "title": "B",
                        "vote_count": 500,
                        "overview": "space journey mystery",
                        "genres": "Drama",
                    },
                ]
            )
            movies.to_csv(data / "tmdb_5000_movies.csv", index=False)
            with patch.object(source, "DATA_DIR", data), patch.object(source, "MODEL_DIR", models):
                source.load_and_preprocess()
                pointer = (models / "active.json").read_bytes()
                seed = (data / "catalog_seed_v1.csv.gz").read_bytes()
                movies.iloc[:1].assign(title="Changed").to_csv(data / "tmdb_latest_movies.csv", index=False)
                with patch.object(
                    source, "build_semantic_embeddings", side_effect=RuntimeError("interrupted")
                ):
                    with self.assertRaises(RuntimeError):
                        source.load_and_preprocess()
            self.assertEqual((models / "active.json").read_bytes(), pointer)
            self.assertEqual((data / "catalog_seed_v1.csv.gz").read_bytes(), seed)

    def test_normal_source_excludes_adult_and_video_rows_without_truthy_string_bug(self):
        source = importlib.import_module("backend.data_preprocessing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame(
                [
                    {"id": 1, "title": "Normal", "adult": "False", "video": "False"},
                    {"id": 2, "title": "Adult", "adult": "True", "video": "False"},
                    {"id": 3, "title": "Video", "adult": "False", "video": "True"},
                ]
            ).to_csv(root / "tmdb_5000_movies.csv", index=False)
            with patch.object(source, "DATA_DIR", root):
                rows = source.load_movie_source()
            self.assertEqual(set(rows["id"]), {1})

    def test_invalid_authentication_stops_all_remaining_refresh_requests(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")
        import requests

        forbidden = requests.Response()
        forbidden.status_code = 401
        successful = requests.Response()
        successful.status_code = 200
        successful._content = b'{"id": 1}'
        with patch.dict(os.environ, {"TMDB_API_KEY": "test-secret"}):
            client = refresh.TMDBClient()
        with patch("requests.Session.get", side_effect=[forbidden, successful]):
            with self.assertRaises(RuntimeError):
                client("/movie/1")
            with self.assertRaises(RuntimeError):
                client("/movie/2")

    def test_verified_deleted_movie_is_reported_without_blocking_complete_refresh(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")

        def get(endpoint, **params):
            if endpoint == "/discover/movie":
                return {
                    "total_pages": 1,
                    "total_results": 2,
                    "results": [{"id": i, "title": "Film", "release_date": "2026-09-01"} for i in (1, 2)],
                }
            if endpoint == "/movie/2":
                return {"id": 2, "_source_not_found": True}
            return {"id": 1, "title": "Film", "release_date": "2026-09-01", "credits": {}, "keywords": {}}

        with tempfile.TemporaryDirectory() as directory:
            coverage = refresh.run_refresh(Path(directory), "2026-09-01", "2026-09-01", get=get)
            self.assertTrue(coverage["complete"])
            self.assertIn({"id": 2, "reason": "detail_deleted_at_source"}, coverage["detail_excluded"])

    def test_missing_append_sections_are_fetched_or_marked_explicitly_unavailable(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")

        def get(endpoint, **params):
            if endpoint.endswith("/credits"):
                return {"id": 1, "cast": [{"name": "Actor"}]}
            if endpoint.endswith("/keywords"):
                return {"id": 1, "_source_not_found": True}
            return {"id": 1, "title": "Film"}

        payload = refresh.fetch_movie_details(get, 1)
        self.assertEqual(payload["credits"]["cast"][0]["name"], "Actor")
        self.assertEqual(payload["_unavailable_sections"], ["keywords"])
        self.assertEqual(payload["keywords"], {})

    def test_lsa_content_projection_matches_plot_before_genre_only_overlap(self):
        import inspect

        import numpy as np
        import scipy.sparse

        source = importlib.import_module("backend.data_preprocessing")
        self.assertIn(
            "genre_dimensions",
            inspect.signature(source.build_semantic_embeddings).parameters,
            "LSA must support an independent plot projection",
        )
        matrix = scipy.sparse.csr_matrix(
            np.array(
                [
                    [10, 0, 1, 0],
                    [10, 0, 0, 1],
                    [0, 10, 1, 0],
                    [0, 10, 0, 1],
                ],
                dtype=np.float32,
            )
        )
        vectors, reducer, info = source.build_semantic_embeddings(
            pd.DataFrame(index=range(4)), matrix, "lsa", "", genre_dimensions=2
        )
        self.assertGreater(float(vectors[0] @ vectors[2]), float(vectors[0] @ vectors[1]) + 0.8)
        self.assertEqual(info["input_scope"], "weighted_tfidf_without_genres")

    def test_invalid_details_do_not_publish_over_successful_refresh_pair(self):
        refresh = importlib.import_module("backend.fetch_latest_movies")

        def get(endpoint, **params):
            if endpoint == "/discover/movie":
                return {
                    "total_pages": 1,
                    "total_results": 1,
                    "results": [{"id": 1, "title": "Good", "release_date": "2026-09-01"}],
                }
            return {
                "id": 1,
                "title": "",
                "release_date": "2026-09-01",
                "credits": {"cast": [], "crew": []},
                "keywords": {"keywords": []},
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "refresh_active.json").write_text('{"generation":"previous"}')
            with self.assertRaises(RuntimeError):
                refresh.run_refresh(root, "2026-09-01", "2026-09-01", get=get)
            self.assertEqual(json.loads((root / "refresh_active.json").read_text())["generation"], "previous")


if __name__ == "__main__":
    unittest.main()
