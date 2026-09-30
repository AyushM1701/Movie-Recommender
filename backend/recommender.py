from __future__ import annotations

import json
import math
import os
import pickle
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from backend.artifacts import active_model_dir
from backend.catalog import CatalogRepository, movie_record
from backend.config import settings
from backend.posters import PosterRepository

MODEL_DIR = settings.model_dir
BLOCKED_RELEASE_STATUSES = {"planned", "in production", "post production", "rumored", "canceled"}


class RecommendationEngine:
    """Hybrid sparse, semantic, quality-aware recommendation engine."""

    def __init__(self) -> None:
        self.movies: pd.DataFrame | None = None
        self.indices: pd.Series | None = None
        self.id_to_index: pd.Series | None = None
        self.tfidf_matrix: scipy.sparse.csr_matrix | None = None
        self.tfidf_bundle: dict | None = None
        self.tfidf_vectorizer = None  # Legacy artifact compatibility.
        self.semantic_embeddings: np.ndarray | None = None
        self.semantic_reducer = None
        self.semantic_info: dict = {}
        self._semantic_query_model = None
        self._genre_lookup: dict[str, str] = {}
        self._catalog_stats: dict[str, int | float | list[int] | None] = {}
        self._quality_scores = np.array([], dtype=np.float32)
        self._popularity_scores = np.array([], dtype=np.float32)
        self._novelty_scores = np.array([], dtype=np.float32)
        self._eligible_mask = np.array([], dtype=bool)
        self.catalog_repository: CatalogRepository | None = None
        self.artifact_manifest: dict = {}
        self.poster_repository = PosterRepository()
        try:
            self._load_artifacts()
            self._prepare_indexes()
            catalog_path = self.model_directory / "catalog.sqlite3"
            catalog = CatalogRepository(catalog_path) if catalog_path.exists() else CatalogRepository()
            if catalog.path.exists():
                self.catalog_repository = catalog
        except Exception:
            self.poster_repository.close()
            raise

    @staticmethod
    def _load_pickle(path: os.PathLike) -> object:
        with open(path, "rb") as file_obj:
            return pickle.load(file_obj)

    def _load_artifacts(self) -> None:
        model_dir = active_model_dir(Path(MODEL_DIR))
        self.model_directory = model_dir
        manifest_path = model_dir / "manifest.json"
        if manifest_path.exists():
            self.artifact_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        try:
            self.movies = pd.read_pickle(model_dir / "movies.pkl")
            self.indices = pd.Series(self.movies.index, index=self.movies["title"])
            self.id_to_index = self._load_pickle(model_dir / "id_to_index.pkl")

            matrix_path = model_dir / "tfidf_matrix.npz"
            if os.path.exists(matrix_path):
                self.tfidf_matrix = scipy.sparse.load_npz(matrix_path).tocsr()

            bundle_path = model_dir / "tfidf_bundle.pkl"
            historical_path = model_dir / "tfidf_vectorizer.pkl"
            if os.path.exists(bundle_path):
                loaded = self._load_pickle(bundle_path)
                if isinstance(loaded, dict):
                    self.tfidf_bundle = loaded
            elif os.path.exists(historical_path):
                loaded = self._load_pickle(historical_path)
                if isinstance(loaded, dict):
                    self.tfidf_bundle = loaded
                else:
                    self.tfidf_vectorizer = loaded

            semantic_path = model_dir / "semantic_embeddings.npy"
            if os.path.exists(semantic_path):
                self.semantic_embeddings = np.load(semantic_path, mmap_mode="r")
            reducer_path = model_dir / "semantic_reducer.pkl"
            if os.path.exists(reducer_path):
                self.semantic_reducer = self._load_pickle(reducer_path)
            semantic_info_path = model_dir / "semantic_info.json"
            if os.path.exists(semantic_info_path):
                with open(semantic_info_path, encoding="utf-8") as file_obj:
                    self.semantic_info = json.load(file_obj)
        except FileNotFoundError as exc:  # pragma: no cover - local artifact state
            raise RuntimeError(
                "Model artifacts are missing. Run `python -m backend.data_preprocessing` first."
            ) from exc

    def _prepare_indexes(self) -> None:
        if self.movies is None:
            raise RuntimeError("Movies dataset failed to load.")
        if self.tfidf_matrix is None:
            if self.tfidf_vectorizer is not None and "tags" in self.movies:
                self.tfidf_matrix = self.tfidf_vectorizer.transform(self.movies["tags"].fillna("")).tocsr()
            else:
                raise RuntimeError("TF-IDF recommendation matrix is missing.")
        if self.tfidf_matrix.shape[0] != len(self.movies):
            raise RuntimeError("Movie and TF-IDF artifacts are out of alignment. Rebuild the models.")
        if self.semantic_embeddings is not None and self.semantic_embeddings.shape[0] != len(self.movies):
            raise RuntimeError("Movie and semantic artifacts are out of alignment. Rebuild the models.")
        expected_ids = self.movies["id"].astype(int).to_numpy()
        if (
            len(set(expected_ids)) != len(expected_ids)
            or self.id_to_index is None
            or not np.array_equal(self.id_to_index.index.to_numpy(), expected_ids)
            or not np.array_equal(self.id_to_index.to_numpy(), np.arange(len(expected_ids)))
        ):
            raise RuntimeError("Movie IDs and the lookup mapping are out of alignment. Rebuild the models.")

        self.movies["normalized_title"] = self.movies["title"].fillna("").astype(str).str.lower().str.strip()
        genres = sorted(
            {genre for values in self.movies["genres_list"] if isinstance(values, list) for genre in values}
        )
        self._genre_lookup = {genre.casefold(): genre for genre in genres}
        self._prepare_ranking_signals()

        years = (
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
            "year_range": [int(years.min()), int(years.max())] if not years.empty else None,
        }

    def _prepare_ranking_signals(self) -> None:
        ratings = pd.to_numeric(self.movies["vote_average"], errors="coerce").fillna(0).to_numpy(float)
        votes = pd.to_numeric(self.movies["vote_count"], errors="coerce").fillna(0).to_numpy(float)
        global_mean = float(np.mean(ratings))
        vote_floor = max(100.0, float(np.percentile(votes, 60)))
        bayesian = (votes / (votes + vote_floor)) * ratings + (
            vote_floor / (votes + vote_floor)
        ) * global_mean
        self._quality_scores = np.clip(bayesian / 10.0, 0.0, 1.0).astype(np.float32)

        popularity = pd.to_numeric(self.movies["popularity"], errors="coerce").fillna(0).to_numpy(float)
        popularity = np.log1p(np.maximum(popularity, 0))
        pop_ceiling = float(np.percentile(popularity, 99)) or 1.0
        self._popularity_scores = np.clip(popularity / pop_ceiling, 0.0, 1.0).astype(np.float32)
        self._novelty_scores = (1.0 - self._popularity_scores).astype(np.float32)

        release_dates = pd.to_datetime(self.movies["release_date"], errors="coerce", utc=True)
        cutoff = getattr(self, "artifact_manifest", {}).get("cutoff")
        today = pd.Timestamp(cutoff, tz="UTC") if cutoff else pd.Timestamp.now(tz="UTC").normalize()
        date_eligible = release_dates.isna() | (release_dates <= today)
        if "status" in self.movies:
            statuses = self.movies["status"].fillna("").astype(str).str.casefold()
            status_eligible = ~statuses.isin(BLOCKED_RELEASE_STATUSES)
        else:
            status_eligible = pd.Series(True, index=self.movies.index)
        self._eligible_mask = (date_eligible & status_eligible).to_numpy(bool)

    def _clean_text(self, value: object) -> str:
        if value is None or pd.isna(value):
            return ""
        text = str(value).strip()
        return "" if text.casefold() == "nan" else text

    def _format_movie(
        self,
        row: pd.Series,
        score: float | None = None,
        score_key: str = "similarity_score",
    ) -> dict:
        movie_id = int(row["id"])
        poster_path = self._clean_text(row.get("poster_path")) or self.poster_repository.resolve(movie_id)
        movie = movie_record(row.to_dict())
        movie["poster_path"] = poster_path
        movie["vote_average"] = round(movie["vote_average"], 1)
        movie["popularity"] = round(movie["popularity"], 2)
        if score is not None:
            movie[score_key] = round(float(score), 4)
        return movie

    def normalize_genres(self, genres: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for genre in genres:
            if not genre:
                continue
            canonical = self._genre_lookup.get(genre.strip().casefold())
            if canonical and canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)
        return normalized

    @staticmethod
    def _feature_token(value: str, prefix: str) -> str:
        cleaned = re.sub(r"[^\w]+", "_", value.strip().lower(), flags=re.UNICODE).strip("_")
        return f"{prefix}{cleaned}" if cleaned else ""

    def _transform_query(
        self,
        query: str,
        detected_genres: Iterable[str] = (),
    ) -> tuple[scipy.sparse.csr_matrix | None, np.ndarray | None]:
        sparse_query: scipy.sparse.csr_matrix | None = None
        if self.tfidf_bundle:
            bundle = self.tfidf_bundle
            genre_text = " ".join(self._feature_token(genre, "genre_") for genre in detected_genres)
            keyword_parts = [
                self._feature_token(token, "keyword_")
                for token in re.findall(r"[\w]+", query.lower())
                if len(token) > 1
            ]
            field_text = {
                "genres": genre_text,
                "keywords": " ".join(keyword_parts),
                "overview": query,
                "metadata": "",
            }
            matrices = []
            for field_name in bundle["field_order"]:
                vectorizer = bundle["vectorizers"][field_name]
                matrix = vectorizer.transform([field_text.get(field_name, query)]).astype(np.float32)
                matrices.append(matrix.multiply(float(bundle["field_weights"][field_name])))
            sparse_query = scipy.sparse.hstack(matrices, format="csr", dtype=np.float32)
            sparse_query = normalize(sparse_query, norm="l2", copy=False).tocsr()
        elif self.tfidf_vectorizer is not None:
            sparse_query = self.tfidf_vectorizer.transform([query]).tocsr()

        semantic_query: np.ndarray | None = None
        if sparse_query is not None and self.semantic_reducer is not None:
            semantic_query = self.semantic_reducer.transform(sparse_query).astype(np.float32)
            semantic_query = normalize(semantic_query, norm="l2", copy=False)[0]
        elif self.semantic_info.get("backend") == "sentence-transformers":
            try:
                if self._semantic_query_model is None:
                    from sentence_transformers import SentenceTransformer

                    self._semantic_query_model = SentenceTransformer(self.semantic_info["model_name"])
                semantic_query = self._semantic_query_model.encode(
                    [query],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )[0].astype(np.float32)
            except (ImportError, KeyError):
                semantic_query = None
        return sparse_query, semantic_query

    def _profile_components(
        self,
        positive_indexes: list[int],
        positive_weights: list[float] | None = None,
        negative_indexes: list[int] | None = None,
        negative_weights: list[float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        total = len(self.movies)
        tfidf_scores = np.zeros(total, dtype=np.float32)
        semantic_scores = np.zeros(total, dtype=np.float32)
        if positive_indexes:
            weights = np.asarray(positive_weights or [1.0] * len(positive_indexes), dtype=np.float32)
            weights = np.maximum(weights, 1e-4)
            weights /= weights.sum()
            sparse_profile = (
                scipy.sparse.csr_matrix(weights.reshape(1, -1)) @ self.tfidf_matrix[positive_indexes]
            )
            tfidf_scores = cosine_similarity(sparse_profile, self.tfidf_matrix).ravel().astype(np.float32)
            if self.semantic_embeddings is not None:
                profile = np.average(
                    np.asarray(self.semantic_embeddings[positive_indexes], dtype=np.float32),
                    axis=0,
                    weights=weights,
                )
                norm = float(np.linalg.norm(profile))
                if norm > 0:
                    profile /= norm
                    semantic_scores = np.asarray(self.semantic_embeddings @ profile, dtype=np.float32)

        if negative_indexes:
            neg_weights = np.asarray(
                negative_weights or [1.0] * len(negative_indexes),
                dtype=np.float32,
            )
            neg_weights = np.maximum(neg_weights, 1e-4)
            neg_weights /= neg_weights.sum()
            negative_profile = (
                scipy.sparse.csr_matrix(neg_weights.reshape(1, -1)) @ self.tfidf_matrix[negative_indexes]
            )
            tfidf_scores -= 0.35 * cosine_similarity(negative_profile, self.tfidf_matrix).ravel()
            if self.semantic_embeddings is not None:
                negative_semantic = np.average(
                    np.asarray(self.semantic_embeddings[negative_indexes], dtype=np.float32),
                    axis=0,
                    weights=neg_weights,
                )
                neg_norm = float(np.linalg.norm(negative_semantic))
                if neg_norm > 0:
                    negative_semantic /= neg_norm
                    semantic_scores -= 0.35 * np.asarray(
                        self.semantic_embeddings @ negative_semantic,
                        dtype=np.float32,
                    )

        # Keep negative-only affinities signed so the fallback can demote dislikes.
        return np.clip(tfidf_scores, -1.0, 1.0), np.clip(semantic_scores, -1.0, 1.0)

    def _genre_scores(self, genres: Iterable[str]) -> np.ndarray:
        normalized = set(self.normalize_genres(genres))
        if not normalized:
            return np.zeros(len(self.movies), dtype=np.float32)
        return np.asarray(
            [
                sum(genre in normalized for genre in values) / len(normalized)
                if isinstance(values, list)
                else 0.0
                for values in self.movies["genres_list"]
            ],
            dtype=np.float32,
        )

    def _seed_genres(self, indexes: Iterable[int]) -> list[str]:
        counts: dict[str, int] = {}
        for index in indexes:
            values = self.movies.iloc[index].get("genres_list", [])
            if isinstance(values, list):
                for genre in values:
                    counts[genre] = counts.get(genre, 0) + 1
        return [genre for genre, _ in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)]

    def _content_scores(self, tfidf_scores: np.ndarray, semantic_scores: np.ndarray) -> np.ndarray:
        if self.semantic_embeddings is None:
            return tfidf_scores
        if self.semantic_info.get("backend") == "lsa":
            return 0.65 * tfidf_scores + 0.35 * semantic_scores
        return 0.4 * tfidf_scores + 0.6 * semantic_scores

    def _rank_and_diversify(
        self,
        scores: np.ndarray,
        *,
        top_n: int,
        excluded_indexes: Iterable[int] = (),
        min_score: float = 0.0,
        diversity: float = 0.18,
    ) -> list[int]:
        working = np.asarray(scores, dtype=np.float64).copy()
        working[~self._eligible_mask] = -np.inf
        for index in excluded_indexes:
            if 0 <= index < len(working):
                working[index] = -np.inf

        ordered = np.argsort(working)[::-1]
        ordered = ordered[np.isfinite(working[ordered]) & (working[ordered] > min_score)]
        if ordered.size == 0:
            return []
        pool_size = min(max(top_n * 12, 80), ordered.size)
        candidates = ordered[:pool_size]
        if diversity <= 0 or top_n == 1:
            return candidates[:top_n].tolist()

        relevance = working[candidates]
        low, high = float(relevance.min()), float(relevance.max())
        relevance_norm = (relevance - low) / (high - low) if high > low else np.ones_like(relevance)
        if self.semantic_embeddings is not None:
            vectors = np.asarray(self.semantic_embeddings[candidates], dtype=np.float32)
            pair_similarity = np.clip(vectors @ vectors.T, 0.0, 1.0)
        else:
            pair_similarity = cosine_similarity(self.tfidf_matrix[candidates])

        selected_positions: list[int] = [0]
        remaining = set(range(1, len(candidates)))
        relevance_weight = 1.0 - diversity
        while remaining and len(selected_positions) < top_n:
            best_position = max(
                remaining,
                key=lambda position: (
                    relevance_weight * relevance_norm[position]
                    - diversity * max(pair_similarity[position, selected_positions])
                ),
            )
            selected_positions.append(best_position)
            remaining.remove(best_position)
        return [int(candidates[position]) for position in selected_positions]

    def _format_ranked(
        self,
        indexes: Iterable[int],
        scores: np.ndarray,
        score_key: str,
    ) -> list[dict]:
        return [
            self._format_movie(self.movies.iloc[index], float(scores[index]), score_key) for index in indexes
        ]

    def recommend_popular(self, top_n: int = 10) -> list[dict]:
        scores = 0.72 * self._quality_scores + 0.23 * self._popularity_scores + 0.05 * self._novelty_scores
        indexes = self._rank_and_diversify(scores, top_n=top_n, diversity=0.12)
        return self._format_ranked(indexes, scores, "bayesian_score")

    def recommend_by_genres(
        self,
        genres: list[str],
        top_n: int = 10,
        min_votes: int = 100,
        min_rating: float = 6.0,
    ) -> list[dict]:
        genre_scores = self._genre_scores(genres)
        if not np.any(genre_scores):
            return []
        ratings = pd.to_numeric(self.movies["vote_average"], errors="coerce").fillna(0).to_numpy(float)
        votes = pd.to_numeric(self.movies["vote_count"], errors="coerce").fillna(0).to_numpy(float)
        valid = (genre_scores > 0) & (votes >= min_votes) & (ratings >= min_rating)
        scores = 0.68 * genre_scores + 0.27 * self._quality_scores + 0.05 * self._novelty_scores
        scores = np.where(valid, scores, -np.inf)
        indexes = self._rank_and_diversify(scores, top_n=top_n, diversity=0.2)
        return self._format_ranked(indexes, scores, "bayesian_score")

    def _valid_seed_indexes(self, movie_ids: Iterable[int]) -> tuple[list[int], list[int]]:
        valid_ids = [
            int(movie_id) for movie_id in dict.fromkeys(movie_ids) if movie_id in self.id_to_index.index
        ]
        return valid_ids, [int(self.id_to_index[movie_id]) for movie_id in valid_ids]

    def recommend_by_history(
        self,
        movie_ids: list[int],
        top_n: int = 10,
        exclude_watched: bool = True,
    ) -> list[dict]:
        _, indexes = self._valid_seed_indexes(movie_ids)
        if not indexes:
            return []
        tfidf_scores, semantic_scores = self._profile_components(indexes)
        content = self._content_scores(tfidf_scores, semantic_scores)
        genres = self._genre_scores(self._seed_genres(indexes))
        scores = 0.73 * content + 0.14 * genres + 0.1 * self._quality_scores + 0.03 * self._novelty_scores
        excluded = indexes if exclude_watched else []
        ranked = self._rank_and_diversify(
            scores,
            top_n=top_n,
            excluded_indexes=excluded,
            min_score=0.03,
            diversity=0.18,
        )
        return self._format_ranked(ranked, scores, "similarity_score")

    def recommend_hybrid(
        self,
        movie_ids: list[int],
        genres: list[str],
        top_n: int = 10,
        weight_content: float = 0.7,
        weight_genre: float = 0.3,
    ) -> list[dict]:
        _, indexes = self._valid_seed_indexes(movie_ids)
        normalized_genres = self.normalize_genres(genres)
        if not indexes and not normalized_genres:
            return []
        tfidf_scores, semantic_scores = self._profile_components(indexes)
        content = self._content_scores(tfidf_scores, semantic_scores)
        genre_scores = self._genre_scores(normalized_genres)
        if not indexes:
            weight_content = 0.0
        if not normalized_genres:
            weight_genre = 0.0
        total_weight = weight_content + weight_genre
        if not math.isfinite(total_weight) or total_weight <= 0:
            return []
        weight_content /= total_weight
        weight_genre /= total_weight
        relevance = weight_content * content + weight_genre * genre_scores
        scores = 0.86 * relevance + 0.1 * self._quality_scores + 0.04 * self._novelty_scores
        if not indexes:
            scores = np.where(genre_scores > 0, scores, -np.inf)
        ranked = self._rank_and_diversify(
            scores,
            top_n=top_n,
            excluded_indexes=indexes,
            min_score=0.03,
            diversity=0.2,
        )
        return self._format_ranked(ranked, scores, "hybrid_score")

    @staticmethod
    def _coerce_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    def _personalized_seed_weights(
        self,
        movie_ids: list[int],
        ratings: dict[int, float | None],
        watched_at: dict[int, object],
    ) -> tuple[list[int], list[float], list[int], list[float]]:
        positive_indexes: list[int] = []
        positive_weights: list[float] = []
        negative_indexes: list[int] = []
        negative_weights: list[float] = []
        now = datetime.now(UTC)
        for movie_id in dict.fromkeys(movie_ids):
            if movie_id not in self.id_to_index.index:
                continue
            index = int(self.id_to_index[movie_id])
            watched = self._coerce_datetime(watched_at.get(movie_id))
            age_days = max((now - watched).total_seconds() / 86400.0, 0.0) if watched else 365.0
            recency = 0.65 + 0.35 * math.exp(-age_days / 730.0)
            rating = ratings.get(movie_id)
            if rating is None:
                positive_indexes.append(index)
                positive_weights.append(0.6 * recency)
            elif rating < 3.0:
                negative_indexes.append(index)
                negative_weights.append(((3.0 - float(rating)) / 2.0) * recency)
            else:
                preference = 0.25 + 0.75 * ((float(rating) - 3.0) / 2.0)
                positive_indexes.append(index)
                positive_weights.append(max(preference, 0.2) * recency)
        return positive_indexes, positive_weights, negative_indexes, negative_weights

    def recommend_for_user(
        self,
        movie_ids: list[int],
        genres: list[str],
        top_n: int = 12,
        *,
        ratings: dict[int, float | None] | None = None,
        watched_at: dict[int, object] | None = None,
        exclude_watched: bool = True,
        excluded_movie_ids: Iterable[int] | None = None,
    ) -> tuple[str, str, list[dict]]:
        valid_ids, all_indexes = self._valid_seed_indexes(movie_ids)
        _, complete_exclusions = self._valid_seed_indexes(excluded_movie_ids or ())
        excluded = sorted(set(all_indexes + complete_exclusions)) if exclude_watched else []
        clean_genres = self.normalize_genres(genres)
        positive, positive_weights, negative, negative_weights = self._personalized_seed_weights(
            valid_ids,
            ratings or {},
            watched_at or {},
        )
        if positive:
            tfidf_scores, semantic_scores = self._profile_components(
                positive,
                positive_weights,
                negative,
                negative_weights,
            )
            content = self._content_scores(tfidf_scores, semantic_scores)
            genre_scores = self._genre_scores(clean_genres or self._seed_genres(positive))
            genre_weight = 0.18 if clean_genres else 0.1
            scores = (
                (0.77 - genre_weight) * content
                + genre_weight * genre_scores
                + 0.1 * self._quality_scores
                + 0.03 * self._novelty_scores
            )
            ranked = self._rank_and_diversify(
                scores,
                top_n=top_n,
                excluded_indexes=excluded,
                min_score=0.03,
                diversity=0.22,
            )
            strategy = "hybrid" if clean_genres else "content_based"
            reason = (
                "Weighted by your ratings, viewing recency, saved genres, and watch history."
                if clean_genres
                else "Weighted by your ratings, viewing recency, and watch history."
            )
            return strategy, reason, self._format_ranked(ranked, scores, "hybrid_score")
        if clean_genres:
            genre_scores = self._genre_scores(clean_genres)
            scores = 0.68 * genre_scores + 0.27 * self._quality_scores + 0.05 * self._novelty_scores
            scores = np.where(genre_scores > 0, scores, -np.inf)
            strategy = "genre_based"
            reason = "Curated from the genres you selected."
        else:
            scores = (
                0.72 * self._quality_scores + 0.23 * self._popularity_scores + 0.05 * self._novelty_scores
            )
            strategy = "popular"
            reason = "Popular, highly rated picks to help you get started."
        if negative:
            sparse_penalty, semantic_penalty = self._profile_components(
                [],
                negative_indexes=negative,
                negative_weights=negative_weights,
            )
            scores += self._content_scores(sparse_penalty, semantic_penalty)
            reason = "Starting from your genres and catalog quality while avoiding content similar to your dislikes."
            strategy = "negative_profile"
        ranked = self._rank_and_diversify(
            scores,
            top_n=top_n,
            excluded_indexes=excluded,
            diversity=0.2,
        )
        return strategy, reason, self._format_ranked(ranked, scores, "hybrid_score")

    def _detect_query_genres(self, query_text: str) -> list[str]:
        query_lower = query_text.casefold()
        detected: list[str] = []
        for canonical in self._genre_lookup.values():
            if re.search(rf"\b{re.escape(canonical.casefold())}\b", query_lower):
                detected.append(canonical)
        if (
            any(term in query_lower for term in ("sci-fi", "scifi", "sci fi"))
            and "Science Fiction" in self._genre_lookup.values()
            and "Science Fiction" not in detected
        ):
            detected.append("Science Fiction")
        return detected

    def search_movies(self, query: str, limit: int = 12) -> dict:
        query_text = query.strip()
        if not query_text:
            return {
                "query": query,
                "match_type": "title_match",
                "exact_match": False,
                "message": None,
                "detected_genres": [],
                "count": 0,
                "movies": [],
            }

        query_clean = query_text.casefold()
        if self.catalog_repository is not None:
            catalog_matches = self.catalog_repository.search_titles(query_text, limit=limit)
            if catalog_matches:
                return {
                    "query": query_text,
                    "match_type": "title_match",
                    "exact_match": any(
                        item["title"].casefold().strip() == query_clean for item in catalog_matches
                    ),
                    "message": f'Found {len(catalog_matches)} catalog matches for "{query_text}".',
                    "detected_genres": [],
                    "count": len(catalog_matches),
                    "movies": catalog_matches,
                }
        tokens = [token for token in re.split(r"\s+", query_clean) if len(token) > 1]
        escaped = re.escape(query_clean)
        candidates = self.movies[
            self.movies["normalized_title"].str.contains(escaped, na=False, regex=True)
        ].copy()
        if candidates.empty and tokens:
            candidates = self.movies[
                self.movies["normalized_title"].apply(lambda title: all(token in title for token in tokens))
            ].copy()
        if not candidates.empty:
            candidates["_exact"] = (candidates["normalized_title"] == query_clean).astype(int)
            candidates["_prefix"] = candidates["normalized_title"].str.startswith(query_clean).astype(int)
            candidates["_token_hits"] = candidates["normalized_title"].apply(
                lambda title: sum(token in title for token in tokens)
            )
            candidates = candidates.sort_values(
                by=["_exact", "_prefix", "_token_hits", "popularity", "vote_average", "vote_count"],
                ascending=False,
            ).head(limit)
            movies = [self._format_movie(row) for _, row in candidates.iterrows()]
            return {
                "query": query_text,
                "match_type": "title_match",
                "exact_match": bool(candidates["_exact"].any()),
                "message": f'Found {len(movies)} catalog match{"es" if len(movies) != 1 else ""} for "{query_text}".',
                "detected_genres": [],
                "count": len(movies),
                "movies": movies,
            }

        detected_genres = self._detect_query_genres(query_text)
        sparse_query, semantic_query = self._transform_query(query_text, detected_genres)
        tfidf_scores = np.zeros(len(self.movies), dtype=np.float32)
        if sparse_query is not None and sparse_query.nnz:
            tfidf_scores = (self.tfidf_matrix @ sparse_query.T).toarray().ravel().astype(np.float32)
        semantic_scores = np.zeros(len(self.movies), dtype=np.float32)
        if semantic_query is not None and self.semantic_embeddings is not None:
            semantic_scores = np.asarray(self.semantic_embeddings @ semantic_query, dtype=np.float32)
            semantic_scores = np.clip(semantic_scores, 0.0, 1.0)
        genre_scores = self._genre_scores(detected_genres)

        relevance_mask = (tfidf_scores > 0) | (semantic_scores > 0.1) | (genre_scores > 0)
        if np.any(relevance_mask):
            scores = (
                0.25 * tfidf_scores
                + 0.48 * semantic_scores
                + 0.15 * genre_scores
                + 0.1 * self._quality_scores
                + 0.02 * self._novelty_scores
            )
            scores = np.where(relevance_mask, scores, -np.inf)
        else:
            return {
                "query": query_text,
                "match_type": "no_match",
                "exact_match": False,
                "message": f'No title or meaningful theme matches for "{query_text}". Try a title, genre, or plot description.',
                "detected_genres": detected_genres,
                "count": 0,
                "movies": [],
            }
        ranked = self._rank_and_diversify(scores, top_n=limit, min_score=0.01, diversity=0.18)
        movies = self._format_ranked(ranked, scores, "similarity_score")
        genre_suffix = f" with {' & '.join(detected_genres)} signals" if detected_genres else ""
        return {
            "query": query_text,
            "match_type": "theme_genre_match",
            "exact_match": False,
            "message": f'No exact title match for "{query_text}". Showing the closest thematic matches{genre_suffix}.',
            "detected_genres": detected_genres,
            "count": len(movies),
            "movies": movies,
        }

    def get_all_genres(self) -> list[str]:
        return sorted(self._genre_lookup.values())

    def get_catalog_stats(self) -> dict[str, int | float | list[int] | None]:
        if self.catalog_repository is not None:
            return self.catalog_repository.stats()
        return dict(self._catalog_stats)

    def get_movie_by_id(self, movie_id: int) -> dict | None:
        if movie_id not in self.id_to_index.index:
            return (
                self.catalog_repository.get_movie(movie_id) if self.catalog_repository is not None else None
            )
        return self._format_movie(self.movies.iloc[int(self.id_to_index[movie_id])])

    def get_similar_movies(self, movie_id: int, top_n: int = 6) -> list[dict]:
        if movie_id not in self.id_to_index.index:
            return []
        index = int(self.id_to_index[movie_id])
        tfidf_scores, semantic_scores = self._profile_components([index])
        content = self._content_scores(tfidf_scores, semantic_scores)
        genre_scores = self._genre_scores(self._seed_genres([index]))
        scores = (
            0.82 * content + 0.06 * genre_scores + 0.1 * self._quality_scores + 0.02 * self._novelty_scores
        )
        ranked = self._rank_and_diversify(
            scores,
            top_n=top_n,
            excluded_indexes=[index],
            min_score=0.03,
            diversity=0.16,
        )
        return self._format_ranked(ranked, scores, "similarity_score")

    def get_explore_catalog(self) -> dict:
        scored = self.movies[self._eligible_mask].copy()
        eligible_indexes = scored.index.to_numpy(int)
        scored["_quality"] = self._quality_scores[eligible_indexes]
        scored["_popularity"] = self._popularity_scores[eligible_indexes]
        scored["_explore"] = 0.7 * scored["_quality"] + 0.3 * scored["_popularity"]

        trending_df = (
            scored[scored["vote_count"] >= 100]
            .sort_values(by=["_popularity", "_quality"], ascending=False)
            .head(20)
        )
        top_rated_df = (
            scored[scored["vote_count"] >= 250]
            .sort_values(by=["_quality", "vote_average"], ascending=False)
            .head(20)
        )
        trending = [
            self._format_movie(row, row["_explore"], "bayesian_score") for _, row in trending_df.iterrows()
        ]
        top_rated = [
            self._format_movie(row, row["_quality"], "bayesian_score") for _, row in top_rated_df.iterrows()
        ]

        years = (
            scored["release_date"]
            .fillna("")
            .astype(str)
            .str.extract(r"(?P<year>\d{4})")["year"]
            .fillna("0")
            .astype(int)
        )
        scored["_year"] = years
        decades = {
            "Before 1970": (0, 1969),
            "1970s": (1970, 1979),
            "1980s": (1980, 1989),
            "1990s": (1990, 1999),
            "2000s": (2000, 2009),
            "2010s": (2010, 2019),
            "2020s": (2020, 2029),
        }
        by_decade: dict[str, list[dict]] = {}
        for label, (start, end) in decades.items():
            matches = (
                scored[(scored["_year"] >= start) & (scored["_year"] <= end) & (scored["vote_count"] >= 50)]
                .sort_values(by=["_explore", "popularity"], ascending=False)
                .head(12)
            )
            if not matches.empty:
                by_decade[label] = [
                    self._format_movie(row, row["_explore"], "bayesian_score")
                    for _, row in matches.iterrows()
                ]
        return {"trending": trending, "top_rated": top_rated, "by_decade": by_decade}

    def close(self) -> None:
        self.poster_repository.close()
        mapped = getattr(self.semantic_embeddings, "_mmap", None)
        self.semantic_embeddings = None
        if mapped is not None:
            mapped.close()
