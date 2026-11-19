import unittest

from solution_print.errors import IntegrationError, PolicyViolation
from solution_print.integrations import (
    AiCoreClient,
    AndroidChatClient,
    CrmAiClient,
    CrmAiTask,
    InferenceEnvelopeRequest,
    JarvisBridge,
    JarvisSupervisorClient,
    LabProviderService,
    MobileChatRequest,
    ProviderManifest,
    Studio3DClient,
    Studio3DRequest,
    TenantContext,
    ToolProposalEnvelope,
    assert_no_pii,
    build_manifest,
    build_mobile_request,
    build_studio_request,
)
from solution_print.integrations.ai_core import INFER_PATH, MANIFEST_PATH
from solution_print.integrations.contracts import ModelDescriptor
from solution_print.integrations.http_client import JsonHttpClient, validate_base_url
from solution_print.router import ModelRouter
from solution_print.safety import ToolPermission

from .helpers import MockServer, chat_route, make_spec
from .test_router import echo_spec, hardware


def tenant(scopes=("ai.infer",)) -> TenantContext:
    return TenantContext(
        tenant_id="tenant-lab",
        user_id="user-1",
        grant_id="grant-1",
        scopes=list(scopes),
        request_id="req-1",
    )


def lab_router() -> ModelRouter:
    from solution_print.registry import ModelRegistry

    spec = make_spec("local-lab", provider="mock", adapter="echo", capabilities=["chat", "ptbr"])
    return ModelRouter(
        registry=ModelRegistry([spec]), hardware=hardware(), environ={}
    )


class TenantAndEnvelopeTests(unittest.TestCase):
    def test_valid_tenant(self) -> None:
        tenant().validate()

    def test_tenant_requires_scopes(self) -> None:
        with self.assertRaises(IntegrationError):
            tenant(scopes=()).validate()

    def test_tenant_rejects_invalid_identifiers(self) -> None:
        with self.assertRaises(IntegrationError):
            TenantContext("tenant lab!", "u", "g", ["ai.infer"]).validate()
        with self.assertRaises(IntegrationError):
            TenantContext("t", "", "g", ["ai.infer"]).validate()

    def test_envelope_validation(self) -> None:
        ok = InferenceEnvelopeRequest(
            tenant=tenant(), messages=[{"role": "user", "content": "oi"}]
        )
        ok.validate()
        with self.assertRaises(IntegrationError):
            InferenceEnvelopeRequest(tenant=tenant(), messages=[]).validate()
        with self.assertRaises(IntegrationError):
            InferenceEnvelopeRequest(
                tenant=tenant(), messages=[{"role": "root", "content": "oi"}]
            ).validate()
        with self.assertRaises(IntegrationError):
            InferenceEnvelopeRequest(
                tenant=tenant(),
                messages=[{"role": "user", "content": "x" * 9000}],
            ).validate()
        with self.assertRaises(IntegrationError):
            InferenceEnvelopeRequest(
                tenant=tenant(), messages=[{"role": "user", "content": "oi"}], max_tokens=0
            ).validate()

    def test_contract_version_mismatch_is_rejected(self) -> None:
        envelope = InferenceEnvelopeRequest(
            tenant=tenant(),
            messages=[{"role": "user", "content": "oi"}],
            contract_version="2.0",
        )
        with self.assertRaises(IntegrationError):
            envelope.validate()


class PiiTests(unittest.TestCase):
    def test_blocks_pii_fields_and_patterns(self) -> None:
        for payload in (
            {"cpf": "123"},
            {"cliente": {"email": "a@b.com"}},
            {"texto": "meu cpf é 123.456.789-00"},
            {"texto": "ligue para 11 98765-4321"},
            ["ok", {"telefone": "x"}],
        ):
            with self.assertRaises(IntegrationError, msg=repr(payload)):
                assert_no_pii(payload)

    def test_allows_anonymous_business_text(self) -> None:
        assert_no_pii({"texto": "O pedido 123 atrasou e o cliente quer o prazo."})


class CrmContractTests(unittest.TestCase):
    def test_authorised_task_types_only(self) -> None:
        with self.assertRaises(IntegrationError):
            CrmAiTask(task_type="delete_all", payload={"x": 1}).validate()
        task = CrmAiTask(task_type="summarize", payload={"text": "pedido atrasado"})
        task.validate()
        messages = task.to_messages()
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("CRM", messages[0]["content"])

    def test_crm_task_refuses_pii(self) -> None:
        with self.assertRaises(IntegrationError):
            CrmAiTask(task_type="classify", payload={"email": "a@b.com"}).validate()
        with self.assertRaises(IntegrationError):
            CrmAiTask(
                task_type="classify", payload={"text": "123.456.789-00"}
            ).validate()


