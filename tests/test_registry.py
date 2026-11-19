import json
import tempfile
import unittest
from pathlib import Path

from solution_print.errors import ModelNotFound, ValidationError
from solution_print.registry import CATALOG_PATH, ModelRegistry, ModelSpec


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ModelRegistry.builtin()

    def test_builtin_catalog_loads_and_is_valid(self) -> None:
        self.assertTrue(CATALOG_PATH.exists())
        self.assertGreaterEqual(len(self.registry), 5)
        for spec in self.registry.all():
            self.assertEqual(spec.validate(), [], "modelo inválido: %s" % spec.id)

    def test_minimind_entry_preserves_upstream_attribution(self) -> None:
        spec = self.registry.get("minimind-3-small")
        self.assertIn("jingyaogong", spec.origin)
        self.assertEqual(spec.license, "Apache-2.0")
        self.assertEqual(spec.adapter, "minimind")

    def test_lookup_missing_model_raises(self) -> None:
        with self.assertRaises(ModelNotFound):
            self.registry.get("nao-existe")

    def test_duplicate_model_is_rejected(self) -> None:
        spec = self.registry.get("sp-echo-baseline-v1")
        with self.assertRaises(ValidationError):
            self.registry.add(spec)

    def test_invalid_model_id_is_rejected(self) -> None:
        spec = ModelSpec(
            id="ID Invalido!",
            name="x",
            origin="teste",
            license="Apache-2.0",
            adapter="echo",
            provider="mock",
            capabilities=["chat"],
            limitations=["fixture"],
        )
        with self.assertRaises(ValidationError):
            self.registry.add(spec)
        self.assertTrue(any("id inválido" in item for item in spec.validate()))

    def test_unknown_field_in_catalog_is_rejected(self) -> None:
        payload = self.registry.get("sp-echo-baseline-v1").to_dict()
        payload["campo_inexistente"] = True
        with self.assertRaises(ValidationError):
            ModelSpec.from_dict(payload)

    def test_free_non_local_model_must_document_network(self) -> None:
        spec = ModelSpec(
            id="modelo-remoto-sem-nota",
            name="Remoto",
            origin="teste",
            license="MIT",
            adapter="openai_compatible",
            provider="openai_compatible",
            capabilities=["chat"],
            status="available",
            cost="free",
            limitations=[],
        )
        problems = spec.validate()
        self.assertTrue(any("dependência de rede" in item for item in problems), problems)

    def test_filter_by_capability_and_cost(self) -> None:
        free_chat = self.registry.filter(capabilities=["chat"], max_cost="free")
        self.assertTrue(free_chat)
        self.assertTrue(all(spec.cost == "free" for spec in free_chat))
        self.assertTrue(all("chat" in spec.capabilities for spec in free_chat))

    def test_report_flags_hardware_fit(self) -> None:
        rows = self.registry.report()
        self.assertEqual(len(rows), len(self.registry))
        for row in rows:
            self.assertIn("fits", row)
            self.assertIn("reasons", row)
        big = next(row for row in rows if row["id"] == "qwen2.5-7b-instruct-gguf")
        self.assertFalse(big["fits"])

    def test_public_view_hides_endpoint_configuration(self) -> None:
        spec = self.registry.get("local-openai-compatible")
        view = spec.public_view()
        self.assertNotIn("endpoint", view)
        self.assertNotIn("endpoint_env", view)

    def test_save_and_reload_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalogo.json"
            self.registry.save(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            reloaded = ModelRegistry.load(path)
            self.assertEqual(reloaded.ids(), self.registry.ids())

    def test_unsupported_schema_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalogo.json"
            path.write_text('{"schema_version": 99, "models": []}', encoding="utf-8")
            with self.assertRaises(ValidationError):
                ModelRegistry.load(path)

    def test_runnable_excludes_planned_models(self) -> None:
        runnable_ids = {spec.id for spec in self.registry.runnable()}
        self.assertNotIn("llama-3.2-3b-instruct-gguf", runnable_ids)
        self.assertNotIn("qwen2.5-7b-instruct-gguf", runnable_ids)


if __name__ == "__main__":
    unittest.main()
