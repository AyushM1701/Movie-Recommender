from __future__ import annotations

import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import scipy.sparse

from backend.artifacts import activate_generation, write_manifest
from backend.recommender import RecommendationEngine
from backend.tests.recommender_fixtures import make_engine


class PublishedModelLoadingTests(unittest.TestCase):
    def write_generation(self, directory: Path) -> None:
        directory.mkdir(parents=True)
        fixture = make_engine()
        fixture.movies.to_pickle(directory / "movies.pkl")
        scipy.sparse.save_npz(directory / "tfidf_matrix.npz", fixture.tfidf_matrix)
        np.save(directory / "semantic_embeddings.npy", fixture.tfidf_matrix.toarray())
        bundle = {
            "pipeline_version": 3,
            "field_order": ["overview"],
            "dimensions": {"overview": fixture.tfidf_matrix.shape[1]},
            "field_weights": {"overview": 1},
            "vectorizers": {"overview": fixture.tfidf_vectorizer},
        }
        for name, value in [
            ("tfidf_bundle.pkl", bundle),
            ("id_to_index.pkl", fixture.id_to_index),
            ("indices.pkl", fixture.indices),
        ]:
            with (directory / name).open("wb") as stream:
                pickle.dump(value, stream)
        (directory / "semantic_info.json").write_text(
            json.dumps({"backend": "none", "dimensions": fixture.tfidf_matrix.shape[1]})
        )
        from backend.catalog import publish_catalog

        publish_catalog(fixture.movies, directory / "catalog.sqlite3", {"cutoff": "2026-09-30"})
        write_manifest(directory, {"cutoff": "2026-09-30"})

    def test_engine_loads_published_generation_without_legacy_root_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generation = root / "generations" / "fixture"
            self.write_generation(generation)
            activate_generation(root, generation)
            with (
                patch("backend.recommender.MODEL_DIR", root),
                patch.dict(os.environ, {"CINEMATCH_CATALOG_PATH": str(root / "missing.sqlite3")}),
            ):
                engine = RecommendationEngine()
                self.assertEqual(len(engine.movies), 12)
                self.assertEqual(engine.get_movie_by_id(27205)["title"], "Inception")
                engine.close()

    def test_corrupt_generation_does_not_fall_back_to_old_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_generation(root / "generations" / "fixture")
            activate_generation(root, root / "generations" / "fixture")
            with (root / "generations" / "fixture" / "movies.pkl").open("ab") as stream:
                stream.write(b"changed")
            self.write_generation(root / "legacy")
            for file in (root / "legacy").iterdir():
                (root / file.name).write_bytes(file.read_bytes())
            with patch("backend.recommender.MODEL_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    RecommendationEngine()


if __name__ == "__main__":
    unittest.main()
