"""Integração com o Solution Print AI CORE.

Divisão de responsabilidades (não negociável):

* AI CORE: identidade, sessão, grants, isolamento por tenant, autorização e auditoria.
* Laboratório: descoberta de modelos, inferência padronizada e metadados.

O laboratório **valida** o contexto delegado (tenant/grant/scopes) e recusa
qualquer chamada sem escopo explícito; ele nunca cria permissões.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import CONTRACT_VERSION
from ..adapters import Message
from ..errors import IntegrationError, NoModelAvailable, PolicyViolation
from ..registry import ModelRegistry
from ..router import ModelRouter, RoutingPolicy, RoutingRequest
from .contracts import (
    PROVIDER_ID,
    InferenceEnvelopeRequest,
    ModelDescriptor,
    ProviderManifest,
    TenantContext,
)
from .http_client import JsonHttpClient

REQUIRED_SCOPE = "ai.infer"
MANIFEST_PATH = "/api/providers/%s/manifest" % PROVIDER_ID
INFER_PATH = "/api/providers/%s/infer" % PROVIDER_ID


def build_manifest(registry: ModelRegistry, router: ModelRouter) -> ProviderManifest:
    """Descreve ao AI CORE apenas modelos gratuitos conhecidos pelo laboratório."""
    models: List[ModelDescriptor] = []
    for spec in registry.all():
        if spec.cost != "free" or spec.status == "unavailable":
            continue
        available, _ = router.availability(spec)
        models.append(
            ModelDescriptor(
                model_id=spec.id,
                name=spec.name,
                provider=spec.provider,
                capabilities=list(spec.capabilities),
                cost=spec.cost,
                requires_setup=not available,
                simulated=spec.provider == "mock",
                license=spec.license,
                limitations=list(spec.limitations),
            )
        )
    manifest = ProviderManifest(
        provider_id=PROVIDER_ID,
        display_name="Solution Hub Lab (modelos locais e gratuitos)",
        contract_version=CONTRACT_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        models=models,
        endpoints={"manifest": MANIFEST_PATH, "infer": INFER_PATH},
    )
    manifest.validate()
    return manifest


class LabProviderService:
    """Implementa o lado do laboratório do contrato de provedor do AI CORE."""

    def __init__(self, router: ModelRouter, registry: Optional[ModelRegistry] = None):
        self.router = router
        self.registry = registry or router.registry

    def manifest(self) -> Dict[str, Any]:
        return build_manifest(self.registry, self.router).to_dict()

    def handle_inference(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Valida o envelope delegado e executa inferência gratuita."""
        if not isinstance(payload, dict):
            raise IntegrationError("payload deve ser objeto JSON")
        tenant_data = payload.get("tenant")
        if not isinstance(tenant_data, dict):
            raise IntegrationError("contexto de tenant ausente: AI CORE é a autoridade de identidade")
        tenant = TenantContext(
            tenant_id=str(tenant_data.get("tenant_id", "")),
            user_id=str(tenant_data.get("user_id", "")),
            grant_id=str(tenant_data.get("grant_id", "")),
            scopes=[str(item) for item in tenant_data.get("scopes", [])],
            request_id=str(tenant_data.get("request_id", "")),
        )
        tenant.validate()
        if REQUIRED_SCOPE not in tenant.scopes:
            raise PolicyViolation(
                "grant sem escopo %s; o laboratório não amplia permissões" % REQUIRED_SCOPE
            )

        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise IntegrationError("messages deve ser lista")
        envelope = InferenceEnvelopeRequest(
            tenant=tenant,
            messages=[item for item in messages if isinstance(item, dict)],
            task=str(payload.get("task", "chat")),
            model_id=payload.get("model_id"),
            max_tokens=int(payload.get("max_tokens", 256)),
            temperature=float(payload.get("temperature", 0.2)),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            contract_version=str(payload.get("contract_version", CONTRACT_VERSION)),
        )
        envelope.validate()

        request = RoutingRequest(
            task=envelope.task,
            preferred_model=envelope.model_id,
            max_cost="free",
            temperature=envelope.temperature,
            max_tokens=envelope.max_tokens,
            metadata=dict(envelope.metadata, tenant_id=tenant.tenant_id, grant_id=tenant.grant_id),
        )
        result = self.router.infer(
            request=request,
            messages=[Message(item["role"], item["content"]) for item in envelope.messages],
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "request_id": tenant.request_id or result.trace_id,
            "trace_id": result.trace_id,
            "model_id": result.response.model,
            "provider": result.response.provider,
            "text": result.response.text,
            "simulated": result.response.simulated,
            "latency_ms": round(result.response.latency_ms, 3),
            "usage": result.response.usage,
            "grant_id": tenant.grant_id,
            "tenant_id": tenant.tenant_id,
        }


class AiCoreClient:
    """Cliente do laboratório para falar com o AI CORE (lado chamador)."""

    def __init__(self, base_url: str, token_env: str = "AI_CORE_SERVICE_TOKEN", **kwargs: Any):
        self.http = JsonHttpClient(base_url, token_env=token_env, **kwargs)

    def discover(self, path: str = MANIFEST_PATH) -> Dict[str, Any]:
        return self.http.get(path)

    def infer(self, envelope: InferenceEnvelopeRequest, path: str = INFER_PATH) -> Dict[str, Any]:
        envelope.validate()
        return self.http.post(path, envelope.to_dict())


def infer_with_ai_core(
    client: AiCoreClient,
    tenant: TenantContext,
    messages: List[Dict[str, str]],
    task: str = "chat",
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Atalho com validação local antes de qualquer chamada de rede."""
    envelope = InferenceEnvelopeRequest(
        tenant=tenant, messages=messages, task=task, model_id=model_id
    )
    envelope.validate()
    return client.infer(envelope)


__all__ = [
    "AiCoreClient",
    "LabProviderService",
    "REQUIRED_SCOPE",
    "build_manifest",
    "infer_with_ai_core",
]
