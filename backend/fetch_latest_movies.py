"""Checkpointed exhaustive date-bounded TMDB refresh; complete pairs publish atomically."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
load_dotenv(PROJECT_ROOT / ".env")
BASE_URL = "https://api.themoviedb.org/3"
MOVIE_COLUMNS = [
    "id",
    "title",
    "overview",
    "genres",
    "keywords",
    "vote_average",
    "vote_count",
    "release_date",
    "status",
    "runtime",
    "popularity",
    "poster_path",
    "backdrop_path",
    "tagline",
    "original_language",
    "production_companies",
]
CREDIT_COLUMNS = ["movie_id", "title", "cast", "crew"]


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1 * (attempt + 1))


class TMDBClient:
    """Thread-local connections share one request budget; errors never disclose URLs."""

    def __init__(self, rate=20):
        self.key = os.environ.get("TMDB_API_KEY", "").strip()
        if not self.key:
            raise RuntimeError("TMDB_API_KEY is required for refresh.")
        self.local = threading.local()
        self.lock = threading.Lock()
        self.next_request = 0.0
        self.interval = 1 / max(1, min(rate, 30))
        self.retries = 0
        self.stopped = threading.Event()

    def __call__(self, endpoint, **params):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
        for attempt in range(5):
            if self.stopped.is_set():
                raise RuntimeError("TMDB refresh stopped after authentication rejection.")
            with self.lock:
                wait = max(0, self.next_request - time.monotonic())
                self.next_request = max(time.monotonic(), self.next_request) + self.interval
            if wait:
                time.sleep(wait)
            try:
                response = self.local.session.get(
                    BASE_URL + endpoint, params={"api_key": self.key, **params}, timeout=(5, 25)
                )
                if response.status_code in (401, 403):
                    self.stopped.set()
                    raise RuntimeError("TMDB authentication rejected; refresh stopped.")
                if response.status_code == 404:
                    movie_id = endpoint.split("/")[2] if endpoint.startswith("/movie/") else None
                    return (
                        {"id": int(movie_id), "_source_not_found": True}
                        if movie_id and movie_id.isdigit()
                        else None
                    )
                if response.status_code == 429:
                    try:
                        delay = min(120, max(1, float(response.headers.get("Retry-After", "2"))))
                    except ValueError:
                        delay = 2
                    with self.lock:
                        self.next_request = max(self.next_request, time.monotonic() + delay)
                    self.retries += 1
                    continue
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
            except (requests.RequestException, ValueError):
                pass
            if attempt < 4:
                self.retries += 1
                time.sleep(min(8, 0.5 * 2**attempt))
        return None


def discover_movies(get, start, end, checkpoint=None):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("Refresh start must precede cutoff.")
    checkpoint_data = (
        json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint and checkpoint.exists() else {}
    )
    pages_cache = checkpoint_data.setdefault("pages", {})
    page_dir = checkpoint.parent / "discovery_pages" if checkpoint else None
    if page_dir:
        page_dir.mkdir(exist_ok=True)
        if not checkpoint.exists():
            atomic_json(checkpoint, checkpoint_data)
    rows, windows, excluded = {}, [], []

    def page_for(a, b, page, reconcile=False, sort="primary_release_date.asc", year_filter=False):
        suffix = "" if sort == "primary_release_date.asc" else "_" + sort.replace(".", "_")
        if year_filter:
            suffix += "_year"
        key = f"{a}/{b}/{page}{suffix}"
        page_file = page_dir / f"{a}_{b}_{page}{suffix}.json" if page_dir else None
        if not reconcile and key in pages_cache:
            return pages_cache[key]
        if not reconcile and page_file and page_file.exists():
            return json.loads(page_file.read_text(encoding="utf-8"))
        year_params = {"primary_release_year": a.year} if year_filter else {}
        payload = get(
            "/discover/movie",
            **{
                "primary_release_date.gte": str(a),
                "primary_release_date.lte": str(b),
                "page": page,
                "include_adult": "false",
                "include_video": "false",
                "sort_by": sort,
                "language": "en-US",
                **year_params,
            },
        )
        if not payload or not isinstance(payload.get("results"), list):
            raise RuntimeError(
                f"Discovery failed for {a} through {b}, page {page}; previous snapshot retained."
            )
        if not reconcile:
            pages_cache[key] = payload
            if page_file:
                atomic_json(page_file, payload)
        return payload

    def walk(a, b):
        initial = page_for(a, b, 1)
        total_pages = int(initial.get("total_pages", 0))
        if total_pages > 500:
            if a == b:
                raise RuntimeError(f"Single-day TMDB page limit exceeded on {a}; scope incomplete.")
            mid = a + (b - a) // 2
            walk(a, mid)
            walk(mid + timedelta(days=1), b)
            return
        ids = set()
        for page in range(1, max(1, total_pages) + 1):
            payload = initial if page == 1 else page_for(a, b, page)
            for movie in payload["results"]:
                movie_id, release = movie.get("id"), movie.get("release_date", "")
                if (
                    not movie_id
                    or not (str(a) <= release <= str(b))
                    or movie.get("adult")
                    or movie.get("video")
                ):
                    excluded.append({"id": movie_id, "reason": "outside_scope_or_missing_date"})
                    continue
                rows[int(movie_id)] = movie
                ids.add(int(movie_id))
        verified = page_for(a, b, 1, reconcile=True)
        drift = initial.get("total_results", 0) != verified.get("total_results", 0)
        complete = not drift and len(ids) == int(initial.get("total_results", 0))
        reconciliation_sort = None
        if not complete and a == b:
            # Equal release-date sorting can repeat IDs even on a single day.
            # Independently sorted complete pages fill gaps; counts must still reconcile.
            reconciliation_sort = "popularity.desc"
            for page in range(1, max(1, total_pages) + 1):
                alternate = page_for(a, b, page, sort=reconciliation_sort)
                for movie in alternate["results"]:
                    movie_id, release = movie.get("id"), movie.get("release_date", "")
                    if (
                        movie_id
                        and str(a) <= release <= str(b)
                        and not movie.get("adult")
                        and not movie.get("video")
                    ):
                        rows[int(movie_id)] = movie
                        ids.add(int(movie_id))
            verified = page_for(a, b, 1, reconcile=True)
            drift = initial.get("total_results", 0) != verified.get("total_results", 0)
            complete = not drift and len(ids) == int(verified.get("total_results", 0))
            if not complete:
                # The redundant year constraint has identical scope for a single
                # day and bypasses a stale independently cached result count.
                first_year = page_for(a, b, 1, sort=reconciliation_sort, year_filter=True)
                for page in range(1, max(1, int(first_year.get("total_pages", 0))) + 1):
                    alternate = (
                        first_year
                        if page == 1
                        else page_for(a, b, page, sort=reconciliation_sort, year_filter=True)
                    )
                    for movie in alternate["results"]:
                        movie_id, release = movie.get("id"), movie.get("release_date", "")
                        if (
                            movie_id
                            and str(a) <= release <= str(b)
                            and not movie.get("adult")
                            and not movie.get("video")
                        ):
                            rows[int(movie_id)] = movie
                            ids.add(int(movie_id))
                verified = page_for(a, b, 1, reconcile=True, sort=reconciliation_sort, year_filter=True)
                drift = initial.get("total_results", 0) != verified.get("total_results", 0)
                complete = first_year.get("total_results") == verified.get("total_results") and len(
                    ids
                ) == int(verified.get("total_results", 0))
                reconciliation_sort += ":primary_release_year"
        if not complete and a != b:
            # TMDB can duplicate IDs across pages with equal sort values. Smaller
            # windows reconcile those boundaries and preserve every discovered ID.
            mid = a + (b - a) // 2
            walk(a, mid)
            walk(mid + timedelta(days=1), b)
            return
        windows.append(
            {
                "start": str(a),
                "end": str(b),
                "reported_results": initial.get("total_results", 0),
                "pages": total_pages,
                "unique_ids": len(ids),
                "verified_results": verified.get("total_results", 0),
                "count_drift": drift,
                "reconciliation_sort": reconciliation_sort,
                "complete": complete,
            }
        )
        print(f"Discovery {a}..{b}: {len(ids):,} IDs / {total_pages} pages", flush=True)

    cursor = first
    while cursor <= last:
        month_end = min(
            last, date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        )
        walk(cursor, month_end)
        cursor = month_end + timedelta(days=1)
    return rows, {
        "windows": windows,
        "excluded": excluded,
        "discovery_complete": all(w["complete"] for w in windows),
        "unique_discovered_ids": len(rows),
    }


def _movie_row(payload):
    row = {column: payload.get(column, "") for column in MOVIE_COLUMNS}
    for column in ("genres", "production_companies"):
        row[column] = json.dumps(payload.get(column) or [], ensure_ascii=False)
    row["keywords"] = json.dumps((payload.get("keywords") or {}).get("keywords") or [], ensure_ascii=False)
    row["poster_path"] = payload.get("poster_path") or ""
    row["backdrop_path"] = payload.get("backdrop_path") or ""
    return row


def fetch_movie_details(get, movie_id):
    payload = get(f"/movie/{movie_id}", append_to_response="credits,keywords", language="en-US")
    if not isinstance(payload, dict) or payload.get("_source_not_found"):
        return payload
    missing = []
    for field in ("credits", "keywords"):
        if isinstance(payload.get(field), dict):
            continue
        section = get(f"/movie/{movie_id}/{field}")
        if isinstance(section, dict) and section.get("_source_not_found"):
            payload[field] = {}
            missing.append(field)
        elif isinstance(section, dict):
            payload[field] = section
        else:
            return None
    payload["_unavailable_sections"] = missing
    return payload


def run_refresh(data_dir, start="2026-01-01", end="2026-09-30", *, get=None, workers=12, rate=20):
    data_dir.mkdir(parents=True, exist_ok=True)
    staging = data_dir / "refresh_staging" / f"{start}_{end}"
    staging.mkdir(parents=True, exist_ok=True)
    get = get or TMDBClient(rate)
    discovered, coverage = discover_movies(get, start, end, staging / "discovery.json")
    if not discovered:
        raise RuntimeError("Discovery returned no valid films; previous snapshot retained.")
    if not coverage["discovery_complete"]:
        cache = json.loads((staging / "discovery.json").read_text(encoding="utf-8"))
        for window in coverage["windows"]:
            if not window["complete"]:
                prefix = f"{window['start']}/{window['end']}/"
                cache["pages"] = {
                    key: value for key, value in cache["pages"].items() if not key.startswith(prefix)
                }
                for page_file in (staging / "discovery_pages").glob(
                    f"{window['start']}_{window['end']}_*.json"
                ):
                    page_file.unlink()
        atomic_json(staging / "discovery.json", cache)
        discovered, coverage = discover_movies(get, start, end, staging / "discovery.json")
    checkpoint = sqlite3.connect(staging / "details.sqlite3")
    checkpoint.execute("CREATE TABLE IF NOT EXISTS details(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    existing = {row[0] for row in checkpoint.execute("SELECT id FROM details")}
    remaining = set(discovered) - existing
    print(f"Detail enrichment: {len(existing):,} checkpointed; {len(remaining):,} remaining", flush=True)
    failed, processed = [], 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 24))) as pool:
        pending = {pool.submit(fetch_movie_details, get, movie_id): movie_id for movie_id in remaining}
        for future in as_completed(pending):
            movie_id = pending[future]
            payload = future.result()
            if (
                isinstance(payload, dict)
                and payload.get("id") == movie_id
                and (
                    payload.get("_source_not_found")
                    or (
                        isinstance(payload.get("title"), str)
                        and payload["title"].strip()
                        and isinstance(payload.get("credits"), dict)
                        and isinstance(payload.get("keywords"), dict)
                    )
                )
            ):
                checkpoint.execute(
                    "INSERT OR REPLACE INTO details VALUES (?,?)",
                    (movie_id, json.dumps(payload, ensure_ascii=False)),
                )
            else:
                failed.append(movie_id)
            processed += 1
            if processed % 200 == 0:
                checkpoint.commit()
                atomic_json(
                    staging / "progress.json",
                    {
                        "processed": processed,
                        "checkpointed_before": len(existing),
                        "remaining_at_start": len(remaining),
                        "failed_ids": failed,
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                )
                print(f"Details {processed:,}/{len(remaining):,}; failures {len(failed)}", flush=True)
    checkpoint.commit()
    movies, credits, detail_excluded, unavailable_sections = [], [], [], []
    for movie_id, raw in checkpoint.execute("SELECT id,payload FROM details ORDER BY id"):
        if movie_id not in discovered:
            continue
        payload = json.loads(raw)
        if payload.get("_source_not_found"):
            detail_excluded.append({"id": movie_id, "reason": "detail_deleted_at_source"})
            continue
        if payload.get("_unavailable_sections"):
            unavailable_sections.append(
                {
                    "id": movie_id,
                    "sections": payload["_unavailable_sections"],
                    "reason": "source_returned_404",
                }
            )
        if (
            not (start <= payload.get("release_date", "") <= end)
            or payload.get("adult")
            or payload.get("video")
        ):
            detail_excluded.append({"id": movie_id, "reason": "detail_outside_scope"})
            continue
        movies.append(_movie_row(payload))
        credits.append(
            {
                "movie_id": movie_id,
                "title": payload.get("title", ""),
                "cast": json.dumps(payload["credits"].get("cast") or [], ensure_ascii=False),
                "crew": json.dumps(payload["credits"].get("crew") or [], ensure_ascii=False),
            }
        )
    checkpoint.close()
    coverage.update(
        {
            "cutoff": end,
            "start": start,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "scope": "TMDB non-adult, non-video movies across all languages/countries with primary release date in range",
            "details_success": len(movies),
            "credits_success": len(credits)
            - sum("credits" in row["sections"] for row in unavailable_sections),
            "unavailable_sections": unavailable_sections,
            "failed_ids": failed,
            "detail_excluded": detail_excluded,
            "retries": getattr(get, "retries", 0),
            "complete": coverage["discovery_complete"] and not failed,
        }
    )
    coverage["feature_coverage"] = {
        "with_overview": sum(bool(str(row.get("overview") or "").strip()) for row in movies),
        "with_genres": sum(row["genres"] != "[]" for row in movies),
        "with_keywords": sum(row["keywords"] != "[]" for row in movies),
        "with_poster": sum(bool(row["poster_path"]) for row in movies),
        "with_votes": sum(int(row.get("vote_count") or 0) > 0 for row in movies),
        "with_cast": sum(row["cast"] != "[]" for row in credits),
        "with_director": sum(
            any(item.get("job") == "Director" for item in json.loads(row["crew"])) for row in credits
        ),
    }
    atomic_json(staging / "coverage.json", coverage)
    if not coverage["complete"] or not movies:
        raise RuntimeError(
            f"Refresh incomplete: {len(failed)} detail failures; previous successful snapshot retained. Resume the same command."
        )
    generation = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target = data_dir / "refresh_generations" / generation
    target.mkdir(parents=True)
    pd.DataFrame(movies, columns=MOVIE_COLUMNS).to_csv(target / "movies.csv", index=False)
    pd.DataFrame(credits, columns=CREDIT_COLUMNS).to_csv(target / "credits.csv", index=False)
    coverage["generation"] = generation
    coverage["checksums"] = {
        name: hashlib.sha256((target / name).read_bytes()).hexdigest()
        for name in ("movies.csv", "credits.csv")
    }
    atomic_json(target / "coverage.json", coverage)
    atomic_json(data_dir / "refresh_active.json", {"generation": generation})
    print(f"Published {len(movies):,} detailed movies and paired credits: {generation}", flush=True)
    return coverage


def active_refresh_dir(data_dir):
    pointer = data_dir / "refresh_active.json"
    if not pointer.exists():
        return None
    generation = json.loads(pointer.read_text(encoding="utf-8"))["generation"]
    if Path(generation).name != generation:
        raise RuntimeError("Invalid refresh generation pointer.")
    return data_dir / "refresh_generations" / generation


def fetch_latest_movies():
    return run_refresh(DATA_DIR)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--rate", type=float, default=20)
    args = parser.parse_args()
    run_refresh(DATA_DIR, args.start, args.end, workers=args.workers, rate=args.rate)
