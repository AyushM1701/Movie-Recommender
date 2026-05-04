from __future__ import annotations

import os
import pickle
import re
from typing import Iterable

import numpy as np
import pandas as pd

from backend.config import settings
from backend.posters import PosterRepository


MODEL_DIR = settings.model_dir


class RecommendationEngine:
    """In-memory recommendation engine backed by precomputed artifacts."""

    def __init__(self) -> None:
        self.movies: pd.DataFrame | None = None
        self.cosine_sim: np.ndarray | None = None
        self.indices: pd.Series | None = None
        self.id_to_index: pd.Series | None = None
        self._genre_lookup: dict[str, str] = {}
        self._catalog_stats: dict[str, int | float | list[int] | None] = {}
        self.poster_repository = PosterRepository()
        self._load_artifacts()
        self._prepare_indexes()

    def _load_artifacts(self) -> None:
        try:
            self.movies = pd.read_pickle(os.path.join(MODEL_DIR, "movies.pkl"))
            with open(os.path.join(MODEL_DIR, "cosine_sim.pkl"), "rb") as file_obj:
                self.cosine_sim = pickle.load(file_obj)
            with open(os.path.join(MODEL_DIR, "indices.pkl"), "rb") as file_obj:
                self.indices = pickle.load(file_obj)
            with open(os.path.join(MODEL_DIR, "id_to_index.pkl"), "rb") as file_obj:
                self.id_to_index = pickle.load(file_obj)
        except FileNotFoundError as exc:  # pragma: no cover - depends on local artifacts
            raise RuntimeError(
                "Model artifacts are missing. Run `python backend/data_preprocessing.py` first."
            ) from exc

    def _prepare_indexes(self) -> None:
        if self.movies is None:
            raise RuntimeError("Movies dataset failed to load.")

        self.movies["normalized_title"] = (
            self.movies["title"].fillna("").astype(str).str.lower().str.strip()
        )

        genres = sorted(
            {
                genre
                for genre_list in self.movies["genres_list"]
                if isinstance(genre_list, list)
                for genre in genre_list
            }
        )
        self._genre_lookup = {genre.lower(): genre for genre in genres}

        year_series = (
            self.movies["release_date"]
            .fillna("")
            .astype(str)
            .str.extract(r"(?P<year>\d{4})")["year"]
            .dropna()
            .astype(int)
        )
        self._catalog_stats = {
            "total_movies": int(len(self.movies)),
            "total_genres": int(len(genres)),
            "average_rating": round(float(self.movies["vote_average"].fillna(0).mean()), 2),
            "posters_available": int(self.movies["poster_path"].fillna("").astype(bool).sum()),
            "year_range": [int(year_series.min()), int(year_series.max())]
            if not year_series.empty
            else None,
        }

    def _clean_text(self, value: object) -> str:
        if value is None or pd.isna(value):
            return ""
        text = str(value).strip()
        return "" if text.lower() == "nan" else text

    def _format_movie(
        self,
        row: pd.Series,
        score: float | None = None,
        score_key: str = "similarity_score",
    ) -> dict:
        genres = row.get("genres_list", [])
        if not isinstance(genres, list):
            genres = []

        release_date = self._clean_text(row.get("release_date"))
        release_year = release_date[:4] if release_date[:4].isdigit() else None

        movie_id = int(row["id"])
        poster_path = self._clean_text(row.get("poster_path"))
        if not poster_path:
            poster_path = self.poster_repository.resolve(movie_id)
            if poster_path:
                row["poster_path"] = poster_path

        movie = {
            "id": movie_id,
            "title": self._clean_text(row.get("title")),
            "overview": self._clean_text(row.get("overview")),
            "genres": genres,
            "vote_average": round(float(row.get("vote_average", 0) or 0), 1),
            "vote_count": int(row.get("vote_count", 0) or 0),
            "release_year": release_year,
            "runtime": int(row["runtime"]) if pd.notna(row.get("runtime")) else None,
            "popularity": round(float(row.get("popularity", 0) or 0), 2),
            "poster_path": poster_path,
        }
        if score is not None:
            movie[score_key] = round(float(score), 4)
        return movie

    def normalize_genres(self, genres: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for genre in genres:
            if not genre:
                continue
            canonical = self._genre_lookup.get(genre.strip().lower())
            if canonical and canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)

        return normalized

    def recommend_popular(self, top_n: int = 10) -> list[dict]:
        movies = self.recommend_by_genres(self.get_all_genres(), top_n=top_n, min_votes=300)
        return movies

    def recommend_by_genres(
        self,
        genres: list[str],
        top_n: int = 10,
        min_votes: int = 100,
        min_rating: float = 6.0,
    ) -> list[dict]:
        normalized_genres = set(self.normalize_genres(genres))
        if not normalized_genres:
            return []

        def has_genre(genre_list: object) -> bool:
            return isinstance(genre_list, list) and any(
                genre in normalized_genres for genre in genre_list
            )

        filtered = self.movies[
            self.movies["genres_list"].apply(has_genre)
            & (self.movies["vote_count"] >= min_votes)
            & (self.movies["vote_average"] >= min_rating)
        ].copy()

        if len(filtered) < top_n:
            filtered = self.movies[self.movies["genres_list"].apply(has_genre)].copy()

        if filtered.empty:
            return []

        global_mean = float(self.movies["vote_average"].mean())
        vote_floor = max(min_votes, 1)
        filtered["_score"] = filtered.apply(
            lambda row: (
                (row["vote_count"] / (row["vote_count"] + vote_floor)) * row["vote_average"]
                + (vote_floor / (row["vote_count"] + vote_floor)) * global_mean
            ),
            axis=1,
        )

        top = filtered.sort_values(
            by=["_score", "popularity", "vote_count"],
            ascending=False,
        ).head(top_n)
        return [
            self._format_movie(row, row["_score"], "bayesian_score")
            for _, row in top.iterrows()
        ]

    def recommend_by_history(
        self,
        movie_ids: list[int],
        top_n: int = 10,
        exclude_watched: bool = True,
    ) -> list[dict]:
        valid_indexes = [
            int(self.id_to_index[movie_id])
            for movie_id in dict.fromkeys(movie_ids)
            if movie_id in self.id_to_index.index
        ]
        if not valid_indexes:
            return []

        profile = np.zeros(len(self.movies), dtype=np.float64)
        for movie_index in valid_indexes:
            profile += self.cosine_sim[movie_index]
        profile /= len(valid_indexes)

        ranked = sorted(enumerate(profile), key=lambda pair: pair[1], reverse=True)
        watched_indexes = set(valid_indexes) if exclude_watched else set()

        results: list[dict] = []
        for movie_index, score in ranked:
            if movie_index in watched_indexes:
                continue
            results.append(
                self._format_movie(
                    self.movies.iloc[movie_index],
                    score,
                    "similarity_score",
                )
            )
            if len(results) >= top_n:
                break

        return results

    def recommend_hybrid(
        self,
        movie_ids: list[int],
        genres: list[str],
        top_n: int = 10,
        weight_content: float = 0.7,
        weight_genre: float = 0.3,
    ) -> list[dict]:
        normalized_genres = self.normalize_genres(genres)
        total_weight = weight_content + weight_genre
        if total_weight <= 0:
            weight_content, weight_genre = 0.7, 0.3
        else:
            weight_content = weight_content / total_weight
            weight_genre = weight_genre / total_weight

        valid_indexes = [
            int(self.id_to_index[movie_id])
            for movie_id in dict.fromkeys(movie_ids)
            if movie_id in self.id_to_index.index
        ]

        content_scores = np.zeros(len(self.movies), dtype=np.float64)
        if valid_indexes:
            for movie_index in valid_indexes:
                content_scores += self.cosine_sim[movie_index]
            content_scores /= len(valid_indexes)

        if content_scores.max() > 0:
            content_scores = content_scores / content_scores.max()

        normalized_genre_set = set(normalized_genres)

        def genre_match_score(genre_list: object) -> float:
            if not isinstance(genre_list, list) or not normalized_genre_set:
                return 0.0
            hits = sum(1 for genre in genre_list if genre in normalized_genre_set)
            return min(hits / len(normalized_genre_set), 1.0)

        genre_scores = self.movies["genres_list"].apply(genre_match_score).values

        global_mean = float(self.movies["vote_average"].mean())
        vote_floor = 50
        bayesian = self.movies.apply(
            lambda row: (
                (row["vote_count"] / (row["vote_count"] + vote_floor)) * row["vote_average"]
                + (vote_floor / (row["vote_count"] + vote_floor)) * global_mean
            ),
            axis=1,
        ).values.astype(np.float64)
        bayesian = bayesian / bayesian.max()

        hybrid_scores = (
            weight_content * content_scores + weight_genre * genre_scores
        ) * bayesian

        watched_indexes = set(valid_indexes)
        ranked = sorted(enumerate(hybrid_scores), key=lambda pair: pair[1], reverse=True)

        results: list[dict] = []
        for movie_index, score in ranked:
            if movie_index in watched_indexes:
                continue
            results.append(
                self._format_movie(self.movies.iloc[movie_index], score, "hybrid_score")
            )
            if len(results) >= top_n:
                break

        return results

    def recommend_for_user(
        self,
        movie_ids: list[int],
        genres: list[str],
        top_n: int = 12,
    ) -> tuple[str, str, list[dict]]:
        clean_genres = self.normalize_genres(genres)
        valid_movie_ids = [movie_id for movie_id in dict.fromkeys(movie_ids) if movie_id in self.id_to_index.index]

        if valid_movie_ids and clean_genres:
            return (
                "hybrid",
                "Blending your saved genres with your watch history.",
                self.recommend_hybrid(valid_movie_ids, clean_genres, top_n=top_n),
            )
        if valid_movie_ids:
            return (
                "content_based",
                "Based on the films already in your library.",
                self.recommend_by_history(valid_movie_ids, top_n=top_n),
            )
        if clean_genres:
            return (
                "genre_based",
                "Curated from the genres you selected.",
                self.recommend_by_genres(clean_genres, top_n=top_n),
            )
        return (
            "popular",
            "Popular, highly rated picks to help you get started.",
            self.recommend_popular(top_n=top_n),
        )

    def search_movies(self, query: str, limit: int = 10) -> list[dict]:
        query_text = query.strip().lower()
        if not query_text:
            return []

        escaped_query = re.escape(query_text)
        tokens = [token for token in re.split(r"\s+", query_text) if token]
        candidates = self.movies[
            self.movies["normalized_title"].str.contains(escaped_query, na=False, regex=True)
        ].copy()

        if candidates.empty and tokens:
            candidates = self.movies[
                self.movies["normalized_title"].apply(
                    lambda title: all(token in title for token in tokens)
                )
            ].copy()

        if candidates.empty:
            return []

        candidates["_match_score"] = candidates["normalized_title"].apply(
            lambda title: (
                5 if title == query_text else 0,
                3 if title.startswith(query_text) else 0,
                sum(token in title for token in tokens),
            )
        )
        candidates[["_exact", "_prefix", "_token_hits"]] = pd.DataFrame(
            candidates["_match_score"].tolist(),
            index=candidates.index,
        )
        candidates = candidates.sort_values(
            by=["_exact", "_prefix", "_token_hits", "popularity", "vote_average", "vote_count"],
            ascending=False,
        ).head(limit)

        return [self._format_movie(row) for _, row in candidates.iterrows()]

    def get_all_genres(self) -> list[str]:
        return sorted(self._genre_lookup.values())

    def get_catalog_stats(self) -> dict[str, int | float | list[int] | None]:
        return dict(self._catalog_stats)

    def get_movie_by_id(self, movie_id: int) -> dict | None:
        if movie_id not in self.id_to_index.index:
            return None
        movie_index = int(self.id_to_index[movie_id])
        return self._format_movie(self.movies.iloc[movie_index])
