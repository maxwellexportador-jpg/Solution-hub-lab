"""Contratos de integração versionados do laboratório.

Cada projeto do ecossistema tem responsabilidades próprias. Estes contratos
apenas descrevem o que trafega e quem autoriza — não concedem permissão nem
substituem IAM, supervisor ou regras de negócio de nenhum projeto.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .. import CONTRACT_VERSION
from ..errors import IntegrationError, ValidationError

PROVIDER_ID = "solution-hub-lab"
MAX_PAYLOAD_CHARS = 8_000
MAX_MESSAGES = 40

#: Chaves que nunca podem chegar ao laboratório vindas do CRM.
PII_KEYS = frozenset(
    {
        "cpf",
        "cnpj",
        "rg",
        "phone",
        "telefone",
        "celular",
        "whatsapp",
        "email",
        "e-mail",
        "address",
        "endereco",
        "endereço",
        "card",
        "cartao",
        "cartão",
        "password",
        "senha",
        "token",
        "secret",
    }
)

PII_PATTERNS = (
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("cnpj", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}\b")),
)

TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,63}$")
MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TenantContext:
    """Identidade delegada por AI CORE/JARVIS. O laboratório não a cria."""

    tenant_id: str
    user_id: str
    grant_id: str
    scopes: List[str] = field(default_factory=list)
    request_id: str = ""

    def validate(self) -> None:
        for name in ("tenant_id", "user_id", "grant_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not TENANT_RE.match(value):
                raise IntegrationError("contexto de tenant inválido: %s" % name)
        if not self.scopes:
            raise IntegrationError(
                "scopes ausentes: o laboratório não infere permissões por conta própria"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelDescriptor:
    """Modelo exposto ao ecossistema, com custo e simulação explícitos."""

    model_id: str
    name: str
    provider: str
    capabilities: List[str]
    cost: str
    requires_setup: bool
    simulated: bool
    license: str
    limitations: List[str] = field(default_factory=list)

    def validate(self) -> None:
        if not MODEL_RE.match(self.model_id):
            raise IntegrationError("model_id inválido no manifesto: %s" % self.model_id)
        if self.cost not in {"free", "paid"}:
            raise IntegrationError("custo inválido no manifesto: %s" % self.cost)
        if self.cost == "paid":
            raise IntegrationError(
                "o laboratório não publica modelos pagos sem autorização explícita"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderManifest:
    """Manifesto de descoberta consumido pelo AI CORE."""

    provider_id: str
    display_name: str
    contract_version: str
    generated_at: str
    models: List[ModelDescriptor]
    endpoints: Dict[str, str] = field(default_factory=dict)
    simulation_notice: str = (
        "Modelos com simulated=true são fixtures locais e não representam qualidade de IA."
    )

    def validate(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise IntegrationError(
                "versão de contrato incompatível: %s (esperado %s)"
                % (self.contract_version, CONTRACT_VERSION)
            )
        if not self.models:
            raise IntegrationError("manifesto sem modelos")
        seen = set()
        for model in self.models:
            model.validate()
            if model.model_id in seen:
                raise IntegrationError("modelo duplicado no manifesto: %s" % model.model_id)
            seen.add(model.model_id)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data


@dataclass
class InferenceEnvelopeRequest:
    """Solicitação padronizada de inferência."""

    tenant: TenantContext
    messages: List[Dict[str, str]]
    task: str = "chat"
    model_id: Optional[str] = None
    max_tokens: int = 256
    temperature: float = 0.2
    metadata: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION

    def validate(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise IntegrationError("versão de contrato incompatível")
        self.tenant.validate()
        if not self.messages:
            raise IntegrationError("mensagens obrigatórias")
        if len(self.messages) > MAX_MESSAGES:
            raise IntegrationError("histórico excessivo")
        total = 0
        for message in self.messages:
            if not isinstance(message, dict):
                raise IntegrationError("mensagem inválida")
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"}:
                raise IntegrationError("role inválido na mensagem")
            if not isinstance(content, str) or not content.strip():
                raise IntegrationError("conteúdo de mensagem vazio")
            total += len(content)
        if total > MAX_PAYLOAD_CHARS:
            raise IntegrationError("mensagens excedem o limite de %d caracteres" % MAX_PAYLOAD_CHARS)
        if not (1 <= int(self.max_tokens) <= 4096):
            raise IntegrationError("max_tokens fora do intervalo permitido")
        if not (0.0 <= float(self.temperature) <= 2.0):
            raise IntegrationError("temperature fora do intervalo permitido")
        if self.model_id and not MODEL_RE.match(self.model_id):
            raise IntegrationError("model_id inválido")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tenant"] = self.tenant.to_dict()
        return data


@dataclass
class InferenceEnvelopeResponse:
    request_id: str
    model_id: str
    text: str
    provider: str
    simulated: bool
    latency_ms: float
    usage: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolProposalEnvelope:
    """Proposta de ferramenta para o supervisor do JARVIS.

    ``execute`` não existe de propósito: este contrato é somente de proposta.
    """

    request_id: str
    tenant: TenantContext
    tool: str
    arguments: Dict[str, Any]
    status: str = "pending_approval"
    supervisor: str = "jarvis"
    contract_version: str = CONTRACT_VERSION

    def validate(self) -> None:
        self.tenant.validate()
        if not TENANT_RE.match(self.tool.replace(".", "_")):
            raise IntegrationError("nome de ferramenta inválido")
        if self.status != "pending_approval":
            raise IntegrationError("laboratório só pode emitir propostas pendentes de aprovação")
        if self.supervisor != "jarvis":
            raise IntegrationError("supervisor deve ser 'jarvis'")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tenant"] = self.tenant.to_dict()
        return data


def assert_no_pii(payload: Any, path: str = "payload") -> None:
    """Recusa qualquer carga com PII, sem ecoar os valores encontrados."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in PII_KEYS:
                raise IntegrationError(
                    "campo com dado pessoal proibido em %s.%s; mantenha PII no CRM" % (path, key)
                )
            assert_no_pii(value, "%s.%s" % (path, key))
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_no_pii(item, "%s[%d]" % (path, index))
    elif isinstance(payload, str):
        for name, pattern in PII_PATTERNS:
            if pattern.search(payload):
                raise IntegrationError(
                    "texto contém possível %s em %s; o laboratório não recebe PII" % (name, path)
                )


