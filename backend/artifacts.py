"""Immutable model generations with verified dimensions, ID order and checksums."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pickle
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse

REQUIRED = (
    "movies.pkl",
    "tfidf_matrix.npz",
    "semantic_embeddings.npy",
    "tfidf_bundle.pkl",
    "id_to_index.pkl",
    "semantic_info.json",
)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contracts(path):
    embeddings = None
    try:
        movies = pd.read_pickle(path / "movies.pkl")
        matrix = scipy.sparse.load_npz(path / "tfidf_matrix.npz")
        embeddings = np.load(path / "semantic_embeddings.npy", mmap_mode="r")
        with (path / "tfidf_bundle.pkl").open("rb") as source:
            bundle = pickle.load(source)
        with (path / "id_to_index.pkl").open("rb") as source:
            indices = pickle.load(source)
        semantic = json.loads((path / "semantic_info.json").read_text(encoding="utf-8"))
        if not np.isfinite(matrix.data).all() or not np.isfinite(embeddings).all():
            raise ValueError("Model numeric artifacts contain NaN or infinity")
        reducer_path = path / "semantic_reducer.pkl"
        if semantic.get("backend") == "lsa" and reducer_path.exists():
            with reducer_path.open("rb") as source:
                reducer = pickle.load(source)
            if (
                reducer.components_.shape != (embeddings.shape[1], matrix.shape[1])
                or not np.isfinite(reducer.components_).all()
            ):
                raise ValueError("Semantic reducer dimensions or numeric values differ")
        ids = [int(value) for value in movies["id"]]
        catalog_path = path / "catalog.sqlite3"
        if not catalog_path.is_file():
            raise ValueError("Paired catalog is missing")
        with closing(sqlite3.connect(catalog_path.resolve().as_uri() + "?mode=ro", uri=True)) as catalog:
            if catalog.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Paired catalog integrity check failed")
            if not set(ids).issubset({row[0] for row in catalog.execute("SELECT id FROM movies")}):
                raise ValueError("Recommendation movie IDs are absent from the paired catalog")
            catalog.execute("SELECT key,value FROM metadata").fetchall()
        order = bundle["field_order"]
        dimensions = bundle["dimensions"]
        if "vectorizers" in bundle and any(
            len(bundle["vectorizers"][field].vocabulary_) != dimensions[field] for field in order
        ):
            raise ValueError("Trained vectorizer vocabulary dimensions differ")
        if (
            len(set(ids)) != len(ids)
            or not ids
            or matrix.shape[0] != len(ids)
            or embeddings.ndim != 2
            or embeddings.shape[0] != len(ids)
        ):
            raise ValueError("Movie IDs or artifact row counts differ")
        if (
            sum(dimensions[field] for field in order) != matrix.shape[1]
            or semantic["dimensions"] != embeddings.shape[1]
        ):
            raise ValueError("Vectorizer/embedding feature dimensions differ")
        if [int(value) for value in indices.index] != ids or [int(value) for value in indices.values] != list(
            range(len(ids))
        ):
            raise ValueError("Movie index mapping/order differs")
        return {
            "ordered_id_sha256": hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest(),
            "movie_count": len(ids),
            "tfidf_shape": list(matrix.shape),
            "embedding_shape": list(embeddings.shape),
            "field_order": order,
            "field_dimensions": dimensions,
            "embedding_backend": semantic["backend"],
            "pipeline_version": bundle["pipeline_version"],
        }
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        EOFError,
        pickle.UnpicklingError,
        sqlite3.Error,
    ) as exc:
        raise RuntimeError(
            f"Model generation {path.name} is invalid: {type(exc).__name__}. Rebuild a complete generation."
        ) from None
    finally:
        if embeddings is not None and getattr(embeddings, "_mmap", None) is not None:
            embeddings._mmap.close()


def write_manifest(path: Path, metadata: dict) -> dict:
    path = Path(path)
    for name in (*REQUIRED, "catalog.sqlite3"):
        if not (path / name).is_file():
            raise RuntimeError(f"Model generation is missing {name}.")
    manifest = {**metadata, **_contracts(path)}
    manifest["packages"] = {
        name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scipy", "scikit-learn")
    }
    manifest["checksums"] = {
        file.name: checksum(file)
        for file in sorted(path.iterdir())
        if file.is_file() and file.name != "manifest.json"
    }
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    validate_generation(path)
    return manifest


def validate_generation(path: Path) -> dict:
    path = Path(path)
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError(
            "Published model manifest is missing or invalid; rebuild the generation."
        ) from None
    for name in (*REQUIRED, "catalog.sqlite3"):
        if name not in manifest.get("checksums", {}):
            raise RuntimeError(f"Model manifest omits required artifact {name}.")
    if manifest.get("packages", {}).get("scikit-learn") != importlib.metadata.version("scikit-learn"):
        raise RuntimeError(
            "Model scikit-learn runtime differs from the build; install the pinned dependencies or rebuild models."
        )
    for name, expected in manifest.get("checksums", {}).items():
        if Path(name).name != name or not (path / name).is_file() or checksum(path / name) != expected:
            raise RuntimeError(
                f"Model artifact checksum failed for {name}; previous generation must be restored or rebuilt."
            )
    actual = _contracts(path)
    if any(manifest.get(key) != value for key, value in actual.items()):
        raise RuntimeError(
            "Model manifest contracts do not match ordered IDs, matrix or vectorizer dimensions."
        )
    return manifest


def activate_generation(model_root: Path, generation: Path):
    model_root, generation = Path(model_root), Path(generation)
    if generation.parent.resolve() != (model_root / "generations").resolve():
        raise RuntimeError("Model generation must be inside this model root.")
    validate_generation(generation)
    pointer = model_root / "active.json"
    temporary = pointer.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"generation": generation.name}), encoding="utf-8")
    os.replace(temporary, pointer)


def active_model_dir(model_root: Path) -> Path:
    model_root = Path(model_root)
    pointer = model_root / "active.json"
    if not pointer.exists():
        # Explicit compatibility path for the pre-generation models; no fallback from corrupt pointers.
        if all((model_root / name).exists() for name in REQUIRED):
            return model_root
        raise RuntimeError("No model generation is provisioned. Run python -m backend.data_preprocessing.")
    try:
        generation = json.loads(pointer.read_text(encoding="utf-8"))["generation"]
        if (
            not isinstance(generation, str)
            or Path(generation).name != generation
            or generation in (".", "..")
        ):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("Invalid active model pointer; restore a validated generation.") from None
    path = model_root / "generations" / generation
    validate_generation(path)
    return path
