"""Build CineMatch's sparse retrieval and semantic recommendation artifacts."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

try:
    from .artifacts import activate_generation, checksum, write_manifest
    from .catalog import publish_catalog
    from .fetch_latest_movies import active_refresh_dir
except ImportError:
    from artifacts import activate_generation, checksum, write_manifest
    from catalog import publish_catalog
    from fetch_latest_movies import active_refresh_dir


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODEL_DIR = PROJECT_ROOT / "models"
PIPELINE_VERSION = 3

FIELD_WEIGHTS = {
    "genres": 0.75,
    "keywords": 1.0,
    "overview": 1.8,
    "metadata": 0.8,
}

CORE_COLUMNS = [
    "id",
    "title",
    "vote_average",
    "vote_count",
    "release_date",
    "runtime",
    "overview",
    "popularity",
    "poster_path",
    "genres",
    "keywords",
]
OPTIONAL_COLUMNS = [
    "status",
    "tagline",
    "original_language",
    "production_companies",
    "backdrop_path",
    "adult",
    "video",
]
ALL_COLUMNS = CORE_COLUMNS + OPTIONAL_COLUMNS


def clean_csv_list(value: object, limit: int = 10) -> list[str]:
    """Parse TMDB JSON arrays and the simpler comma-separated refresh format."""
    if not isinstance(value, str) or not value.strip():
        return []

    stripped = value.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                results: list[str] = []
                for item in parsed:
                    name = item.get("name") if isinstance(item, dict) else item
                    if isinstance(name, str) and name.strip():
                        results.append(name.strip())
                return results[:limit]
        except (json.JSONDecodeError, TypeError):
            pass

    return [item.strip() for item in stripped.split(",") if item.strip()][:limit]


def feature_token(value: object, prefix: str = "") -> str:
    cleaned = re.sub(r"[^\w]+", "_", str(value).strip().lower(), flags=re.UNICODE).strip("_")
    return f"{prefix}{cleaned}" if cleaned else ""


def parse_credit_names(value: object, *, crew_job: str | None = None, limit: int = 5) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []

    names: list[str] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if crew_job and str(item.get("job", "")).casefold() != crew_job.casefold():
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
        if len(names) >= limit:
            break
    return names


def load_movie_source() -> pd.DataFrame:
    """Load compact seed or chunk raw source; always retain eligible history and recent titles."""
    print("Loading versioned catalog sources...")
    seed = DATA_DIR / "catalog_seed_v1.csv.gz"
    raw = DATA_DIR / "TMDB_movie_dataset_v11.csv"
    provenance = {"cutoff": "2026-09-30", "coverage": "limited_offline", "sources": []}
    frames = []
    if seed.exists():
        manifest_path = DATA_DIR / "catalog_seed_v1.json"
        if not manifest_path.exists():
            raise RuntimeError("Catalog seed manifest is missing.")
        provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
        if checksum(seed) != provenance["seed_sha256"]:
            raise RuntimeError("Catalog seed checksum mismatch.")
        frames.append(pd.read_csv(seed, keep_default_na=False, low_memory=False))
    elif raw.exists():
        for chunk in pd.read_csv(raw, usecols=lambda name: name in ALL_COLUMNS, chunksize=100_000):
            votes = pd.to_numeric(chunk.get("vote_count", 0), errors="coerce").fillna(0)
            recent = chunk["release_date"].fillna("").between("2026-01-01", "2026-09-30")
            frames.append(chunk[(votes >= 100) | recent].copy())
        provenance["coverage"] = "local_historical_plus_recent_source_not_live_verified"
        provenance["sources"].append({"name": raw.name, "sha256": checksum(raw)})
    historical = DATA_DIR / "tmdb_5000_movies.csv"
    if historical.exists():
        frames.insert(0, pd.read_csv(historical, usecols=lambda name: name in ALL_COLUMNS))
        provenance["sources"].append({"name": historical.name, "sha256": checksum(historical)})
    active = active_refresh_dir(DATA_DIR)
    supplements = [DATA_DIR / "tmdb_latest_movies.csv"]
    if active:
        supplements.append(active / "movies.csv")
        coverage = json.loads((active / "coverage.json").read_text(encoding="utf-8"))
        for name, expected in coverage["checksums"].items():
            if checksum(active / name) != expected:
                raise RuntimeError("Refresh snapshot checksum failed.")
        provenance.update(
            {
                "refresh": coverage,
                "coverage": "live_verified_date_scope",
                "retrieved_at": coverage["retrieved_at"],
                "catalog_generation": coverage["generation"],
            }
        )
    for supplement in supplements:
        if supplement.exists() and supplement.stat().st_size > 2:
            try:
                frame = pd.read_csv(supplement, usecols=lambda name: name in ALL_COLUMNS)
                if {"id", "title"} <= set(frame):
                    frames.append(frame)
                    provenance["sources"].append({"name": supplement.name, "sha256": checksum(supplement)})
            except pd.errors.EmptyDataError:
                print("Ignoring empty legacy supplement; valid sources retained.")
    if not frames:
        raise RuntimeError(
            "No movie data provisioned; supply catalog_seed_v1 or the tracked TMDB 5000 offline source."
        )
    movies = pd.concat(frames, ignore_index=True)
    credits_by_id = {}
    for row in movies.to_dict("records"):
        movie_id = pd.to_numeric(row.get("id"), errors="coerce")
        if pd.isna(movie_id):
            continue
        known = credits_by_id.setdefault(int(movie_id), {"cast": "[]", "crew": "[]"})
        for field in ("cast", "crew"):
            if parse_credit_names(row.get(field), limit=1):
                known[field] = row[field]
    for column in ALL_COLUMNS:
        if column not in movies:
            movies[column] = ""
    movies["id"] = pd.to_numeric(movies["id"], errors="coerce")
    movies = movies.dropna(subset=["id", "title"])
    movies = movies[movies["title"].astype(str).str.strip().ne("")].copy()
    movies["id"] = movies["id"].astype(int)
    movies = movies.drop_duplicates("id", keep="last").reset_index(drop=True)
    # Upgrade older compact seeds that did not carry the source adult flag.
    if seed.exists() and raw.exists() and "adult" not in frames[1 if historical.exists() else 0].columns:
        wanted = set(movies["id"])
        adult_ids = set()
        for chunk in pd.read_csv(raw, usecols=["id", "adult"], chunksize=100_000):
            adult_ids.update(
                chunk.loc[
                    chunk["adult"].astype(str).str.casefold().isin(("true", "1")) & chunk["id"].isin(wanted),
                    "id",
                ].astype(int)
            )
        movies["adult"] = movies["adult"].astype(object)
        movies.loc[movies["id"].isin(adult_ids), "adult"] = "True"
    adult = movies["adult"].fillna(False).astype(str).str.casefold().isin(("true", "1"))
    video = movies["video"].fillna(False).astype(str).str.casefold().isin(("true", "1"))
    provenance["excluded_adult_or_video"] = int((adult | video).sum())
    movies = movies[~(adult | video)].copy().reset_index(drop=True)
    # Seed stores normalized historical metadata, then good refreshed fields supersede it.
    credit_sources = [DATA_DIR / "tmdb_5000_credits.csv", DATA_DIR / "tmdb_latest_credits.csv"]
    if active:
        credit_sources.append(active / "credits.csv")
    for path in credit_sources:
        if not path.exists() or path.stat().st_size <= 2:
            continue
        frame = pd.read_csv(path, usecols=lambda name: name in ("movie_id", "cast", "crew"))
        if "movie_id" not in frame:
            continue
        for row in frame.to_dict("records"):
            if pd.isna(row["movie_id"]):
                continue
            known = credits_by_id.setdefault(int(row["movie_id"]), {"cast": "[]", "crew": "[]"})
            for field in ("cast", "crew"):
                if parse_credit_names(row.get(field), limit=1):
                    known[field] = row[field]
        provenance["sources"].append({"name": path.name, "sha256": checksum(path)})
    for field in ("cast", "crew"):
        movies[field] = movies["id"].apply(
            lambda movie_id, field=field: credits_by_id.get(movie_id, {}).get(field, "[]")
        )
    movies["cast_list"] = movies["cast"].apply(lambda value: parse_credit_names(value, limit=5))
    movies["director_list"] = movies["crew"].apply(
        lambda value: parse_credit_names(value, crew_job="Director", limit=2)
    )
    movies.attrs["provenance"] = provenance
    return movies


def build_feature_columns(movies: pd.DataFrame) -> pd.DataFrame:
    movies["genres_list"] = movies["genres"].apply(lambda value: clean_csv_list(value, 8))
    movies["keywords_list"] = movies["keywords"].apply(lambda value: clean_csv_list(value, 20))
    movies["production_companies_list"] = movies["production_companies"].apply(
        lambda value: clean_csv_list(value, 5)
    )

    movies["genre_text"] = movies["genres_list"].apply(
        lambda values: " ".join(filter(None, (feature_token(value, "genre_") for value in values)))
    )

    def keyword_text(values: list[str]) -> str:
        tokens: list[str] = []
        for value in values:
            full_token = feature_token(value, "keyword_")
            if full_token:
                tokens.append(full_token)
            tokens.extend(
                feature_token(part, "keyword_")
                for part in re.findall(r"[\w]+", value.lower())
                if len(part) > 1
            )
        return " ".join(filter(None, tokens))

    movies["keyword_text"] = movies["keywords_list"].apply(keyword_text)
    movies["overview_text"] = (
        movies["overview"].fillna("").astype(str).str.strip()
        + " "
        + movies["tagline"].fillna("").astype(str).str.strip()
    ).str.strip()

    def metadata_text(row: pd.Series) -> str:
        tokens = [feature_token(row.get("original_language", ""), "language_")]
        tokens.extend(feature_token(value, "company_") for value in row["production_companies_list"])
        tokens.extend(feature_token(value, "cast_") for value in row["cast_list"])
        tokens.extend(feature_token(value, "director_") for value in row["director_list"])
        return " ".join(filter(None, tokens))

    movies["metadata_text"] = movies.apply(metadata_text, axis=1)
    movies["semantic_text"] = movies.apply(
        lambda row: (
            f"{row['title']}. Genres: {', '.join(row['genres_list'])}. "
            f"Themes: {', '.join(row['keywords_list'])}. "
            f"{row['overview_text']}"
        ).strip(),
        axis=1,
    )
    # Retained for human inspection and the low-tech search fallback.
    movies["tags"] = (
        movies["genre_text"]
        + " "
        + movies["keyword_text"]
        + " "
        + movies["overview_text"]
        + " "
        + movies["metadata_text"]
    ).str.strip()
    return movies


def build_weighted_tfidf(movies: pd.DataFrame) -> tuple[scipy.sparse.csr_matrix, dict]:
    print("Fitting field-specific TF-IDF vectorizers...")
    vectorizers = {
        "genres": TfidfVectorizer(
            max_features=512,
            min_df=1,
            ngram_range=(1, 1),
            token_pattern=r"(?u)\b[\w_]+\b",
            lowercase=False,
            binary=True,
            dtype=np.float32,
        ),
        "keywords": TfidfVectorizer(
            max_features=15_000,
            min_df=2,
            max_df=0.97,
            ngram_range=(1, 1),
            token_pattern=r"(?u)\b[\w_]+\b",
            lowercase=False,
            sublinear_tf=True,
            dtype=np.float32,
        ),
        "overview": TfidfVectorizer(
            max_features=40_000,
            min_df=2,
            max_df=0.85,
            stop_words="english",
            ngram_range=(1, 2),
            sublinear_tf=True,
            strip_accents="unicode",
            dtype=np.float32,
        ),
        "metadata": TfidfVectorizer(
            max_features=15_000,
            min_df=2,
            max_df=0.98,
            ngram_range=(1, 1),
            token_pattern=r"(?u)\b[\w_]+\b",
            lowercase=False,
            sublinear_tf=True,
            dtype=np.float32,
        ),
    }
    columns = {
        "genres": "genre_text",
        "keywords": "keyword_text",
        "overview": "overview_text",
        "metadata": "metadata_text",
    }

    matrices: list[scipy.sparse.csr_matrix] = []
    dimensions: dict[str, int] = {}
    for field_name, vectorizer in vectorizers.items():
        documents = movies[columns[field_name]].fillna("")
        # Small offline corpora and entirely absent credit/keyword fields still build.
        if len(movies) < 10:
            vectorizer.set_params(min_df=1, max_df=1.0)
        try:
            matrix = vectorizer.fit_transform(documents)
        except ValueError as exc:
            if "vocabulary" not in str(exc) and "terms remain" not in str(exc):
                raise
            vectorizer.set_params(min_df=1, max_df=1.0)
            vectorizer.fit(["missing_field_sentinel"])
            matrix = vectorizer.transform(documents)
        matrix = matrix.astype(np.float32).multiply(FIELD_WEIGHTS[field_name]).tocsr()
        matrices.append(matrix)
        dimensions[field_name] = int(matrix.shape[1])
        print(f"   {field_name:>8}: {matrix.shape[1]:>6,} features x {FIELD_WEIGHTS[field_name]:.2f}")

    weighted = scipy.sparse.hstack(matrices, format="csr", dtype=np.float32)
    weighted = normalize(weighted, norm="l2", copy=False).tocsr()
    bundle = {
        "pipeline_version": PIPELINE_VERSION,
        "field_order": list(vectorizers),
        "field_columns": columns,
        "field_weights": dict(FIELD_WEIGHTS),
        "dimensions": dimensions,
        "vectorizers": vectorizers,
    }
    print(f"   Combined weighted matrix: {weighted.shape}")
    return weighted, bundle


def build_semantic_embeddings(
    movies: pd.DataFrame,
    tfidf_matrix: scipy.sparse.csr_matrix,
    backend: str,
    model_name: str,
    *,
    genre_dimensions: int = 0,
) -> tuple[np.ndarray, object | None, dict]:
    if backend == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install backend/requirements-semantic.txt before using the "
                "sentence-transformers semantic backend."
            ) from exc

        print(f"Encoding neural semantic vectors with {model_name}...")
        model = SentenceTransformer(model_name)
        embeddings = model.encode(
            movies["semantic_text"].fillna("").tolist(),
            batch_size=64,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(np.float32)
        info = {
            "pipeline_version": PIPELINE_VERSION,
            "backend": "sentence-transformers",
            "model_name": model_name,
            "dimensions": int(embeddings.shape[1]),
        }
        return embeddings, None, info

    components = min(256, tfidf_matrix.shape[0] - 1, tfidf_matrix.shape[1] - 1)
    print(f"Fitting {components}-dimension latent semantic embeddings...")
    reducer = TruncatedSVD(n_components=components, n_iter=7, random_state=42)
    # Genres already drive sparse retrieval and explicit filters. Their few
    # heavily repeated basis vectors otherwise dominate low-rank plot semantics.
    semantic_input = tfidf_matrix.copy()
    if genre_dimensions:
        semantic_input.data[semantic_input.indices < genre_dimensions] = 0
        semantic_input.eliminate_zeros()
        semantic_input = normalize(semantic_input, norm="l2", copy=False).tocsr()
    embeddings = reducer.fit_transform(semantic_input).astype(np.float32)
    embeddings = normalize(embeddings, norm="l2", copy=False).astype(np.float32)
    info = {
        "pipeline_version": PIPELINE_VERSION,
        "backend": "lsa",
        "model_name": "TruncatedSVD",
        "dimensions": int(embeddings.shape[1]),
        "explained_variance": float(reducer.explained_variance_ratio_.sum()),
        "input_scope": "weighted_tfidf_without_genres" if genre_dimensions else "weighted_tfidf",
    }
    return embeddings, reducer, info


def save_pickle(path: Path, value: object) -> None:
    with path.open("wb") as file_obj:
        pickle.dump(value, file_obj, protocol=pickle.HIGHEST_PROTOCOL)


def load_and_preprocess(
    *,
    min_votes: int = 100,
    semantic_backend: str = "lsa",
    semantic_model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> tuple[pd.DataFrame, pd.Series]:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    movies = load_movie_source()
    provenance = movies.attrs.get("provenance", {})
    catalog_movies = movies.copy()
    print(f"   Loaded source rows: {len(movies):,}")

    # A compact seed includes searchable recent titles and the historical pool,
    # with short local-credit payloads instead of enormous source credit JSON.
    seed = movies[ALL_COLUMNS + ["cast_list", "director_list"]].copy()
    seed["cast"] = seed["cast_list"].apply(
        lambda names: json.dumps([{"name": name} for name in names], ensure_ascii=False)
    )
    seed["crew"] = seed["director_list"].apply(
        lambda names: json.dumps([{"name": name, "job": "Director"} for name in names], ensure_ascii=False)
    )
    seed = seed.drop(columns=["cast_list", "director_list"])
    seed_path = DATA_DIR / "catalog_seed_v1.csv.gz"
    seed_temporary = DATA_DIR / "catalog_seed_v1.csv.gz.tmp"
    seed.to_csv(seed_temporary, index=False, compression={"method": "gzip", "mtime": 0})
    seed_manifest = {
        **provenance,
        "seed_version": 1,
        "seed_sha256": checksum(seed_temporary),
        "seed_rows": len(seed),
        "generated_at": datetime.now(UTC).isoformat(),
    }

    movies["vote_count"] = pd.to_numeric(movies["vote_count"], errors="coerce").fillna(0)
    release = movies["release_date"].fillna("").astype(str)
    recent = release.between("2026-01-01", provenance.get("cutoff", "2026-09-30"))
    signal = (
        movies["overview"].fillna("").astype(str).str.strip().ne("")
        | movies["genres"].apply(lambda value: bool(clean_csv_list(value)))
        | movies["keywords"].apply(lambda value: bool(clean_csv_list(value)))
    )
    movies = movies[((movies["vote_count"] >= min_votes) | recent) & signal].copy()
    movies.dropna(subset=["id", "title"], inplace=True)
    for column in ALL_COLUMNS:
        movies[column] = movies[column].fillna("")
    movies["id"] = pd.to_numeric(movies["id"], errors="coerce")
    movies.dropna(subset=["id"], inplace=True)
    movies["id"] = movies["id"].astype(int)
    movies.drop_duplicates(subset=["id"], keep="last", inplace=True)
    movies.reset_index(drop=True, inplace=True)
    print(f"   Eligible historical/recent movies with content: {len(movies):,}")

    movies = build_feature_columns(movies)
    movies["poster_path"] = movies["poster_path"].fillna("").astype(str)

    runtime_columns = [
        "id",
        "title",
        "overview",
        "genres_list",
        "keywords_list",
        "cast_list",
        "director_list",
        "production_companies_list",
        "vote_average",
        "vote_count",
        "release_date",
        "status",
        "runtime",
        "popularity",
        "original_language",
        "poster_path",
    ]
    tfidf_matrix, tfidf_bundle = build_weighted_tfidf(movies)
    semantic_embeddings, semantic_reducer, semantic_info = build_semantic_embeddings(
        movies,
        tfidf_matrix,
        semantic_backend,
        semantic_model,
        genre_dimensions=tfidf_bundle["dimensions"]["genres"],
    )
    movies_clean = movies[runtime_columns].copy()

    indices = pd.Series(movies_clean.index, index=movies_clean["title"]).drop_duplicates()
    id_to_idx = pd.Series(movies_clean.index, index=movies_clean["id"]).drop_duplicates()

    print("Saving immutable recommendation generation...")
    generation = (
        MODEL_DIR
        / "generations"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    )
    generation.mkdir(parents=True)
    publish_catalog(catalog_movies, generation / "catalog.sqlite3", provenance)
    movies_clean.to_pickle(generation / "movies.pkl")
    scipy.sparse.save_npz(generation / "tfidf_matrix.npz", tfidf_matrix)
    np.save(generation / "semantic_embeddings.npy", semantic_embeddings)
    save_pickle(generation / "indices.pkl", indices)
    save_pickle(generation / "id_to_index.pkl", id_to_idx)
    save_pickle(generation / "tfidf_bundle.pkl", tfidf_bundle)
    # Kept for deployments/scripts that still look for the historical artifact name.
    save_pickle(generation / "tfidf_vectorizer.pkl", tfidf_bundle)
    if semantic_reducer is not None:
        save_pickle(generation / "semantic_reducer.pkl", semantic_reducer)
    (generation / "semantic_info.json").write_text(
        json.dumps(semantic_info, indent=2),
        encoding="utf-8",
    )
    write_manifest(
        generation,
        {
            "catalog": provenance,
            "catalog_generation": provenance.get("catalog_generation", generation.name),
            "cutoff": provenance.get("cutoff"),
            "field_weights": dict(FIELD_WEIGHTS),
            "semantic_input_scope": semantic_info.get("input_scope", "semantic_text"),
            "credits_coverage": {
                "cast": int(movies["cast_list"].apply(bool).sum()),
                "directors": int(movies["director_list"].apply(bool).sum()),
            },
        },
    )
    activate_generation(MODEL_DIR, generation)
    os.replace(seed_temporary, seed_path)
    seed_manifest_temporary = DATA_DIR / "catalog_seed_v1.json.tmp"
    seed_manifest_temporary.write_text(json.dumps(seed_manifest, indent=2), encoding="utf-8")
    os.replace(seed_manifest_temporary, DATA_DIR / "catalog_seed_v1.json")
    # Legacy tools can use the standalone index after successful pair activation.
    import shutil

    catalog_temporary = DATA_DIR / "catalog.sqlite3.tmp"
    shutil.copyfile(generation / "catalog.sqlite3", catalog_temporary)
    os.replace(catalog_temporary, DATA_DIR / "catalog.sqlite3")

    print("\nPreprocessing complete")
    print(f"   movies.pkl              -> {len(movies_clean):,} movies")
    print(f"   tfidf_matrix.npz        -> {tfidf_matrix.shape}")
    print(f"   semantic_embeddings.npy -> {semantic_embeddings.shape}")
    print(f"   semantic backend        -> {semantic_info['backend']}")
    return movies_clean, indices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-votes",
        type=int,
        default=int(os.getenv("CINEMATCH_PREPROCESS_MIN_VOTES", "100")),
        help="Minimum TMDB vote count required for the recommendation catalogue.",
    )
    parser.add_argument(
        "--semantic-backend",
        choices=("lsa", "sentence-transformers"),
        default=os.getenv("CINEMATCH_SEMANTIC_BACKEND", "lsa"),
    )
    parser.add_argument(
        "--semantic-model",
        default=os.getenv(
            "CINEMATCH_SEMANTIC_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    load_and_preprocess(
        min_votes=max(arguments.min_votes, 0),
        semantic_backend=arguments.semantic_backend,
        semantic_model=arguments.semantic_model,
    )
