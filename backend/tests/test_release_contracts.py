from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ReleaseContractTests(unittest.TestCase):
    def test_render_runtime_is_valid_and_python_version_is_explicit(self) -> None:
        service = yaml.safe_load((ROOT / "render.yaml").read_text())["services"][0]
        self.assertEqual(service["runtime"], "python")
        self.assertNotIn("env", service)
        self.assertRegex((ROOT / ".python-version").read_text().strip(), r"^3\.13\.\d+$")
        self.assertIn("backend/requirements.lock", service["buildCommand"])
        self.assertIn("python -m backend.data_preprocessing", service["buildCommand"])

    def test_runtime_lock_contains_only_exact_versions(self) -> None:
        path = ROOT / "backend/requirements.lock"
        self.assertTrue(path.exists(), "A fresh install must have an exact runtime dependency lock")
        entries = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertGreater(len(entries), 10)
        for line in entries:
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s;]+(?:\s*;.*)?$")
        normalized = [re.split(r"==", line)[0].lower().replace("_", "-") for line in entries]
        self.assertIn("scipy", normalized)


if __name__ == "__main__":
    unittest.main()