class MobileAndStudioContractTests(unittest.TestCase):
    def test_mobile_contract(self) -> None:
        request = build_mobile_request(
            [{"role": "user", "content": "oi"}], app_version="1.0.0"
        )
        self.assertEqual(request.locale, "pt-BR")
        with self.assertRaises(IntegrationError):
            MobileChatRequest(
                messages=[{"role": "user", "content": "oi"}], locale="en-US"
            ).validate()
        with self.assertRaises(IntegrationError):
            MobileChatRequest(messages=[{"role": "user", "content": " "}]).validate()

    def test_studio_contract(self) -> None:
        request = build_studio_request("suggest_material", "quero uma peça resistente")
        request.validate()
        with self.assertRaises(IntegrationError):
            Studio3DRequest(operation="render_mesh", prompt="x").validate()
        with self.assertRaises(IntegrationError):
            Studio3DRequest(
                operation="describe_scene", prompt="cpf 123.456.789-00"
            ).validate()


class ManifestTests(unittest.TestCase):
    def test_manifest_exposes_only_free_models(self) -> None:
        from solution_print.registry import ModelRegistry

        registry = ModelRegistry(
            [
                make_spec("local-lab", provider="mock", adapter="echo"),
                make_spec(
                    "local-paid", provider="openai_compatible", adapter="echo", cost="paid"
                ),
            ]
        )
        router = ModelRouter(registry=registry, hardware=hardware(), environ={})
        manifest = build_manifest(registry, router)
        manifest.validate()
        ids = [model.model_id for model in manifest.models]
        self.assertIn("local-lab", ids)
        self.assertNotIn("local-paid", ids)
        self.assertTrue(all(model.cost == "free" for model in manifest.models))


class ModelDescriptorTests(unittest.TestCase):
    def test_paid_model_is_rejected_in_manifest(self) -> None:
        descriptor = ModelDescriptor(
            model_id="pago-x",
            name="Pago",
            provider="openai_compatible",
            capabilities=["chat"],
            cost="paid",
            requires_setup=False,
            simulated=False,
            license="proprietária",
        )
        with self.assertRaises(IntegrationError):
            descriptor.validate()

    def test_manifest_rejects_duplicate_models(self) -> None:
        model = ModelDescriptor(
            model_id="dup-1",
            name="Dup",
            provider="local",
            capabilities=["chat"],
            cost="free",
            requires_setup=False,
            simulated=False,
            license="Apache-2.0",
        )
        manifest = ProviderManifest(
            provider_id="solution-hub-lab",
            display_name="Lab",
            contract_version="1.0",
            generated_at="2026-01-01T00:00:00Z",
            models=[model, model],
        )
        with self.assertRaises(IntegrationError):
            manifest.validate()


class AiCoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LabProviderService(lab_router())

    def test_manifest_is_serialisable(self) -> None:
        manifest = self.service.manifest()
        self.assertEqual(manifest["provider_id"], "solution-hub-lab")
        self.assertEqual(manifest["contract_version"], "1.0")
        self.assertTrue(manifest["models"])

    def test_inference_with_delegated_scope(self) -> None:
        response = self.service.handle_inference(
            {
                "tenant": tenant().to_dict(),
                "messages": [{"role": "user", "content": "olá"}],
                "task": "chat",
            }
        )
        self.assertTrue(response["simulated"])
        self.assertEqual(response["tenant_id"], "tenant-lab")
        self.assertEqual(response["grant_id"], "grant-1")
        self.assertTrue(response["text"])

    def test_inference_without_scope_is_denied(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.service.handle_inference(
                {
                    "tenant": tenant(scopes=("crm.read",)).to_dict(),
                    "messages": [{"role": "user", "content": "olá"}],
                }
            )

    def test_inference_without_tenant_is_denied(self) -> None:
        with self.assertRaises(IntegrationError):
            self.service.handle_inference(
                {"messages": [{"role": "user", "content": "olá"}]}
            )


class AiCoreClientTests(unittest.TestCase):
    def test_discover_and_infer_over_http(self) -> None:
        def manifest_route(method, body):
            return 200, {
                "provider_id": "solution-hub-lab",
                "contract_version": "1.0",
                "models": [{"model_id": "local-lab"}],
            }

        def infer_route(method, body):
            assert body["tenant"]["grant_id"] == "grant-1"
            return 200, {"text": "resposta", "simulated": True, "model_id": "local-lab"}

        with MockServer({MANIFEST_PATH: manifest_route, INFER_PATH: infer_route}) as server:
            client = AiCoreClient(server.base_url, token_env="TEST_TOKEN", environ={"TEST_TOKEN": "abc"})
            manifest = client.discover()
            self.assertEqual(manifest["contract_version"], "1.0")
            response = client.infer(
                InferenceEnvelopeRequest(
                    tenant=tenant(), messages=[{"role": "user", "content": "oi"}]
                )
            )
            self.assertEqual(response["text"], "resposta")
            self.assertEqual(server.requests[0]["authorization"], "Bearer abc")

    def test_remote_plain_http_is_rejected(self) -> None:
        with self.assertRaises(IntegrationError):
            AiCoreClient("http://api.exemplo.com")
        self.assertEqual(validate_base_url("http://127.0.0.1:8080"), "http://127.0.0.1:8080")


class JarvisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = lab_router()
        self.bridge = JarvisBridge(self.router)

    def test_model_selection_and_inference(self) -> None:
        decision = self.bridge.select_model("ptbr")
        self.assertIn("model_id", decision)
        result = self.bridge.infer([{"role": "user", "content": "oi"}])
        self.assertEqual(result["supervisor"], "jarvis")
        self.assertEqual(result["memory_owner"], "jarvis")

    def test_tool_calls_become_proposals_only(self) -> None:
        envelopes = self.bridge.evaluate_tool_calls(
            [{"name": "crm.lookup_order", "arguments": {"order_id": "A1"}}], tenant()
        )
        self.assertEqual(envelopes[0]["status"], "denied")

        self.bridge.register_tool_permission(
            ToolPermission(name="crm.lookup_order", allowed_argument_keys=("order_id",))
        )
        envelopes = self.bridge.evaluate_tool_calls(
            [{"name": "crm.lookup_order", "arguments": {"order_id": "A1"}}], tenant()
        )
        self.assertEqual(envelopes[0]["status"], "pending_approval")
        self.assertEqual(envelopes[0]["supervisor"], "jarvis")

    def test_bridge_never_executes(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.bridge.execute_tool("shell", {"cmd": "ls"})

    def test_supervisor_rejects_executed_status(self) -> None:
        with MockServer({"/api/supervisor/tool-proposals": lambda m, b: (200, {"ok": True})}) as server:
            client = JarvisSupervisorClient(server.base_url, token_env=None)
            with self.assertRaises(PolicyViolation):
                client.submit([{"status": "executed", "tool": "x"}])
            self.assertEqual(server.requests, [])
            response = client.submit([{"status": "pending_approval", "tool": "crm.lookup_order"}])
            self.assertEqual(response["ok"], True)

    def test_proposal_envelope_cannot_claim_execution(self) -> None:
        envelope = ToolProposalEnvelope(
            request_id="r1", tenant=tenant(), tool="crm.lookup_order", arguments={}
        )
        envelope.status = "executed"
        with self.assertRaises(IntegrationError):
            envelope.validate()


class CrmClientTests(unittest.TestCase):
    def test_pii_is_blocked_before_any_request(self) -> None:
        with MockServer({"/api/ai/tasks": lambda m, b: (200, {"result": "ok"})}) as server:
            client = CrmAiClient(server.base_url, token_env=None)
            with self.assertRaises(IntegrationError):
                client.classify("contato: cliente@exemplo.com")
            self.assertEqual(server.requests, [])

    def test_clean_task_is_submitted(self) -> None:
        with MockServer({"/api/ai/tasks": lambda m, b: (200, {"result": {"label": "prazo"}})}) as server:
            client = CrmAiClient(server.base_url, token_env=None)
            response = client.classify("o pedido atrasou")
            self.assertEqual(response["result"]["label"], "prazo")
            self.assertEqual(server.requests[0]["body"]["task_type"], "classify")


class AndroidAndStudioClientTests(unittest.TestCase):
    def test_android_chat(self) -> None:
        with MockServer({"/v1/chat/completions": chat_route("olá do laboratório")}) as server:
            client = AndroidChatClient(server.base_url, token_env=None)
            result = client.chat(
                build_mobile_request([{"role": "user", "content": "oi"}], app_version="1.0")
            )
            self.assertEqual(result["text"], "olá do laboratório")
            self.assertEqual(result["locale"], "pt-BR")

    def test_android_rejects_bad_locale_before_network(self) -> None:
        with MockServer({}) as server:
            client = AndroidChatClient(server.base_url, token_env=None)
            with self.assertRaises(IntegrationError):
                client.chat(
                    MobileChatRequest(
                        messages=[{"role": "user", "content": "oi"}], locale="en-US"
                    )
                )
            self.assertEqual(server.requests, [])

    def test_studio_request(self) -> None:
        with MockServer({"/v1/chat/completions": chat_route("use PETG")}) as server:
            client = Studio3DClient(server.base_url, token_env=None)
            result = client.request_ai(
                build_studio_request("suggest_material", "peça resistente", scene_id="cena-1")
            )
            self.assertEqual(result["text"], "use PETG")
            self.assertEqual(result["operation"], "suggest_material")
            self.assertEqual(result["scene_id"], "cena-1")


class HttpClientTests(unittest.TestCase):
    def test_error_status_raises_integration_error(self) -> None:
        with MockServer({"/x": lambda m, b: (500, {"error": "falha"})}) as server:
            client = JsonHttpClient(server.base_url)
            with self.assertRaises(IntegrationError) as ctx:
                client.get("/x")
            self.assertIn("HTTP 500", str(ctx.exception))

    def test_non_json_response_raises(self) -> None:
        with MockServer({"/x": lambda m, b: (200, b"nao json")}) as server:
            client = JsonHttpClient(server.base_url)
            with self.assertRaises(IntegrationError):
                client.get("/x")

    def test_timeout_is_reported(self) -> None:
        import time

        def slow(method, body):
            time.sleep(0.8)
            return 200, {"ok": True}

        with MockServer({"/x": slow}) as server:
            client = JsonHttpClient(server.base_url, timeout=0.2)
            with self.assertRaises(IntegrationError) as ctx:
                client.get("/x")
            self.assertIn("timeout", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
