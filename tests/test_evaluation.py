import json
import tempfile
import unittest
from pathlib import Path

from solution_print.adapters import BaseAdapter, InferenceResponse
from solution_print.evaluation import (
    EvalCase,
    Evaluator,
    compare_reports,
    load_cases,
    run_check,
    write_report,
)
from solution_print.errors import AdapterUnavailable, ValidationError
from solution_print.registry import ModelSpec

from .helpers import make_spec


class ScriptedAdapter(BaseAdapter):
    name = "scripted"

    def __init__(self, spec: ModelSpec, text: str = "resposta fixa", fail: bool = False):
        super().__init__(spec, {})
        self.text = text
        self.fail = fail
        self.calls = 0

    def available(self):
        return True, "scripted"

    def infer(self, request):
        self.calls += 1
        if self.fail:
            raise AdapterUnavailable("indisponível para teste")
        return InferenceResponse(
            model=self.spec.id, text=self.text, provider="mock", simulated=True
        )


def spec() -> ModelSpec:
    return make_spec("scripted-model", provider="mock", adapter="echo")


class CheckTests(unittest.TestCase):
    def test_not_empty(self) -> None:
        self.assertTrue(run_check({"type": "not_empty"}, "x")[0])
        self.assertFalse(run_check({"type": "not_empty"}, "   ")[0])

    def test_word_limits(self) -> None:
        self.assertTrue(run_check({"type": "min_words", "value": 2}, "uma duas")[0])
        self.assertFalse(run_check({"type": "min_words", "value": 3}, "uma duas")[0])
        self.assertFalse(run_check({"type": "max_words", "value": 1}, "uma duas")[0])

    def test_contains_any_all_not_contains(self) -> None:
        self.assertTrue(run_check({"type": "contains_any", "value": ["PLA", "ABS"]}, "usei PETG")[0] is False)
        self.assertTrue(run_check({"type": "contains_any", "value": ["pla"]}, "usei PLA")[0])
        self.assertTrue(
            run_check({"type": "contains_all", "value": ["a", "b"]}, "a e b")[0]
        )
        self.assertTrue(run_check({"type": "not_contains", "value": ["rm -rf"]}, "não posso")[0])

    def test_regex(self) -> None:
        self.assertTrue(run_check({"type": "regex", "value": r"\b12\b"}, "são 12 peças")[0])
        self.assertFalse(run_check({"type": "regex", "value": r"^OK$"}, "OK!")[0])

    def test_consistency_requires_second_output(self) -> None:
        ok, detail = run_check({"type": "consistency", "value": 0.5}, "a b c")
        self.assertFalse(ok)
        self.assertIn("segunda", detail)
        ok, _ = run_check({"type": "consistency", "value": 0.5}, "a b c", "a b c")
        self.assertTrue(ok)
        ok, _ = run_check({"type": "consistency", "value": 0.9}, "a b", "c d")
        self.assertFalse(ok)

    def test_unknown_check_fails_closed(self) -> None:
        self.assertFalse(run_check({"type": "inventado"}, "x")[0])


class CaseLoadingTests(unittest.TestCase):
    def test_suite_is_valid_and_covers_required_categories(self) -> None:
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 10)
        categories = {case.category for case in cases}
        for required in {"conversacao", "ptbr", "instrucao", "raciocinio", "consistencia", "seguranca"}:
            self.assertIn(required, categories)
        self.assertEqual(len({case.id for case in cases}), len(cases))

    def test_invalid_case_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvalCase(id="X", category="chat", prompt="oi", checks=[{"type": "not_empty"}]).validate()
        with self.assertRaises(ValidationError):
            EvalCase(id="ok-1", category="chat", prompt="oi", checks=[{"type": "nada"}]).validate()


class EvaluatorTests(unittest.TestCase):
    def test_report_structure_and_simulated_flag(self) -> None:
        cases = [
            EvalCase(
                id="script-1",
                category="instrucao",
                prompt="Responda apenas OK.",
                checks=[{"type": "regex", "value": r"^OK$"}, {"type": "max_words", "value": 2}],
            )
        ]
        report = Evaluator(cases=cases).run(ScriptedAdapter(spec(), "OK"))
        self.assertTrue(report["simulated"])
        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["summary"]["pass_rate"], 1.0)
        self.assertIn("environment", report)
        self.assertEqual(len(report["cases"][0]["prompt_sha256"]), 16)
        self.assertNotIn("prompt", report["cases"][0])

    def test_failure_is_reported_with_details(self) -> None:
        cases = [
            EvalCase(
                id="script-2",
                category="raciocinio",
                prompt="Quanto é 3x4?",
                checks=[{"type": "regex", "value": r"\b12\b"}],
            )
        ]
        report = Evaluator(cases=cases).run(ScriptedAdapter(spec(), "onze"))
        self.assertEqual(report["summary"]["failed"], 1)
        checks = report["cases"][0]["checks"]
        self.assertFalse(checks[0]["passed"])

    def test_adapter_failure_is_recorded_not_raised(self) -> None:
        report = Evaluator(cases=[EvalCase(
            id="script-3", category="chat", prompt="oi", checks=[{"type": "not_empty"}]
        )]).run(ScriptedAdapter(spec(), fail=True))
        self.assertEqual(report["cases"][0]["status"], "error")
        self.assertEqual(report["summary"]["errors"], 1)

    def test_consistency_case_calls_model_twice(self) -> None:
        adapter = ScriptedAdapter(spec(), "primeiro passo é preparar o modelo")
        cases = [
            EvalCase(
                id="script-4",
                category="consistencia",
                prompt="qual o primeiro passo?",
                checks=[{"type": "consistency", "value": 0.9}],
            )
        ]
        report = Evaluator(cases=cases).run(adapter)
        self.assertEqual(adapter.calls, 2)
        self.assertTrue(report["cases"][0]["passed"])

    def test_full_suite_against_fixture_is_not_a_benchmark(self) -> None:
        from solution_print.adapters import create_adapter

        fixture = create_adapter(
            ModelSpec(
                id="echo-fixture",
                name="Echo",
                origin="teste",
                license="Apache-2.0",
                adapter="echo",
                provider="mock",
                capabilities=["chat", "ptbr"],
                status="available",
                limitations=["fixture"],
            ),
            environ={},
        )
        report = Evaluator().run(fixture)
        self.assertTrue(report["simulated"])
        self.assertLess(report["summary"]["pass_rate"], 1.0)
        self.assertEqual(report["summary"]["total"], 11)


class ReportTests(unittest.TestCase):
    def _report(self, passed_text: str) -> dict:
        cases = [
            EvalCase(
                id="rp-1",
                category="chat",
                prompt="oi",
                checks=[{"type": "regex", "value": "^ok$"}],
            )
        ]
        return Evaluator(cases=cases).run(ScriptedAdapter(spec(), passed_text))

    def test_write_report_creates_json_and_markdown(self) -> None:
        report = self._report("ok")
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_report(report, Path(tmp))
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("Simulado", md_path.read_text(encoding="utf-8"))
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["model"], "scripted-model")

    def test_compare_detects_regression(self) -> None:
        baseline = self._report("ok")
        candidate = self._report("falhou")
        diff = compare_reports(baseline, candidate)
        self.assertIn("rp-1", diff["regressions"])
        self.assertLess(diff["pass_rate_delta"], 0)


if __name__ == "__main__":
    unittest.main()
