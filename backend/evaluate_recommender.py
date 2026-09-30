"""Offline quality evaluation for CineMatch recommendation artifacts."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

os.environ.setdefault("CINEMATCH_ENABLE_POSTER_LOOKUP", "0")

from backend.recommender import RecommendationEngine  # noqa: E402


def set_jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def attribute_relevance(source: pd.Series, target: pd.Series) -> float:
    source_genres = set(source.get("genres_list", []) or [])
    target_genres = set(target.get("genres_list", []) or [])
    source_keywords = set(source.get("keywords_list", []) or [])
    target_keywords = set(target.get("keywords_list", []) or [])
    genre_score = set_jaccard(source_genres, target_genres)
    keyword_score = set_jaccard(source_keywords, target_keywords)
    return 0.68 * genre_score + 0.32 * keyword_score


def dcg(grades: list[float]) -> float:
    return sum((2.0**grade - 1.0) / math.log2(position + 2) for position, grade in enumerate(grades))


def evaluate_catalog(
    engine: RecommendationEngine, sample_size: int, top_k: int, seed: int, strategy: str = "hybrid"
) -> dict:
    if sample_size < 1 or top_k < 1:
        raise ValueError("Sample size and top K must be positive.")
    if strategy not in {"hybrid", "popularity", "genre"}:
        raise ValueError("Unknown evaluation strategy.")
    rng = np.random.default_rng(seed)
    eligible = np.flatnonzero(engine._eligible_mask)
    sample = rng.choice(eligible, size=min(sample_size, len(eligible)), replace=False)
    attributes = [
        (set(genres or []), set(keywords or []))
        for genres, keywords in engine.movies[["genres_list", "keywords_list"]].itertuples(
            index=False, name=None
        )
    ]

    id_to_index = {int(movie_id): int(index) for movie_id, index in engine.id_to_index.items()}
    hits: list[float] = []
    recalls: list[float] = []
    precisions: list[float] = []
    ndcgs: list[float] = []
    shared_genres: list[float] = []
    list_diversities: list[float] = []
    recommended_indexes: list[int] = []

    for source_index in sample:
        source = engine.movies.iloc[int(source_index)]
        if strategy == "popularity":
            recommendations = engine.recommend_popular(top_n=top_k + 1)
        elif strategy == "genre":
            recommendations = engine.recommend_by_genres(source["genres_list"], top_n=top_k + 1, min_votes=0)
        else:
            recommendations = engine.get_similar_movies(int(source["id"]), top_n=top_k)
        predicted = list(
            dict.fromkeys(
                id_to_index[item["id"]]
                for item in recommendations
                if item["id"] in id_to_index and id_to_index[item["id"]] != source_index
            )
        )[:top_k]
        recommended_indexes.extend(predicted)

        grades = [attribute_relevance(source, engine.movies.iloc[index]) for index in predicted]
        relevant_hits = [grade >= 0.28 for grade in grades]
        hits.append(float(any(relevant_hits)))
        shared_genres.extend(
            float(bool(set(source["genres_list"]) & set(engine.movies.iloc[index]["genres_list"])))
            for index in predicted
        )

        all_grades = np.asarray(
            [
                0.68 * set_jaccard(attributes[source_index][0], attributes[index][0])
                + 0.32 * set_jaccard(attributes[source_index][1], attributes[index][1])
                if index != source_index
                else 0.0
                for index in eligible
            ],
            dtype=np.float32,
        )
        relevant_total = int(np.count_nonzero(all_grades >= 0.28))
        recalls.append(sum(relevant_hits) / max(1, relevant_total))
        precisions.append(sum(relevant_hits) / top_k)
        ideal = np.sort(all_grades)[::-1][:top_k].tolist()
        ideal_dcg = dcg(ideal)
        ndcgs.append(dcg(grades) / ideal_dcg if ideal_dcg else 0.0)

        if len(predicted) > 1:
            if engine.semantic_embeddings is not None:
                vectors = np.asarray(engine.semantic_embeddings[predicted], dtype=np.float32)
                similarities = np.clip(vectors @ vectors.T, 0.0, 1.0)
            else:
                similarities = cosine_similarity(engine.tfidf_matrix[predicted])
            upper = similarities[np.triu_indices_from(similarities, k=1)]
            list_diversities.append(float(1.0 - upper.mean()))

    unique_recommendations = set(recommended_indexes)
    metrics = {
        "evaluation_type": "attribute_proxy_not_human_relevance",
        "strategy": strategy,
        "pipeline_version": int((engine.tfidf_bundle or {}).get("pipeline_version", 1)),
        "semantic_backend": engine.semantic_info.get("backend", "none"),
        "catalog_movies": int(len(engine.movies)),
        "eligible_movies": int(engine._eligible_mask.sum()),
        "sample_movies": int(len(sample)),
        "top_k": int(top_k),
        "hit_rate_at_k": round(float(np.mean(hits)), 4) if hits else 0.0,
        "attribute_recall_at_k": round(float(np.mean(recalls)), 4) if recalls else 0.0,
        "attribute_precision_at_k": round(float(np.mean(precisions)), 4) if precisions else 0.0,
        "attribute_ndcg_at_k": round(float(np.mean(ndcgs)), 4) if ndcgs else 0.0,
        "shared_genre_rate": round(float(np.mean(shared_genres)), 4) if shared_genres else 0.0,
        "intra_list_diversity": round(float(np.mean(list_diversities)), 4) if list_diversities else 0.0,
        "catalog_coverage": round(len(unique_recommendations) / max(int(engine._eligible_mask.sum()), 1), 4),
        "mean_quality": round(float(np.mean(engine._quality_scores[list(unique_recommendations)])), 4)
        if unique_recommendations
        else 0.0,
        "mean_novelty": round(float(np.mean(engine._novelty_scores[list(unique_recommendations)])), 4)
        if unique_recommendations
        else 0.0,
    }
    return metrics


def evaluate_comparison(engine: RecommendationEngine, sample_size: int, top_k: int, seed: int) -> dict:
    """Use identical seeded samples and eligible relevance pools for each strategy."""
    return {
        strategy: evaluate_catalog(engine, sample_size, top_k, seed, strategy)
        for strategy in ("hybrid", "popularity", "genre")
    }


def evaluate_interactions(engine: RecommendationEngine, csv_path: Path, top_k: int) -> dict:
    interactions = pd.read_csv(csv_path)
    required = {"user_id", "movie_id"}
    if not required.issubset(interactions.columns):
        raise ValueError(f"Interaction CSV must contain columns: {sorted(required)}")
    interactions = interactions[interactions["movie_id"].isin(engine.id_to_index.index)].copy()
    sort_column = "watched_at" if "watched_at" in interactions else None

    hits: list[float] = []
    reciprocal_ranks: list[float] = []
    for _, group in interactions.groupby("user_id"):
        if len(group) < 3:
            continue
        if sort_column:
            group = group.sort_values(sort_column)
        held_out = int(group.iloc[-1]["movie_id"])
        history = group.iloc[:-1]
        ratings = {
            int(row.movie_id): float(row.rating)
            for row in history.itertuples()
            if hasattr(row, "rating") and pd.notna(row.rating)
        }
        watched_at = {
            int(row.movie_id): row.watched_at for row in history.itertuples() if hasattr(row, "watched_at")
        }
        _, _, recommendations = engine.recommend_for_user(
            [int(value) for value in history["movie_id"]],
            [],
            top_n=top_k,
            ratings=ratings,
            watched_at=watched_at,
        )
        ids = [item["id"] for item in recommendations]
        hits.append(float(held_out in ids))
        reciprocal_ranks.append(1.0 / (ids.index(held_out) + 1) if held_out in ids else 0.0)

    return {
        "evaluated_users": len(hits),
        "leave_one_out_recall_at_k": round(float(np.mean(hits)), 4) if hits else 0.0,
        "mean_reciprocal_rank": round(float(np.mean(reciprocal_ranks)), 4) if hits else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interactions-csv", type=Path)
    parser.add_argument("--compare-baselines", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = RecommendationEngine()
    try:
        report = evaluate_catalog(
            engine,
            sample_size=max(args.sample_size, 1),
            top_k=max(args.top_k, 1),
            seed=args.seed,
        )
        if args.compare_baselines:
            report["baseline_comparison"] = evaluate_comparison(
                engine, max(args.sample_size, 1), max(args.top_k, 1), args.seed
            )
        if args.interactions_csv:
            report["interaction_metrics"] = evaluate_interactions(
                engine,
                args.interactions_csv,
                max(args.top_k, 1),
            )
        rendered = json.dumps(report, indent=2)
        print(rendered)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
