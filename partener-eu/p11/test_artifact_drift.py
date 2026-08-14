#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply_mod = load_module("apply_resolutions_drift", ROOT / "apply_resolutions.py")
projection_mod = load_module("build_public_projection_drift", ROOT / "build_public_projection.py")


class ArtifactDriftTests(unittest.TestCase):
    def test_resolution_check_detects_semantic_drift(self):
        bundle = apply_mod.load(ROOT / "opportunity_bundle.json")
        resolutions = [apply_mod.load(path) for path in sorted((ROOT / "resolutions").glob("*_resolution.json"))]
        expected = apply_mod.apply(bundle, resolutions)
        with tempfile.TemporaryDirectory() as folder:
            artifact = pathlib.Path(folder) / "bundle.json"
            artifact.write_text(apply_mod.serialize(expected), encoding="utf-8")
            apply_mod.assert_artifact_current(artifact, expected)
            changed = json.loads(artifact.read_text(encoding="utf-8"))
            changed["resolution_application"]["automatic_publication"] = True
            artifact.write_text(apply_mod.serialize(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "resolution artifact drift"):
                apply_mod.assert_artifact_current(artifact, expected)

    def test_projection_check_rejects_unsafe_semantic_drift(self):
        bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))
        payload = projection_mod.render(projection_mod.build(bundle))
        with tempfile.TemporaryDirectory() as folder:
            artifact = pathlib.Path(folder) / "projection.js"
            artifact.write_text(payload, encoding="utf-8")
            projection_mod.assert_artifact_current(artifact, payload)
            artifact.write_text(payload.replace('"automaticPublication":false', '"automaticPublication":true'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "policy must disable automatic publication"):
                projection_mod.assert_artifact_current(artifact, payload)


if __name__ == "__main__":
    unittest.main()
