"""Segurança de entrada, saída e de propostas de ferramentas.

Princípio central: **o laboratório não executa ações**. A saída do modelo é
somente uma *proposta*; quem decide e executa é o supervisor do JARVIS ou o
IAM do AI CORE. Este módulo valida, registra e recusa — nunca executa.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import PolicyViolation, ValidationError

MAX_INPUT_CHARS = 20_000
MAX_OUTPUT_CHARS = 64_000
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Nomes/prefixos que jamais podem ser habilitados como ferramenta de modelo.
PRIVILEGED_PREFIXES = (
    "shell",
    "exec",
    "system",
    "process",
    "filesystem",
    "file",
    "http",
    "network",
    "database",
    "db",
    "sql",
    "whatsapp",
    "meta",
    "billing",
    "payment",
    "deploy",
    "cloud",
)

SECRET_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_token", re.compile(r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("private_key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}")),
)

SUSPICIOUS_ARGUMENT_MARKERS = ("$(", "`", "&&", "||", ";", ">", "<", "\x00", "../")


def validate_input(text: str, max_chars: int = MAX_INPUT_CHARS) -> str:
    """Valida texto do usuário e devolve a versão normalizada."""
    if not isinstance(text, str):
        raise ValidationError("entrada deve ser texto")
    if not text.strip():
        raise ValidationError("entrada vazia")
    if len(text) > max_chars:
        raise ValidationError("entrada excede %d caracteres" % max_chars)
    if "\x00" in text:
        raise ValidationError("entrada contém byte nulo")
    return text.strip()


def sanitize_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> Tuple[str, List[str]]:
    """Remove escapes ANSI/controle e sinaliza truncamento ou marcadores."""
    flags: List[str] = []
    if not isinstance(text, str):
        raise ValidationError("saída deve ser texto")
    cleaned = ANSI_RE.sub("", text)
    if cleaned != text:
        flags.append("ansi_escape_removido")
    control = CONTROL_RE.sub("", cleaned)
    if control != cleaned:
        flags.append("caractere_controle_removido")
        cleaned = control
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
        flags.append("saida_truncada")
    if re.search(r"(?i)\b(system prompt|ignore (all )?previous|instru[cç][oõ]es anteriores)\b", cleaned):
        flags.append("possivel_prompt_injection_na_saida")
    if re.search(r"<\|?(tool_call|function_call)\|?>", cleaned):
        flags.append("marcador_de_ferramenta_na_saida")
    return cleaned, flags


def find_secrets(text: str) -> List[str]:
    """Retorna os *tipos* de segredo encontrados (nunca o valor)."""
    if not isinstance(text, str):
        return []
    return [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]


def redact_secrets(text: str) -> str:
    if not isinstance(text, str):
        return text
    redacted = text
    for name, pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED:%s]" % name, redacted)
    return redacted


@dataclass(frozen=True)
class ToolPermission:
    """Permissão declarada por um supervisor externo (JARVIS/AI CORE)."""

    name: str
    requires_approval: bool = True
    allowed_argument_keys: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not TOOL_NAME_RE.match(self.name):
            raise ValidationError("nome de ferramenta inválido: %r" % self.name)
        if is_privileged(self.name):
            raise PolicyViolation(
                "ferramenta privilegiada não pode ser habilitada no laboratório: %s" % self.name
            )


def is_privileged(name: str) -> bool:
    lowered = name.lower()
    return any(lowered == prefix or lowered.startswith(prefix + ".") or lowered.startswith(prefix + "_")
               for prefix in PRIVILEGED_PREFIXES)


@dataclass
class ToolProposal:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def digest(self) -> str:
        payload = json.dumps(self.arguments, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class ToolDecision:
    proposal: ToolProposal
    status: str  # denied | pending_approval
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.proposal.name,
            "arguments_digest": self.proposal.digest(),
            "status": self.status,
            "reasons": list(self.reasons),
        }


class ToolCallGateway:
    """Avalia propostas de ferramentas; nunca executa nada."""

    def __init__(
        self,
        permissions: Iterable[ToolPermission] = (),
        max_calls: int = 3,
        max_argument_bytes: int = 4096,
    ):
        self._permissions: Dict[str, ToolPermission] = {}
        for permission in permissions:
            permission.validate()
            self._permissions[permission.name] = permission
        self.max_calls = max_calls
        self.max_argument_bytes = max_argument_bytes
        self.audit_log: List[Dict[str, Any]] = []

    def grant(self, permission: ToolPermission) -> None:
        """Registra uma permissão concedida por um supervisor externo."""
        permission.validate()
        self._permissions[permission.name] = permission

    # ------------------------------------------------------------------ #
    # Parsing defensivo
    # ------------------------------------------------------------------ #
    def parse(self, raw_calls: Sequence[Any]) -> List[ToolProposal]:
        """Converte tool_calls crus em propostas; formato inválido é descartado."""
        proposals: List[ToolProposal] = []
        for item in raw_calls or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("tool") or ""
            if not isinstance(name, str):
                continue
            arguments = item.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_unparsed": True}
            if not isinstance(arguments, dict):
                arguments = {"_invalid": type(arguments).__name__}
            proposals.append(ToolProposal(name=name.strip(), arguments=arguments))
        return proposals

    # ------------------------------------------------------------------ #
    # Avaliação
    # ------------------------------------------------------------------ #
    def evaluate(self, proposals: Sequence[ToolProposal]) -> List[ToolDecision]:
        decisions: List[ToolDecision] = []
        if len(proposals) > self.max_calls:
            decisions.append(
                ToolDecision(
                    ToolProposal("_limit", {"count": len(proposals)}),
                    "denied",
                    ["limite de %d chamadas por resposta excedido" % self.max_calls],
                )
            )
            proposals = proposals[: self.max_calls]

        for proposal in proposals:
            decisions.append(self._evaluate_one(proposal))

        for decision in decisions:
            self.audit_log.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "tool": decision.proposal.name,
                    "status": decision.status,
                    "reasons": decision.reasons,
                    "arguments_digest": decision.proposal.digest(),
                }
            )
        return decisions

    def _evaluate_one(self, proposal: ToolProposal) -> ToolDecision:
        reasons: List[str] = []
        if not TOOL_NAME_RE.match(proposal.name or ""):
            return ToolDecision(proposal, "denied", ["nome de ferramenta inválido"])

        permission = self._permissions.get(proposal.name)
        if permission is None:
            return ToolDecision(
                proposal, "denied", ["ferramenta não autorizada pelo supervisor"]
            )

        reasons.extend(self._inspect_arguments(proposal, permission))
        if reasons:
            return ToolDecision(proposal, "denied", reasons)

        if permission.requires_approval:
            return ToolDecision(
                proposal,
                "pending_approval",
                ["proposta registrada; execução exige aprovação do supervisor externo"],
            )
        # Mesmo sem aprovação obrigatória, o laboratório não executa.
        return ToolDecision(
            proposal,
            "pending_approval",
            ["laboratório não executa ferramentas; encaminhado ao supervisor"],
        )

    def _inspect_arguments(self, proposal: ToolProposal, permission: ToolPermission) -> List[str]:
        reasons: List[str] = []
        try:
            size = len(json.dumps(proposal.arguments, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return ["argumentos não serializáveis"]
        if size > self.max_argument_bytes:
            reasons.append("argumentos excedem %d bytes" % self.max_argument_bytes)
        for key in proposal.arguments:
            if permission.allowed_argument_keys and key not in permission.allowed_argument_keys:
                reasons.append("chave de argumento não permitida: %s" % key)
        for value in proposal.arguments.values():
            if isinstance(value, str):
                if any(marker in value for marker in SUSPICIOUS_ARGUMENT_MARKERS):
                    reasons.append("argumento com metacaractere suspeito")
                    break
        return reasons

    # ------------------------------------------------------------------ #
    # Guarda explícita
    # ------------------------------------------------------------------ #
    def execute(self, *args: Any, **kwargs: Any) -> None:
        """Sempre recusa: execução é responsabilidade de outro projeto."""
        raise PolicyViolation(
            "o laboratório não executa ferramentas; envie a proposta ao supervisor autorizado"
        )
