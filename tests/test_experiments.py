import json
import tempfile
import unittest
from pathlib import Path

from solution_print.experiments import (
    ExperimentRecorder,
    canonical_hash,
    environment_snapshot,
    git_version,
)


class ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.recorder = ExperimentRecorder(self.root, repo_root=Path("."))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hash_is_stable_and_order_independent(self) -> None:
        first = canonical_hash({"a": 1, "b": [1, 2]})
        second = canonical_hash({"b": [1, 2], "a": 1})
        self.assertEqual(first, second)
        self.assertNotEqual(first, canonical_hash({"a": 2}))
        self.assertEqual(len(first), 64)

    def test_environment_snapshot_has_real_data(self) -> None:
        snapshot = environment_snapshot()
        self.assertIn("ram_total_gb", snapshot)
        self.assertIn("profile", snapshot)
        self.assertGreater(snapshot["ram_total_gb"], 0)

    def test_git_version_returns_fields(self) -> None:
        info = git_version(Path("."))
        self.assertIn("commit", info)
        self.assertIn("dirty", info)

    def test_start_and_finish_roundtrip(self) -> None:
        record = self.recorder.start(
            "baseline echo",
            config={"model": "sp-echo-baseline-v1", "cases": 11},
            dataset_id="eval_cases_ptbr.json",
            model_ids=["sp-echo-baseline-v1"],
        )
        self.assertEqual(record.status, "running")
        self.assertEqual(len(record.config_sha256), 64)
        path = self.root / record.experiment_id / "experiment.json"
        self.assertTrue(path.exists())

        final = self.recorder.finish(
            record, "completed", metrics={"pass_rate": 0.27}, results_path="evidence/eval.json"
        )
        self.assertTrue(final.exists())
        payload = json.loads(final.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["metrics"]["pass_rate"], 0.27)
        self.assertIsNotNone(payload["finished_at"])

    def test_invalid_final_status_is_rejected(self) -> None:
        record = self.recorder.start("x", config={})
        with self.assertRaises(ValueError):
            self.recorder.finish(record, "quase-pronto")

    def test_empty_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.recorder.start("   ")

    def test_list_and_load(self) -> None:
        record = self.recorder.start("listar", config={"k": 1})
        self.recorder.finish(record, "completed", metrics={})
        items = self.recorder.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["experiment_id"], record.experiment_id)
        loaded = self.recorder.load(record.experiment_id)
        self.assertEqual(loaded.name, "listar")
        self.assertEqual(loaded.status, "completed")

    def test_config_is_persisted_with_hash_for_reproduction(self) -> None:
        config = {"model": "sp-echo-baseline-v1", "temperature": 0.0, "cases": 11}
        record = self.recorder.start("reprodutivel", config=config)
        self.recorder.finish(record, "completed", metrics={})
        payload = json.loads(
            (self.root / record.experiment_id / "experiment.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["config"], config)
        self.assertEqual(payload["config_sha256"], canonical_hash(config))
        self.assertIn("code_version", payload)
        self.assertIn("environment", payload)


if __name__ == "__main__":
    unittest.main()