@dataclass
class CrmAiTask:
    """Tarefa autorizada do CRM (sem acesso a banco e sem PII)."""

    task_type: str
    payload: Dict[str, Any]
    model_id: Optional[str] = None
    max_tokens: int = 256
    contract_version: str = CONTRACT_VERSION

    ALLOWED_TYPES = frozenset({"classify", "summarize", "draft_reply", "assist"})

    def validate(self) -> None:
        if self.task_type not in self.ALLOWED_TYPES:
            raise IntegrationError("tipo de tarefa não autorizado: %s" % self.task_type)
        if not isinstance(self.payload, dict) or not self.payload:
            raise IntegrationError("payload obrigatório")
        assert_no_pii(self.payload)
        if len(str(self.payload)) > MAX_PAYLOAD_CHARS:
            raise IntegrationError("payload excede %d caracteres" % MAX_PAYLOAD_CHARS)

    def to_messages(self) -> List[Dict[str, str]]:
        import json

        return [
            {
                "role": "system",
                "content": "Você apoia o CRM Solution Hub. Responda em português do Brasil, "
                "sem inventar dados e sem solicitar informações pessoais.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"task": self.task_type, "payload": self.payload}, ensure_ascii=False
                ),
            },
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "task_type": self.task_type,
            "model_id": self.model_id,
            "max_tokens": self.max_tokens,
            "payload": self.payload,
        }


@dataclass
class MobileChatRequest:
    """Contrato do app Android (Expo/React Native)."""

    messages: List[Dict[str, str]]
    locale: str = "pt-BR"
    app_version: str = ""
    model_id: Optional[str] = None
    max_tokens: int = 256
    contract_version: str = CONTRACT_VERSION

    def validate(self) -> None:
        if not self.messages:
            raise IntegrationError("mensagens obrigatórias")
        if self.locale != "pt-BR":
            raise IntegrationError("locale não suportado nesta versão: %s" % self.locale)
        for message in self.messages:
            if not isinstance(message, dict) or message.get("role") not in {
                "user",
                "assistant",
                "system",
            }:
                raise IntegrationError("mensagem inválida no contrato mobile")
            if not isinstance(message.get("content"), str) or not message["content"].strip():
                raise IntegrationError("conteúdo vazio no contrato mobile")
        if len(self.messages) > MAX_MESSAGES:
            raise IntegrationError("histórico excessivo no contrato mobile")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Studio3DRequest:
    """Contrato do Studio 3D: apoio textual, sem tocar no núcleo 3D."""

    operation: str
    prompt: str
    scene_id: Optional[str] = None
    locale: str = "pt-BR"
    model_id: Optional[str] = None
    max_tokens: int = 256
    contract_version: str = CONTRACT_VERSION

    ALLOWED_OPERATIONS = frozenset(
        {"describe_scene", "suggest_material", "generate_prompt", "explain_3d_term"}
    )

    def validate(self) -> None:
        if self.operation not in self.ALLOWED_OPERATIONS:
            raise IntegrationError("operação 3D não autorizada: %s" % self.operation)
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise IntegrationError("prompt obrigatório")
        if len(self.prompt) > 4000:
            raise IntegrationError("prompt excede 4000 caracteres")
        assert_no_pii(self.prompt, "prompt")
        if self.locale != "pt-BR":
            raise IntegrationError("locale não suportado: %s" % self.locale)

    def to_messages(self) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "Você é assistente do Solution Print Studio 3D. Responda em "
                "português do Brasil, de forma curta e aplicada a impressão 3D.",
            },
            {"role": "user", "content": "[%s] %s" % (self.operation, self.prompt)},
        ]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
