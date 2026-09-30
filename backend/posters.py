from __future__ import annotations

import csv
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from backend.config import settings

POSTER_CSV = settings.data_dir / "poster_paths.csv"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{movie_id}?api_key={api_key}"
USER_AGENT = "CineMatchPosterResolver/1.0"


class PosterRepository:
    def __init__(self) -> None:
        self.enabled = settings.enable_poster_lookup and bool(settings.tmdb_api_key.strip())
        self._lock = threading.Lock()
        self._poster_map = self._load_map()
        self._known_missing: dict[int, float] = {}
        self._dynamic: OrderedDict[int, tuple[float, str]] = OrderedDict()
        self.cache_ttl = 3600
        self.cache_capacity = 512
        self._executor = ThreadPoolExecutor(max_workers=5)
        self._in_flight: set[int] = set()

    def _load_map(self) -> dict[int, str]:
        if not POSTER_CSV.exists():
            return {}

        rows = {}
        with POSTER_CSV.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    movie_id = int(row.get("id", ""))
                except (TypeError, ValueError):
                    continue
                rows[movie_id] = (row.get("poster_path") or "").strip()
        return rows

    def get(self, movie_id: int) -> str:
        with self._lock:
            entry = self._dynamic.get(movie_id)
            if entry and entry[0] > time.monotonic():
                self._dynamic.move_to_end(movie_id)
                return entry[1]
            self._dynamic.pop(movie_id, None)
            return self._poster_map.get(movie_id, "")

    def resolve(self, movie_id: int) -> str:
        cached = self.get(movie_id)
        if cached or not self.enabled:
            return cached
        with self._lock:
            missing_until = self._known_missing.get(movie_id, 0)
            if missing_until > time.monotonic() or movie_id in self._in_flight or len(self._in_flight) >= 128:
                return ""
            self._known_missing.pop(movie_id, None)
            self._in_flight.add(movie_id)
        try:
            self._executor.submit(self._background_fetch, movie_id)
        except RuntimeError:
            with self._lock:
                self._in_flight.discard(movie_id)
        return ""

    def _background_fetch(self, movie_id: int) -> None:
        from backend.tmdb import TMDBNotFound

        missing = False
        try:
            poster_path = self._fetch_from_tmdb(movie_id)
        except TMDBNotFound:
            poster_path = ""
            missing = True
        except Exception:
            poster_path = ""
        with self._lock:
            self._in_flight.discard(movie_id)
            if poster_path:
                self._dynamic[movie_id] = (time.monotonic() + self.cache_ttl, poster_path)
                self._dynamic.move_to_end(movie_id)
                self._known_missing.pop(movie_id, None)
                while len(self._dynamic) > self.cache_capacity:
                    self._dynamic.popitem(last=False)
            elif missing:
                self._known_missing[movie_id] = time.monotonic() + 60
                while len(self._known_missing) > self.cache_capacity:
                    self._known_missing.pop(next(iter(self._known_missing)))

    def _fetch_from_tmdb(self, movie_id: int) -> str:
        from backend.tmdb import tmdb_client

        payload = tmdb_client.get_details_and_credits(movie_id)
        return (payload or {}).get("poster_path") or ""

    def close(self) -> None:
        """Release workers without mutating checked-in data at request time."""
        self._executor.shutdown(wait=False, cancel_futures=True)
