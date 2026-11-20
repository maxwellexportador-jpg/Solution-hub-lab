import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class UpstreamPreservationTests(unittest.TestCase):
    def test_readme_and_license_are_intact(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("MiniMind", readme)
        self.assertIn("jingyaogong", readme)
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)

    def test_upstream_directories_exist(self) -> None:
        for relative in (
            "model/model_minimind.py",
            "model/tokenizer.json",
            "trainer/train_pretrain.py",
            "trainer/train_full_sft.py",
            "dataset",
            "scripts",
            "images/logo2.png",
        ):
            self.assertTrue((ROOT / relative).exists(), "ausente: %s" % relative)

    def test_solution_print_layer_is_separate(self) -> None:
        package = ROOT / "solution_print"
        self.assertTrue((package / "__init__.py").exists())
        self.assertFalse((ROOT / "model" / "solution_print.py").exists())
        text = (package / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("Apache-2.0", text)
        self.assertIn("Jingyao Gong", text)

    def test_origin_document_exists(self) -> None:
        origin = (ROOT / "SOLUTION_PRINT_ORIGIN.md").read_text(encoding="utf-8")
        self.assertIn("minimind", origin.lower())
        self.assertIn("Apache", origin)


class SecurityHygieneTests(unittest.TestCase):
    def test_no_obvious_secrets_in_our_code(self) -> None:
        findings = []
        for path in list((ROOT / "solution_print").rglob("*.py")) + list(
            (ROOT / "tests").rglob("*.py")
        ):
            text = path.read_text(encoding="utf-8")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append(str(path.relative_to(ROOT)))
        self.assertEqual(findings, [], "possíveis segredos: %s" % findings)

    def test_catalog_has_no_paid_models(self) -> None:
        import json

        data = json.loads((ROOT / "solution_print" / "catalog.json").read_text(encoding="utf-8"))
        paid = [model["id"] for model in data["models"] if model.get("cost") != "free"]
        self.assertEqual(paid, [])

    def test_gitignore_excludes_local_artifacts(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in (".venv", "__pycache__", "*.pth", "*.gguf", ".env"):
            self.assertIn(entry, gitignore)


if __name__ == "__main__":
    unittest.main()
