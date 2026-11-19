import json
import tempfile
import unittest
from pathlib import Path

from solution_print.adapters import Message
from solution_print.errors import (
    AdapterTimeout,
    AllModelsFailed,
    ModelNotFound,
    NoModelAvailable,
    PolicyViolation,
    ValidationError,
)
from solution_print.hardware import HardwareInfo
from solution_print.registry import ModelRegistry, ModelSpec
from solution_print.router import ModelRouter, RoutingPolicy, RoutingRequest

from .helpers import FailingAdapter, adapter_factory, make_spec


def hardware(ram: float = 8.0) -> HardwareInfo:
    return HardwareInfo(
        ram_total_gb=ram,
        ram_available_gb=ram * 0.75,
        cpu_cores=4,
        platform="test",
        python_version="3.12",
    )


def echo_spec() -> ModelSpec:
    return ModelSpec(
        id="echo-fixture",
        name="Echo fixture",
        origin="teste",
        license="Apache-2.0",
        adapter="echo",
        provider="mock",
        capabilities=["chat", "ptbr"],
        min_ram_gb=0.1,
        status="available",
        limitations=["fixture simulada"],
    )


def failing_spec() -> ModelSpec:
    return make_spec("fail-primary", capabilities=["chat"], min_ram_gb=0.1)


class RouterRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ModelRegistry.builtin()
        self.router = ModelRouter(registry=self.registry, hardware=hardware(), environ={})

    def test_routes_to_free_local_capable_model(self) -> None:
        decision = self.router.route(RoutingRequest(task="ptbr"))
        self.assertIn(decision.model_id, self.registry.ids())
        self.assertTrue(decision.chain)
        self.assertEqual(decision.simulated, self.registry.get(decision.model_id).provider == "mock")

    def test_preferred_model_is_respected(self) -> None:
        decision = self.router.route(
            RoutingRequest(task="chat", preferred_model="sp-echo-baseline-v1")
        )
        self.assertEqual(decision.model_id, "sp-echo-baseline-v1")

    def test_missing_preferred_model_raises(self) -> None:
        with self.assertRaises(ModelNotFound):
            self.router.route(RoutingRequest(preferred_model="nao-existe"))

    def test_unavailable_model_is_rejected_with_reason(self) -> None:
        decision = self.router.route(RoutingRequest(task="chat"))
        rejected = {item.model_id: item.reasons for item in decision.rejected}
        self.assertIn("minimind-3-small", rejected)
        self.assertTrue(any("CHECKPOINT" in reason for reason in rejected["minimind-3-small"]))

    def test_paid_cost_is_rejected_by_policy(self) -> None:
        with self.assertRaises(PolicyViolation):
            RoutingPolicy(allow_paid=True)
        paid = ModelSpec(
            id="paid-model",
            name="Pago",
            origin="externo",
            license="proprietária",
            adapter="openai_compatible",
            provider="openai_compatible",
            capabilities=["chat"],
            cost="paid",
            status="available",
            endpoint="http://127.0.0.1:9",
            limitations=["serviço pago"],
        )
        router = ModelRouter(
            registry=ModelRegistry([paid]), hardware=hardware(), environ={}
        )
        with self.assertRaises(NoModelAvailable):
            router.route(RoutingRequest())

    def test_unknown_task_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            self.router.route(RoutingRequest(task="tarefa-inexistente"))

    def test_hardware_budget_excludes_big_models(self) -> None:
        small = ModelRouter(registry=self.registry, hardware=hardware(2.0), environ={})
        decision = small.route(RoutingRequest(task="chat"))
        rejected = {item.model_id for item in decision.rejected}
        self.assertIn("qwen2.5-1.5b-instruct-gguf", rejected)
        self.assertEqual(decision.model_id, "sp-echo-baseline-v1")


class RouterExecutionTests(unittest.TestCase):
    def _router(self, policy: RoutingPolicy, adapters: dict) -> ModelRouter:
        registry = ModelRegistry([failing_spec(), echo_spec()])
        return ModelRouter(
            registry=registry,
            hardware=hardware(),
            policy=policy,
            environ={},
            adapter_factory=adapter_factory(adapters),
        )

    def _adapters(self, error=None) -> dict:
        primary = FailingAdapter(failing_spec(), error)
        from solution_print.adapters import create_adapter

        echo = create_adapter(echo_spec(), environ={})
        return {"fail-primary": primary, "echo-fixture": echo}

    def test_successful_inference_is_logged_without_prompt_text(self) -> None:
        router = self._router(RoutingPolicy(), self._adapters())
        result = router.infer(
            request=RoutingRequest(preferred_model="echo-fixture"),
            messages=[Message("user", "texto sensível do cliente")],
        )
        self.assertEqual(result.response.model, "echo-fixture")
        self.assertTrue(result.response.simulated)
        self.assertEqual(len(router.execution_log), 1)
        entry = router.execution_log[0]
        self.assertNotIn("texto sensível", json.dumps(entry, ensure_ascii=False))
        self.assertEqual(len(entry["input_digest"]), 16)

    def test_authorised_fallback_is_used(self) -> None:
        router = self._router(
            RoutingPolicy(authorized_fallbacks=("echo-fixture",)), self._adapters()
        )
        result = router.infer(
            request=RoutingRequest(preferred_model="fail-primary"),
            messages=[Message("user", "oi")],
        )
        self.assertEqual(result.response.model, "echo-fixture")
        self.assertEqual(result.attempts[0]["status"], "error")
        self.assertEqual(result.attempts[1]["status"], "ok")

    def test_unauthorised_fallback_is_not_used(self) -> None:
        adapters = self._adapters()
        router = self._router(RoutingPolicy(), adapters)
        with self.assertRaises(AllModelsFailed):
            router.infer(
                request=RoutingRequest(preferred_model="fail-primary"),
                messages=[Message("user", "oi")],
            )
        self.assertEqual(adapters["echo-fixture"]._calls, 0)

    def test_timeout_is_reported_and_fallback_applies(self) -> None:
        adapters = self._adapters(AdapterTimeout("estourou"))
        router = self._router(
            RoutingPolicy(authorized_fallbacks=("echo-fixture",)), adapters
        )
        result = router.infer(
            request=RoutingRequest(preferred_model="fail-primary"),
            messages=[Message("user", "oi")],
        )
        self.assertEqual(result.attempts[0]["error_type"], "AdapterTimeout")
        self.assertEqual(result.response.model, "echo-fixture")

    def test_all_models_failing_raises(self) -> None:
        adapters = self._adapters(AdapterTimeout("estourou"))
        router = self._router(RoutingPolicy(), adapters)
        with self.assertRaises(AllModelsFailed) as ctx:
            router.infer(
                request=RoutingRequest(preferred_model="fail-primary"),
                messages=[Message("user", "oi")],
            )
        self.assertIn("fail-primary", str(ctx.exception))

    def test_missing_messages_raises(self) -> None:
        router = self._router(RoutingPolicy(), self._adapters())
        with self.assertRaises(ValidationError):
            router.infer(request=RoutingRequest(preferred_model="echo-fixture"))

    def test_execution_log_is_persisted_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "logs" / "router.jsonl"
            registry = ModelRegistry([echo_spec()])
            router = ModelRouter(
                registry=registry,
                hardware=hardware(),
                environ={},
                log_path=log_path,
            )
            router.infer(
                request=RoutingRequest(),
                messages=[Message("user", "registrar")],
            )
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["status"], "ok")
            self.assertNotIn("registrar", lines[0])


if __name__ == "__main__":
    unittest.main()
