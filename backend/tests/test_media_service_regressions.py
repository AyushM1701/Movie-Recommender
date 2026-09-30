import os

os.environ["TMDB_API_KEY"] = ""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend.posters import PosterRepository
from backend.tmdb import TMDBClient


class MediaServiceTests(unittest.TestCase):
    def client(self, **kwargs):
        client = TMDBClient(**kwargs)
        client.enabled = True
        return client

    def test_transient_failure_recovers_on_next_lookup(self):
        client = self.client()
        with patch.object(client, "_fetch_tmdb", side_effect=[None, {"id": 1, "title": "Recovered"}]):
            self.assertIsNone(client.get_details_and_credits(1))
            self.assertEqual(client.get_details_and_credits(1)["title"], "Recovered")

    def test_distinct_movies_overlap_and_same_movie_deduplicates(self):
        client = self.client()
        calls = []
        barrier = threading.Barrier(2)

        def fetch(endpoint):
            calls.append(endpoint)
            barrier.wait(timeout=1)
            return {"id": int(endpoint.split("/")[2].split("?")[0]), "title": "Film"}

        with (
            patch.object(client, "_fetch_tmdb", side_effect=fetch),
            ThreadPoolExecutor(max_workers=3) as workers,
        ):
            first = workers.submit(client.get_details_and_credits, 1)
            second = workers.submit(client.get_details_and_credits, 2)
            duplicate = workers.submit(client.get_details_and_credits, 1)
            self.assertEqual(first.result()["id"], 1)
            self.assertEqual(second.result()["id"], 2)
            self.assertEqual(duplicate.result()["id"], 1)
        self.assertEqual(len(calls), 2)

    def test_ttl_expiry_and_cache_capacity(self):
        client = self.client(cache_ttl=0.01, cache_capacity=2)
        with patch.object(client, "_fetch_tmdb", return_value={"id": 1, "title": "Film"}) as fetch:
            client.get_details_and_credits(1)
            client.get_details_and_credits(1)
            self.assertEqual(fetch.call_count, 1)
            time.sleep(0.02)
            client.get_details_and_credits(1)
            self.assertEqual(fetch.call_count, 2)
            client.get_details_and_credits(2)
            client.get_details_and_credits(3)
            client.get_details_and_credits(1)
            self.assertEqual(fetch.call_count, 5)

    def test_provider_groups_and_safe_links(self):
        client = self.client()
        payload = {
            "results": {
                "IN": {
                    "link": "http://unsafe.invalid",
                    "flatrate": [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/netflix.jpg"}],
                    "rent": [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/netflix.jpg"}],
                }
            }
        }
        with patch.object(client, "_fetch_tmdb", return_value=payload):
            result = client.get_watch_options(1, "IN")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["providers"][0]["types"], ["flatrate", "rent"])
        self.assertEqual(result["link"], "https://www.themoviedb.org/movie/1/watch?locale=IN")
        self.assertTrue(result["checked_at"])

    def test_provider_missing_and_outage_are_distinct(self):
        client = self.client()
        with patch.object(client, "_fetch_tmdb", side_effect=[None, {"results": {}}]):
            self.assertEqual(client.get_watch_options(1, "IN")["status"], "unavailable")
            self.assertEqual(client.get_watch_options(1, "IN")["status"], "not_listed")

    def test_failed_poster_fill_is_retryable(self):
        repository = PosterRepository()
        repository.enabled = True
        with patch.object(repository, "_fetch_from_tmdb", side_effect=["", "/recovered.jpg"]):
            repository._background_fetch(1)
            repository._background_fetch(1)
            self.assertEqual(repository.get(1), "/recovered.jpg")
        self.assertNotIn(1, repository._known_missing)
        repository.close()

    def test_confirmed_404_expires_without_poisoning_other_movies(self):
        from backend.tmdb import TMDBNotFound

        client = self.client(cache_ttl=0.01)
        with patch.object(
            client,
            "_fetch_tmdb",
            side_effect=[TMDBNotFound(), {"id": 2, "title": "Other"}, {"id": 1, "title": "Added later"}],
        ) as fetch:
            self.assertIsNone(client.get_details_and_credits(1))
            self.assertIsNone(client.get_details_and_credits(1))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(client.get_details_and_credits(2)["title"], "Other")
            time.sleep(0.02)
            self.assertEqual(client.get_details_and_credits(1)["title"], "Added later")

    def test_provider_checked_at_stays_at_successful_fetch_time(self):
        client = self.client()
        with patch.object(client, "_fetch_tmdb", return_value={"results": {}}) as fetch:
            first = client.get_watch_options(1, "IN")
            time.sleep(0.01)
            second = client.get_watch_options(1, "IN")
            self.assertEqual(first["checked_at"], second["checked_at"])
            self.assertEqual(fetch.call_count, 1)

    def test_provider_cache_keeps_listings_six_hours_but_retries_missing_region_sooner(self):
        client = self.client()
        clock = [100.0]
        payload = {"results": {"IN": {"flatrate": [{"provider_id": 8, "provider_name": "Netflix"}]}}}
        with (
            patch("backend.tmdb.time.monotonic", side_effect=lambda: clock[0]),
            patch.object(client, "_fetch_tmdb", return_value=payload) as fetch,
        ):
            client.get_watch_options(1, "IN")
            clock[0] += 3600
            client.get_watch_options(1, "IN")
            self.assertEqual(fetch.call_count, 1)
            client.get_watch_options(1, "US")
            clock[0] += 901
            client.get_watch_options(1, "US")
            self.assertEqual(fetch.call_count, 3)
