from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
USER_AGENT = "CineMatchMediaService/2.0"


class TMDBNotFound(Exception):
    """A confirmed HTTP 404, distinct from credentials or transient outages."""


FALLBACK_COUNTRIES = [
    ("IN", "India"),
    ("US", "United States"),
    ("GB", "United Kingdom"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
    ("DE", "Germany"),
    ("FR", "France"),
    ("ES", "Spain"),
    ("IT", "Italy"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("BR", "Brazil"),
    ("MX", "Mexico"),
    ("AR", "Argentina"),
    ("ZA", "South Africa"),
    ("AE", "United Arab Emirates"),
    ("SA", "Saudi Arabia"),
    ("SG", "Singapore"),
    ("MY", "Malaysia"),
    ("ID", "Indonesia"),
    ("PH", "Philippines"),
    ("TH", "Thailand"),
    ("VN", "Vietnam"),
    ("PK", "Pakistan"),
    ("BD", "Bangladesh"),
    ("LK", "Sri Lanka"),
    ("NP", "Nepal"),
    ("NL", "Netherlands"),
    ("BE", "Belgium"),
    ("CH", "Switzerland"),
    ("AT", "Austria"),
    ("SE", "Sweden"),
    ("NO", "Norway"),
    ("DK", "Denmark"),
    ("FI", "Finland"),
    ("PL", "Poland"),
    ("PT", "Portugal"),
    ("IE", "Ireland"),
    ("TR", "Turkey"),
    ("EG", "Egypt"),
    ("IL", "Israel"),
    ("GR", "Greece"),
    ("CZ", "Czechia"),
    ("HU", "Hungary"),
    ("RO", "Romania"),
    ("CL", "Chile"),
    ("CO", "Colombia"),
    ("PE", "Peru"),
    ("TW", "Taiwan"),
    ("HK", "Hong Kong"),
]


class TMDBClient:
    """Bounded TTL caches and same-key coalescing; network work never holds the lock."""

    def __init__(self, cache_ttl: float = 21600, cache_capacity: int = 512, max_concurrency: int = 6) -> None:
        self.api_key = settings.tmdb_api_key.strip()
        self.enabled = bool(self.api_key)
        self.cache_ttl = cache_ttl
        self.cache_capacity = max(1, cache_capacity)
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._in_flight: dict[tuple, dict] = {}
        self._network_slots = threading.BoundedSemaphore(max_concurrency)

    def _cached(self, key: tuple, fetch, ttl: float | None = None):
        if not self.enabled:
            return None
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                self._cache.move_to_end(key)
                return cached[1]
            self._cache.pop(key, None)
            flight = self._in_flight.get(key)
            owner = flight is None
            if owner:
                flight = {"event": threading.Event(), "value": None}
                self._in_flight[key] = flight
        if not owner:
            flight["event"].wait(timeout=20)
            return flight["value"]
        result = None
        duration = self.cache_ttl if ttl is None or callable(ttl) else ttl
        cache_result = False
        try:
            with self._network_slots:
                result = fetch()
            if callable(ttl):
                duration = ttl(result)
            cache_result = result is not None
        except TMDBNotFound:
            cache_result = True
            duration = min(duration, 60)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, TypeError):
            logger.debug("TMDB lookup failed temporarily.")
        finally:
            with self._lock:
                flight["value"] = result
                if cache_result:
                    self._cache[key] = (time.monotonic() + duration, result)
                    self._cache.move_to_end(key)
                    while len(self._cache) > self.cache_capacity:
                        self._cache.popitem(last=False)
                self._in_flight.pop(key, None)
                flight["event"].set()
        return result

    def get_details_and_credits(self, movie_id: int) -> dict[str, Any] | None:
        def fetch():
            data = self._fetch_tmdb(f"/movie/{movie_id}?append_to_response=videos,credits,external_ids")
            return self._parse_movie_payload(data) if isinstance(data, dict) and data else None

        return self._cached(("details", movie_id), fetch)

    def get_trailer_url(self, movie_id: int) -> dict[str, str] | None:
        details = self.get_details_and_credits(movie_id)
        return details.get("trailer") if details else None

    def get_countries(self) -> list[dict]:
        def fetch():
            data = self._fetch_tmdb("/configuration/countries")
            if not isinstance(data, list):
                return None
            rows = [
                {"code": row["iso_3166_1"], "name": row.get("english_name") or row["iso_3166_1"]}
                for row in data
                if isinstance(row, dict) and len(row.get("iso_3166_1", "")) == 2
            ]
            return sorted(rows, key=lambda row: row["name"]) or None

        return self._cached(("countries",), fetch, 86400) or sorted(
            [{"code": code, "name": name} for code, name in FALLBACK_COUNTRIES], key=lambda row: row["name"]
        )

    def get_watch_options(self, movie_id: int, country: str = "IN") -> dict:
        def fetch():
            result = self._fetch_tmdb(f"/movie/{movie_id}/watch/providers")
            if not isinstance(result, dict):
                return None
            return {**result, "__checked_at": datetime.now(UTC).isoformat()}

        def provider_ttl(payload):
            region = (payload.get("results") or {}).get(country) or {} if isinstance(payload, dict) else {}
            listed = any(region.get(kind) for kind in ("flatrate", "free", "ads", "rent", "buy"))
            return min(self.cache_ttl, 21600 if listed else 900)

        payload = self._cached(("providers", movie_id, country), fetch, provider_ttl)
        # TMDB's regional watch page is an availability link, not a direct playback URL.
        link = f"https://www.themoviedb.org/movie/{movie_id}/watch?locale={country}"
        providers: dict[int, dict] = {}
        region = (payload.get("results") or {}).get(country) or {} if isinstance(payload, dict) else {}
        for kind in ("flatrate", "free", "ads", "rent", "buy"):
            for entry in region.get(kind) or []:
                provider_id = entry.get("provider_id")
                if not isinstance(provider_id, int):
                    continue
                provider = providers.setdefault(
                    provider_id,
                    {
                        "id": provider_id,
                        "name": entry.get("provider_name") or "Provider",
                        "logo_path": entry.get("logo_path"),
                        "types": [],
                    },
                )
                if kind not in provider["types"]:
                    provider["types"].append(kind)
        return {
            "movie_id": movie_id,
            "country": country,
            "status": "unavailable" if payload is None else ("available" if providers else "not_listed"),
            "link": link,
            "providers": list(providers.values()),
            "checked_at": (payload or {}).get("__checked_at") or datetime.now(UTC).isoformat(),
        }

    def _fetch_tmdb(self, endpoint: str) -> dict[str, Any] | list | None:
        separator = "&" if "?" in endpoint else "?"
        full_url = f"{TMDB_BASE_URL}{endpoint}{separator}api_key={urllib.parse.quote(self.api_key)}"
        request = urllib.request.Request(
            full_url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        for attempt in range(3):
            delay = min(0.15 * 2**attempt, 1)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise TMDBNotFound() from None
                if exc.code in (401, 403):
                    return None
                if exc.code == 429:
                    try:
                        delay = min(float(exc.headers.get("Retry-After", delay)), 2)
                    except (ValueError, TypeError):
                        pass
                elif exc.code < 500:
                    return None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
                # Never log URL-bearing exception strings: they may contain the API key.
                pass
            if attempt < 2:
                time.sleep(delay)
        return None

    def _parse_movie_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        movie_id = data.get("id")

        # 1. Trailer extraction
        videos = (data.get("videos") or {}).get("results", [])
        trailer_info = None
        # Prioritize YouTube official Trailer -> Teaser -> any YouTube video
        youtube_videos = [v for v in videos if v.get("site") == "YouTube" and v.get("key")]
        trailers = [v for v in youtube_videos if v.get("type") == "Trailer"]
        if not trailers:
            trailers = [v for v in youtube_videos if v.get("type") == "Teaser"]
        if not trailers:
            trailers = youtube_videos

        if trailers:
            best_trailer = trailers[0]
            # Try to find official one if possible
            official = [v for v in trailers if v.get("official") is True]
            if official:
                best_trailer = official[0]

            key = best_trailer.get("key")
            trailer_info = {
                "key": key,
                "name": best_trailer.get("name", "Official Trailer"),
                "embed_url": f"https://www.youtube-nocookie.com/embed/{key}?autoplay=1&rel=0&modestbranding=1",
                "watch_url": f"https://www.youtube.com/watch?v={key}",
            }

        # 2. Credits (Cast & Crew)
        credits_data = data.get("credits") or {}
        raw_cast = credits_data.get("cast", [])
        cast_list = []
        for member in raw_cast[:10]:
            profile_path = member.get("profile_path")
            cast_list.append(
                {
                    "id": member.get("id"),
                    "name": member.get("name"),
                    "character": member.get("character") or "Cast",
                    "profile_path": profile_path,
                    "profile_url": f"{TMDB_IMAGE_BASE}/w185{profile_path}" if profile_path else None,
                }
            )

        directors = []
        for crew_member in credits_data.get("crew") or []:
            if crew_member.get("job") == "Director":
                profile_path = crew_member.get("profile_path")
                directors.append(
                    {
                        "id": crew_member.get("id"),
                        "name": crew_member.get("name"),
                        "job": "Director",
                        "profile_url": f"{TMDB_IMAGE_BASE}/w185{profile_path}" if profile_path else None,
                    }
                )

        # 3. External IDs
        ext_ids = data.get("external_ids") or {}
        imdb_id = ext_ids.get("imdb_id") or data.get("imdb_id")

        return {
            "id": movie_id,
            "title": data.get("title") or "",
            "tagline": (data.get("tagline") or "").strip(),
            "overview": (data.get("overview") or "").strip(),
            "runtime": data.get("runtime"),
            "release_date": data.get("release_date") or "",
            "budget": data.get("budget") or 0,
            "revenue": data.get("revenue") or 0,
            "poster_path": data.get("poster_path") or "",
            "backdrop_path": data.get("backdrop_path") or "",
            "backdrop_url": f"{TMDB_IMAGE_BASE}/w1280{data.get('backdrop_path')}"
            if data.get("backdrop_path")
            else None,
            "imdb_id": imdb_id,
            "imdb_url": f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None,
            "tmdb_url": f"https://www.themoviedb.org/movie/{movie_id}" if movie_id else None,
            "trailer": trailer_info,
            "cast": cast_list,
            "directors": directors,
            "genres": [g["name"] for g in data.get("genres", []) if "name" in g],
        }


tmdb_client = TMDBClient()
