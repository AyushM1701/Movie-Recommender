"""
Phase 1: Data Acquisition & Preprocessing Pipeline
"""

import pandas as pd
import numpy as np
import ast
import os
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA_DIR  = os.path.join(os.path.dirname(__file__), "..", "data")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")


def safe_literal_eval(val):
    try:
        return ast.literal_eval(val)
    except (ValueError, SyntaxError):
        return []


def extract_names(obj_list, limit=3):
    if isinstance(obj_list, list):
        return [item["name"] for item in obj_list[:limit] if "name" in item]
    return []


def extract_director(crew_list):
    if isinstance(crew_list, list):
        for member in crew_list:
            if member.get("job") == "Director":
                return [member["name"]]
    return []


def collapse_spaces(name_list):
    return [name.replace(" ", "") for name in name_list]


def load_and_preprocess() -> tuple:
    os.makedirs(MODEL_DIR, exist_ok=True)

    # Step 1: Load and merge the datasets
    print("📂 Loading raw datasets...")
    movies  = pd.read_csv(os.path.join(DATA_DIR, "tmdb_5000_movies.csv"))
    credits = pd.read_csv(os.path.join(DATA_DIR, "tmdb_5000_credits.csv"))

    if "movie_id" in credits.columns:
        credits.rename(columns={"movie_id": "id"}, inplace=True)

    movies = movies.merge(credits, on="id")
    print(f"   Merged dataset: {len(movies):,} movies")

    # Step 2: Select the required columns
    movies.rename(columns={"title_x": "title"}, inplace=True)

    # Safely grab poster_path regardless of column name variant
    for col in ["poster_path", "poster_path_x", "poster_path_y"]:
        if col in movies.columns:
            movies["poster_path"] = movies[col].fillna("")
            break
    else:
        movies["poster_path"] = ""

    keep = ["id", "title", "overview", "genres", "keywords",
            "cast", "crew", "vote_average", "vote_count",
            "release_date", "runtime", "popularity", "poster_path"]

    keep = [c for c in keep if c in movies.columns]
    movies = movies[keep].copy()

    # Load pre-fetched poster paths
    poster_csv = os.path.join(DATA_DIR, "poster_paths.csv")
    if os.path.exists(poster_csv):
        poster_df = pd.read_csv(poster_csv)[["id", "poster_path"]]
        poster_df["id"] = poster_df["id"].astype(int)
        movies["id"]    = movies["id"].astype(int)

        poster_df = poster_df[poster_df["poster_path"].notna()]
        poster_df = poster_df[poster_df["poster_path"].astype(str).str.strip() != ""]

        poster_map            = dict(zip(poster_df["id"], poster_df["poster_path"].astype(str).str.strip()))
        movies["poster_path"] = movies["id"].map(poster_map).fillna("")

        found   = movies["poster_path"].astype(bool).sum()
        missing = len(movies) - found
        print(f"   Loaded {found:,} poster paths from poster_paths.csv")
        if missing > 0:
            print(f"   ⚠️  {missing:,} movies have no poster (not on TMDB)")
    else:
        movies["poster_path"] = ""
        print("   ⚠️  poster_paths.csv not found — run fetch_posters_quick.py first")

    movies.dropna(subset=["overview", "genres"], inplace=True)
    movies.reset_index(drop=True, inplace=True)
    print(f"   After cleaning: {len(movies):,} movies remain")

    # Step 3: Parse JSON columns
    for col in ["genres", "keywords", "cast", "crew"]:
        movies[col] = movies[col].apply(safe_literal_eval)

    movies["genres_list"]   = movies["genres"].apply(lambda x: extract_names(x, 5))
    movies["keywords_list"] = movies["keywords"].apply(lambda x: extract_names(x, 10))
    movies["cast_list"]     = movies["cast"].apply(
        lambda x: collapse_spaces(extract_names(x, 3))
    )
    movies["director"]      = movies["crew"].apply(
        lambda x: collapse_spaces(extract_director(x))
    )

    # Step 4: Feature engineering
    def build_tags(row: pd.Series) -> str:
        overview_tokens = (
            row["overview"].lower().split()[:50]
            if isinstance(row["overview"], str) else []
        )
        parts = (
            row["genres_list"]   * 2 +
            row["keywords_list"]     +
            row["cast_list"]         +
            row["director"]          +
            overview_tokens
        )
        return " ".join(parts).lower()

    movies["tags"] = movies.apply(build_tags, axis=1)

    # Filter the final columns needed
    movies_clean = movies[[
        "id", "title", "overview", "genres_list",
        "vote_average", "vote_count", "release_date",
        "runtime", "popularity", "tags", "poster_path"
    ]].copy()

    movies_clean["poster_path"] = movies_clean["poster_path"].fillna("")

    # Step 5: TF-IDF vectorization
    print("🔢 Fitting TF-IDF vectorizer...")
    tfidf = TfidfVectorizer(
        max_features=15_000,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2,
    )
    tfidf_matrix = tfidf.fit_transform(movies_clean["tags"])
    print(f"   TF-IDF matrix shape: {tfidf_matrix.shape}")

    # Step 6: Compute cosine similarity matrix
    print("🔄 Computing cosine similarity matrix (may take ~60s)...")
    cosine_sim = cosine_similarity(tfidf_matrix, tfidf_matrix)
    print(f"   Similarity matrix shape: {cosine_sim.shape}")

    # Step 7: Save all artifacts
    print("💾 Saving model artifacts...")

    indices   = pd.Series(movies_clean.index, index=movies_clean["title"]).drop_duplicates()
    id_to_idx = pd.Series(movies_clean.index, index=movies_clean["id"]).drop_duplicates()

    movies_clean.to_pickle(os.path.join(MODEL_DIR, "movies.pkl"))

    with open(os.path.join(MODEL_DIR, "cosine_sim.pkl"), "wb") as f:
        pickle.dump(cosine_sim, f)

    with open(os.path.join(MODEL_DIR, "indices.pkl"), "wb") as f:
        pickle.dump(indices, f)

    with open(os.path.join(MODEL_DIR, "id_to_index.pkl"), "wb") as f:
        pickle.dump(id_to_idx, f)

    with open(os.path.join(MODEL_DIR, "tfidf_vectorizer.pkl"), "wb") as f:
        pickle.dump(tfidf, f)

    print("\n✅  Preprocessing complete!")
    print(f"   movies.pkl        → {len(movies_clean):,} movies")
    print(f"   cosine_sim.pkl    → {cosine_sim.shape} matrix")
    print(f"   indices.pkl       → title → index map")
    print(f"   id_to_index.pkl   → TMDB ID → index map")
    print(f"   tfidf_vectorizer.pkl → fitted vectorizer")
    print("\n🚀 You can now start the API with: uvicorn main:app --reload")

    return movies_clean, cosine_sim, indices


if __name__ == "__main__":
    load_and_preprocess()