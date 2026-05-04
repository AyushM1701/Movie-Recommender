from __future__ import annotations

import csv
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from .config import settings
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import settings


POSTER_CSV = settings.data_dir / "poster_paths.csv"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/{movie_id}?api_key={api_key}"
USER_AGENT = "CineMatchPosterResolver/1.0"


class PosterRepository:
    def __init__(self) -> None:
        self.enabled = settings.enable_poster_lookup and bool(settings.tmdb_api_key.strip())
        self._lock = threading.Lock()
        self._poster_map = self._load_map()
        self._known_missing: set[int] = set()

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
        return self._poster_map.get(movie_id, "")

    def resolve(self, movie_id: int) -> str:
        cached = self._poster_map.get(movie_id, "")
        if cached or not self.enabled or movie_id in self._known_missing:
            return cached

        with self._lock:
            cached = self._poster_map.get(movie_id, "")
            if cached or movie_id in self._known_missing:
                return cached

            poster_path = self._fetch_from_tmdb(movie_id)
            self._poster_map[movie_id] = poster_path
            if poster_path:
                self._append_or_update(movie_id, poster_path)
            else:
                self._known_missing.add(movie_id)
            return poster_path

    def _fetch_from_tmdb(self, movie_id: int) -> str:
        request = urllib.request.Request(
            TMDB_MOVIE_URL.format(
                movie_id=movie_id,
                api_key=urllib.parse.quote(settings.tmdb_api_key.strip()),
            ),
            headers={"User-Agent": USER_AGENT},
        )

        for _attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=6) as response:
                    payload = json.loads(response.read())
                return (payload.get("poster_path") or "").strip()
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403, 404}:
                    return ""
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                continue
        return ""

    def _append_or_update(self, movie_id: int, poster_path: str) -> None:
        rows = self._poster_map.copy()
        rows[movie_id] = poster_path
        with POSTER_CSV.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "poster_path"])
            writer.writeheader()
            for existing_id in sorted(rows):
                writer.writerow({"id": existing_id, "poster_path": rows[existing_id]})
