import json
import sys
import time
import unittest
from typing import Any, Dict, Tuple

from solution_print.adapters import Message, create_adapter
from solution_print.adapters.base import InferenceRequest
from solution_print.adapters.openai_compat import validate_endpoint
from solution_print.errors import (
    AdapterTimeout,
    AdapterUnavailable,
    ConfigurationError,
    MalformedResponse,
    ValidationError,
)
from solution_print.registry import ModelSpec

from .helpers import MockServer, chat_route, make_spec


def request(model_id: str, text: str = "olá") -> InferenceRequest:
    return InferenceRequest(model=model_id, messages=[Message("user", text)])


class EchoAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = ModelSpec(
            id="echo-test",
            name="Echo",
            origin="teste",
            license="Apache-2.0",
            adapter="echo",
            provider="mock",
            capabilities=["chat"],
            status="available",
            limitations=["fixture"],
        )
        self.adapter = create_adapter(self.spec, environ={})

    def test_is_available_and_simulated(self) -> None:
        ok, reason = self.adapter.available()
        self.assertTrue(ok, reason)
        response = self.adapter.infer(request("echo-test", "teste de eco"))
        self.assertTrue(response.simulated)
        self.assertIn("SIMULADO", response.text)
        self.assertGreater(response.latency_ms, 0)

    def test_is_deterministic(self) -> None:
        first = self.adapter.infer(request("echo-test", "mesma entrada"))
        second = self.adapter.infer(request("echo-test", "mesma entrada"))
        self.assertEqual(first.text, second.text)

    def test_rejects_empty_message(self) -> None:
        with self.assertRaises(ValidationError):
            self.adapter.infer(
                InferenceRequest(model="echo-test", messages=[Message("user", "   ")])
            )


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = make_spec("local-test")

    def _adapter(self, endpoint: str, environ: Dict[str, str] = None, timeout: float = 2.0):
        spec = make_spec("local-test", endpoint=endpoint)
        return create_adapter(spec, environ=environ or {}, timeout=timeout)

    def test_successful_inference(self) -> None:
        with MockServer({"/chat/completions": chat_route("olá do modelo local")}) as server:
            adapter = self._adapter(server.base_url)
            response = adapter.infer(request("local-test", "pergunta"))
            self.assertEqual(response.text, "olá do modelo local")
            self.assertFalse(response.simulated)
            self.assertEqual(response.usage.get("completion_tokens"), 2)
        sent = server.requests[0]["body"]
        self.assertEqual(sent["model"], "Modelo de teste local-test")
        self.assertEqual(sent["messages"][0]["content"], "pergunta")

    def test_http_error_becomes_adapter_unavailable(self) -> None:
        with MockServer({"/chat/completions": lambda m, b: (500, {"error": "boom"})}) as server:
            adapter = self._adapter(server.base_url)
            with self.assertRaises(AdapterUnavailable):
                adapter.infer(request("local-test"))

    def test_auth_error_is_not_leaked(self) -> None:
        with MockServer({"/chat/completions": lambda m, b: (401, {"error": "no"})}) as server:
            adapter = self._adapter(server.base_url)
            with self.assertRaises(AdapterUnavailable) as ctx:
                adapter.infer(request("local-test"))
            self.assertIn("autenticação", str(ctx.exception))

    def test_malformed_json(self) -> None:
        with MockServer({"/chat/completions": lambda m, b: (200, b"<html>nao json</html>")}) as server:
            adapter = self._adapter(server.base_url)
            with self.assertRaises(MalformedResponse):
                adapter.infer(request("local-test"))

    def test_missing_choices(self) -> None:
        with MockServer({"/chat/completions": lambda m, b: (200, {"model": "x"})}) as server:
            adapter = self._adapter(server.base_url)
            with self.assertRaises(MalformedResponse):
                adapter.infer(request("local-test"))

    def test_empty_content(self) -> None:
        payload = {"choices": [{"message": {"content": "   "}}]}
        with MockServer({"/chat/completions": lambda m, b: (200, payload)}) as server:
            adapter = self._adapter(server.base_url)
            with self.assertRaises(MalformedResponse):
                adapter.infer(request("local-test"))

    def test_timeout_is_typed(self) -> None:
        def slow(method: str, body: Dict[str, Any]) -> Tuple[int, Any]:
            time.sleep(1.0)
            return 200, {"choices": [{"message": {"content": "tarde"}}]}

        with MockServer({"/chat/completions": slow}) as server:
            adapter = self._adapter(server.base_url, timeout=0.25)
            with self.assertRaises(AdapterTimeout):
                adapter.infer(request("local-test"))

    def test_no_endpoint_configured(self) -> None:
        adapter = create_adapter(make_spec("local-test", endpoint=None), environ={})
        ok, reason = adapter.available()
        self.assertFalse(ok)
        self.assertIn("endpoint não configurado", reason)
        with self.assertRaises(AdapterUnavailable):
            adapter.infer(request("local-test"))

    def test_endpoint_from_environment(self) -> None:
        spec = make_spec("local-test", endpoint=None, endpoint_env="TEST_LOCAL_ENDPOINT")
        adapter = create_adapter(spec, environ={"TEST_LOCAL_ENDPOINT": "http://127.0.0.1:9999"})
        ok, _ = adapter.available()
        self.assertTrue(ok)

    def test_remote_endpoint_blocked_by_default(self) -> None:
        spec = make_spec("local-test", endpoint="https://api.exemplo.com/v1")
        adapter = create_adapter(spec, environ={})
        ok, reason = adapter.available()
        self.assertFalse(ok)
        self.assertIn("remoto bloqueado", reason)
        with self.assertRaises(ConfigurationError):
            validate_endpoint("https://api.exemplo.com/v1")

    def test_remote_endpoint_allowed_only_with_opt_in(self) -> None:
        spec = make_spec("local-test", endpoint="https://api.exemplo.com/v1")
        adapter = create_adapter(
            spec, environ={"SOLUTION_PRINT_ALLOW_REMOTE_MODELS": "1"}
        )
        ok, _ = adapter.available()
        self.assertTrue(ok)
        self.assertEqual(
            validate_endpoint("https://api.exemplo.com/v1", allow_remote=True),
            "https://api.exemplo.com/v1",
        )

    def test_endpoint_with_credentials_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            validate_endpoint("http://user:pass@127.0.0.1:8080")

    def test_api_key_not_sent_when_absent(self) -> None:
        with MockServer({"/chat/completions": chat_route()}) as server:
            adapter = self._adapter(server.base_url)
            adapter.infer(request("local-test"))
        self.assertIsNone(server.requests[0]["authorization"])


class MiniMindAdapterTests(unittest.TestCase):
    def test_unavailable_without_checkpoint_and_without_importing_torch(self) -> None:
        self.assertNotIn("torch", sys.modules)
        spec = ModelSpec(
            id="minimind-test",
            name="MiniMind",
            origin="jingyaogong/minimind",
            license="Apache-2.0",
            adapter="minimind",
            provider="minimind",
            capabilities=["chat"],
            min_ram_gb=4.0,
            status="requires_setup",
            limitations=["precisa de checkpoint .pth"],
        )
        adapter = create_adapter(spec, environ={})
        ok, reason = adapter.available()
        self.assertFalse(ok)
        self.assertIn("CHECKPOINT", reason)
        with self.assertRaises(AdapterUnavailable):
            adapter.infer(request("minimind-test"))
        self.assertNotIn("torch", sys.modules, "torch não deve ser importado sem checkpoint")


if __name__ == "__main__":
    unittest.main()
