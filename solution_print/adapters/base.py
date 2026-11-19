"""Contrato comum de adaptadores de inferência.

Todo adaptador recebe e devolve os mesmos tipos. Isso permite trocar MiniMind,
llama.cpp local ou qualquer endpoint compatível sem alterar roteador,
avaliação, API ou integrações.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ValidationError
from ..registry import ModelSpec

VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})
MAX_MESSAGE_CHARS = 32_000
MAX_TOTAL_CHARS = 64_000
MAX_TOKENS_LIMIT = 4096


@dataclass
class Message:
    role: str
    content: str

    def validate(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValidationError("role inválido: %r" % self.role)
        if not isinstance(self.content, str):
            raise ValidationError("content deve ser texto")
        if not self.content.strip():
            raise ValidationError("content vazio")
        if len(self.content) > MAX_MESSAGE_CHARS:
            raise ValidationError(
                "content excede %d caracteres" % MAX_MESSAGE_CHARS
            )

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class InferenceRequest:
    model: str
    messages: List[Message]
    temperature: float = 0.2
    max_tokens: int = 512
    tools: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.model:
            raise ValidationError("model obrigatório")
        if not self.messages:
            raise ValidationError("pelo menos uma mensagem é obrigatória")
        if len(self.messages) > 200:
            raise ValidationError("histórico excessivo (máx. 200 mensagens)")
        total = 0
        for message in self.messages:
            message.validate()
            total += len(message.content)
        if total > MAX_TOTAL_CHARS:
            raise ValidationError("conversa excede %d caracteres" % MAX_TOTAL_CHARS)
        if not (0.0 <= float(self.temperature) <= 2.0):
            raise ValidationError("temperature deve estar entre 0 e 2")
        if not (1 <= int(self.max_tokens) <= MAX_TOKENS_LIMIT):
            raise ValidationError("max_tokens deve estar entre 1 e %d" % MAX_TOKENS_LIMIT)
        if self.tools and not isinstance(self.tools, list):
            raise ValidationError("tools deve ser uma lista")

    def as_chat_payload(self) -> List[Dict[str, str]]:
        return [message.to_dict() for message in self.messages]


@dataclass
class InferenceResponse:
    model: str
    text: str
    provider: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    simulated: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "text": self.text,
            "provider": self.provider,
            "usage": self.usage,
            "latency_ms": round(self.latency_ms, 3),
            "finish_reason": self.finish_reason,
            "simulated": self.simulated,
            "tool_calls": self.tool_calls,
        }


class BaseAdapter(ABC):
    """Interface mínima de um adaptador."""

    name = "base"

    def __init__(self, spec: ModelSpec, environ: Optional[Dict[str, str]] = None):
        self.spec = spec
        self._environ = environ

    # ------------------------------------------------------------------ #
    # Disponibilidade
    # ------------------------------------------------------------------ #
    @abstractmethod
    def available(self) -> Tuple[bool, str]:
        """Retorna ``(disponivel, motivo)`` sem carregar pesos nem rede."""

    # ------------------------------------------------------------------ #
    # Inferência
    # ------------------------------------------------------------------ #
    @abstractmethod
    def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Executa a inferência ou levanta uma subclasse de AdapterError."""

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _start_timer() -> float:
        return time.perf_counter()

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000.0

    def describe(self) -> Dict[str, Any]:
        ok, reason = self.available()
        return {
            "adapter": self.name,
            "model": self.spec.id,
            "available": ok,
            "reason": reason,
            "provider": self.spec.provider,
            "cost": self.spec.cost,
        }

    def __repr__(self) -> str:  # pragma: no cover - conveniência
        return "<%s model=%s>" % (type(self).__name__, self.spec.id)
