import importlib
import json
import pickle
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse


class ArtifactGenerationTests(unittest.TestCase):
    def fixture(self, path):
        path.mkdir(parents=True)
        pd.DataFrame({"id": [7, 8], "title": ["A", "B"]}).to_pickle(path / "movies.pkl")
        scipy.sparse.save_npz(path / "tfidf_matrix.npz", scipy.sparse.csr_matrix(np.eye(2, dtype=np.float32)))
        np.save(path / "semantic_embeddings.npy", np.eye(2, dtype=np.float32))
        with (path / "tfidf_bundle.pkl").open("wb") as output:
            pickle.dump(
                {"field_order": ["overview"], "dimensions": {"overview": 2}, "pipeline_version": 3}, output
            )
        with (path / "id_to_index.pkl").open("wb") as output:
            pickle.dump(pd.Series([0, 1], index=[7, 8]), output)
        (path / "semantic_info.json").write_text(json.dumps({"dimensions": 2, "backend": "lsa"}))
        from backend.catalog import publish_catalog

        publish_catalog(
            pd.DataFrame({"id": [7, 8], "title": ["A", "B"]}),
            path / "catalog.sqlite3",
            {"cutoff": "2026-09-30"},
        )

    def test_missing_or_corrupt_paired_catalog_is_rejected(self):
        artifacts = importlib.import_module("backend.artifacts")
        with tempfile.TemporaryDirectory() as directory:
            for failure in ("missing", "corrupt"):
                path = Path(directory) / failure
                self.fixture(path)
                if failure == "missing":
                    (path / "catalog.sqlite3").unlink()
                else:
                    (path / "catalog.sqlite3").write_bytes(b"not a catalog")
                with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                    artifacts.write_manifest(path, {"pipeline_version": 3})

    def test_checksum_failure_keeps_previous_active_generation(self):
        self.assertIsNotNone(
            importlib.util.find_spec("backend.artifacts"), "Atomic model bundles are missing"
        )
        artifacts = importlib.import_module("backend.artifacts")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "generations" / "first"
            self.fixture(first)
            artifacts.write_manifest(first, {"pipeline_version": 3})
            artifacts.activate_generation(root, first)
            second = root / "generations" / "second"
            self.fixture(second)
            artifacts.write_manifest(second, {"pipeline_version": 3})
            (second / "semantic_embeddings.npy").write_bytes(b"corrupt")
            with self.assertRaises(RuntimeError):
                artifacts.activate_generation(root, second)
            self.assertEqual(artifacts.active_model_dir(root), first)

    def test_reordered_ids_and_feature_width_are_rejected(self):
        self.assertIsNotNone(importlib.util.find_spec("backend.artifacts"), "Model validation is missing")
        artifacts = importlib.import_module("backend.artifacts")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generation"
            self.fixture(path)
            artifacts.write_manifest(path, {"pipeline_version": 3})
            pd.DataFrame({"id": [8, 7], "title": ["B", "A"]}).to_pickle(path / "movies.pkl")
            with self.assertRaises(RuntimeError):
                artifacts.validate_generation(path)
            self.fixture(Path(directory) / "invalid")
            invalid = Path(directory) / "invalid"
            scipy.sparse.save_npz(invalid / "tfidf_matrix.npz", scipy.sparse.csr_matrix(np.ones((2, 3))))
            with self.assertRaises(RuntimeError):
                artifacts.write_manifest(invalid, {"pipeline_version": 3})

    def test_incompatible_pickle_runtime_is_rejected_before_loading(self):
        artifacts = importlib.import_module("backend.artifacts")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generation"
            self.fixture(path)
            artifacts.write_manifest(path, {"pipeline_version": 3})
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["packages"]["scikit-learn"] = "0.0.0"
            (path / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                artifacts.validate_generation(path)

    def test_nonfinite_numeric_artifacts_and_wrong_reducer_shape_are_rejected(self):
        artifacts = importlib.import_module("backend.artifacts")
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            for label in ("sparse", "embeddings", "reducer"):
                path = Path(directory) / label
                self.fixture(path)
                if label == "sparse":
                    scipy.sparse.save_npz(
                        path / "tfidf_matrix.npz", scipy.sparse.csr_matrix([[float("nan"), 0], [0, 1]])
                    )
                elif label == "embeddings":
                    np.save(path / "semantic_embeddings.npy", [[1, float("inf")], [0, 1]])
                else:
                    with (path / "semantic_reducer.pkl").open("wb") as output:
                        pickle.dump(SimpleNamespace(components_=np.ones((3, 2))), output)
                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    artifacts.write_manifest(path, {"pipeline_version": 3})


if __name__ == "__main__":
    unittest.main()
