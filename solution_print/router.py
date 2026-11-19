"""Roteador de modelos orientado a tarefa, hardware e política de custo.

Regras invioláveis:

* custo pago é sempre recusado por padrão (``allow_paid=False``);
* fallback só ocorre entre modelos explicitamente autorizados;
* modelo que não cabe no hardware é recusado com motivo registrado;
* toda execução gera registro auditável (sem guardar o texto do usuário).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .adapters import BaseAdapter, InferenceRequest, InferenceResponse, Message, create_adapter
from .errors import (
    AdapterError,
    AllModelsFailed,
    ModelNotFound,
    NoModelAvailable,
    PolicyViolation,
    ValidationError,
)
from .hardware import HardwareInfo, available_headroom_gb, detect_hardware
from .registry import ModelRegistry, ModelSpec

TASK_CAPABILITIES: Dict[str, Tuple[str, ...]] = {
    "chat": ("chat",),
    "ptbr": ("chat", "ptbr"),
    "instruction": ("instruction",),
    "reasoning": ("reasoning",),
    "classification": ("classification",),
    "summarization": ("summarization",),
    "tool_calling": ("tool_calling",),
    "code": ("code",),
    "embeddings": ("embeddings",),
}


@dataclass(frozen=True)
class RoutingPolicy:
    """Política aplicada a todas as decisões de roteamento."""

    allow_paid: bool = False
    allowed_providers: Tuple[str, ...] = ("local", "openai_compatible", "mock")
    allow_mock: bool = True
    authorized_fallbacks: Tuple[str, ...] = ()
    max_attempts: int = 3
    default_temperature: float = 0.2
    default_max_tokens: int = 512

    def __post_init__(self) -> None:
        if self.allow_paid:
            raise PolicyViolation(
                "allow_paid=True não é permitido: o laboratório nunca aciona serviços pagos automaticamente"
            )
        if self.max_attempts < 1 or self.max_attempts > 3:
            raise ValidationError("max_attempts deve estar entre 1 e 3")


@dataclass
class RoutingRequest:
    task: str = "chat"
    required_capabilities: Tuple[str, ...] = ()
    preferred_model: Optional[str] = None
    max_cost: str = "free"
    temperature: float = 0.2
    max_tokens: int = 512
    metadata: Dict[str, Any] = field(default_factory=dict)

    def effective_capabilities(self) -> Tuple[str, ...]:
        if self.required_capabilities:
            return tuple(self.required_capabilities)
        try:
            return TASK_CAPABILITIES[self.task]
        except KeyError as exc:
            raise ValidationError("tarefa desconhecida: %s" % self.task) from exc


@dataclass
class Rejection:
    model_id: str
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"model_id": self.model_id, "reasons": list(self.reasons)}


@dataclass
class RouteDecision:
    model_id: str
    adapter: str
    task: str
    capabilities: List[str]
    reasons: List[str]
    chain: List[str]
    rejected: List[Rejection] = field(default_factory=list)
    hardware_profile: str = ""
    simulated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "adapter": self.adapter,
            "task": self.task,
            "capabilities": list(self.capabilities),
            "reasons": list(self.reasons),
            "chain": list(self.chain),
            "rejected": [item.to_dict() for item in self.rejected],
            "hardware_profile": self.hardware_profile,
            "simulated": self.simulated,
        }


@dataclass
class InferenceResult:
    response: InferenceResponse
    decision: RouteDecision
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "response": self.response.to_dict(),
            "decision": self.decision.to_dict(),
            "attempts": list(self.attempts),
        }


class ModelRouter:
    """Seleciona e executa modelos respeitando hardware, custo e autorização."""

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        hardware: Optional[HardwareInfo] = None,
        policy: Optional[RoutingPolicy] = None,
        environ: Optional[Dict[str, str]] = None,
        adapter_factory: Callable[..., BaseAdapter] = create_adapter,
        log_path: Optional[os.PathLike] = None,
    ):
        self.registry = registry or ModelRegistry.builtin()
        self.hardware = hardware or detect_hardware()
        self.policy = policy or RoutingPolicy()
        self.environ = environ if environ is not None else dict(os.environ)
        self._factory = adapter_factory
        self._adapters: Dict[str, BaseAdapter] = {}
        self._log_path = Path(log_path) if log_path else None
        self.execution_log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Adaptadores
    # ------------------------------------------------------------------ #
    def adapter_for(self, model_id: str) -> BaseAdapter:
        if model_id not in self._adapters:
            spec = self.registry.get(model_id)
            self._adapters[model_id] = self._factory(spec, environ=self.environ)
        return self._adapters[model_id]

    def availability(self, spec: ModelSpec) -> Tuple[bool, str]:
        """Disponibilidade efetiva: status declarado + adaptador operacional."""
        if spec.status == "unavailable":
            return False, "status 'unavailable'"
        if spec.status == "planned":
            return False, "status 'planned' (não implementado)"
        try:
            adapter = self.adapter_for(spec.id)
        except (ValidationError, RuntimeError) as exc:
            return False, "adaptador não instanciável: %s" % exc
        return adapter.available()

    # ------------------------------------------------------------------ #
    # Roteamento
    # ------------------------------------------------------------------ #
    def _evaluate(self, spec: ModelSpec, request: RoutingRequest) -> Tuple[Optional[float], List[str]]:
        reasons: List[str] = []
        if spec.cost == "paid":
            reasons.append("custo pago desativado por política")
        if request.max_cost == "free" and spec.cost != "free":
            reasons.append("solicitação exige custo zero")
        if spec.provider not in self.policy.allowed_providers:
            reasons.append("provedor não autorizado: %s" % spec.provider)
        if spec.provider == "mock" and not self.policy.allow_mock:
            reasons.append("adaptador simulado desativado por política")
        if spec.status not in {"available", "requires_setup"}:
            reasons.append("status não operacional: %s" % spec.status)

        missing = sorted(set(request.effective_capabilities()) - set(spec.capabilities))
        if missing:
            reasons.append("capacidades ausentes: %s" % ", ".join(missing))

        fits, hardware_reasons = spec.requirements_met(self.hardware)
        if not fits:
            reasons.extend(hardware_reasons)

        available, availability_reason = self.availability(spec)
        if not available:
            reasons.append("indisponível: %s" % availability_reason)

        if reasons:
            return None, reasons

        score = 0.0
        if spec.provider == "local":
            score += 30
        elif spec.provider == "openai_compatible":
            score += 15
        elif spec.provider == "mock":
            score += 5
        score += 5 * len(request.effective_capabilities())
        score += min(15.0, available_headroom_gb(self.hardware) / 2.0)
        if spec.parameters_m:
            score -= min(10.0, float(spec.parameters_m) / 1000.0)
        if request.preferred_model and spec.id == request.preferred_model:
            score += 1000

        selection = [
            "provedor %s" % spec.provider,
            "custo %s" % spec.cost,
            "cabe em %.1f GB de RAM" % self.hardware.ram_total_gb,
            "capacidades: %s" % ", ".join(request.effective_capabilities()),
        ]
        return score, selection

    def route(self, request: Optional[RoutingRequest] = None) -> RouteDecision:
        request = request or RoutingRequest()
        if request.preferred_model:
            if request.preferred_model not in self.registry:
                raise ModelNotFound("modelo preferido inexistente: %s" % request.preferred_model)

        scored: List[Tuple[float, ModelSpec, List[str]]] = []
        rejected: List[Rejection] = []
        for spec in self.registry.all():
            score, reasons = self._evaluate(spec, request)
            if score is None:
                rejected.append(Rejection(spec.id, reasons))
            else:
                scored.append((score, spec, reasons))

        if not scored:
            raise NoModelAvailable(
                "nenhum modelo atende à tarefa %s com custo %s; motivos: %s"
                % (
                    request.task,
                    request.max_cost,
                    "; ".join("%s: %s" % (r.model_id, ", ".join(r.reasons)) for r in rejected),
                )
            )

        scored.sort(key=lambda item: (-item[0], item[1].id))
        selected = scored[0][1]
        available_ids = [item[1].id for item in scored]

        chain = [selected.id]
        for fallback_id in self.policy.authorized_fallbacks:
            if fallback_id == selected.id:
                continue
            if fallback_id not in available_ids:
                rejected.append(
                    Rejection(fallback_id, ["fallback autorizado não está disponível nesta tarefa"])
                )
                continue
            if len(chain) >= self.policy.max_attempts:
                break
            chain.append(fallback_id)

        unauthorized = [item[1].id for item in scored if item[1].id not in chain]
        for model_id in unauthorized:
            rejected.append(Rejection(model_id, ["não autorizado como fallback"]))

        profile_key = ""
        try:
            from .hardware import classify_profile

            profile_key = classify_profile(self.hardware).key
        except Exception:  # pragma: no cover - defensivo
            profile_key = ""

        return RouteDecision(
            model_id=selected.id,
            adapter=selected.adapter,
            task=request.task,
            capabilities=list(selected.capabilities),
            reasons=list(scored[0][2]),
            chain=chain,
            rejected=rejected,
            hardware_profile=profile_key,
            simulated=selected.provider == "mock",
        )

    # ------------------------------------------------------------------ #
    # Execução
    # ------------------------------------------------------------------ #
    def infer(
        self,
        request: Optional[RoutingRequest] = None,
        messages: Optional[Sequence[Message]] = None,
        model_id: Optional[str] = None,
        infer_request: Optional[InferenceRequest] = None,
    ) -> InferenceResult:
        """Roteia e executa, com fallback apenas entre modelos autorizados."""
        request = request or RoutingRequest()
        if model_id:
            request = RoutingRequest(
                task=request.task,
                required_capabilities=request.required_capabilities,
                preferred_model=model_id,
                max_cost=request.max_cost,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata=request.metadata,
            )
        decision = self.route(request)
        if not messages and not infer_request:
            raise ValidationError("mensagens são obrigatórias para inferência")

        trace_id = uuid.uuid4().hex
        attempts: List[Dict[str, Any]] = []
        started = time.perf_counter()

        for candidate_id in decision.chain:
            spec = self.registry.get(candidate_id)
            payload = infer_request or InferenceRequest(
                model=candidate_id,
                messages=list(messages or []),
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata=dict(request.metadata),
            )
            payload.model = candidate_id
            attempt_started = time.perf_counter()
            try:
                adapter = self.adapter_for(candidate_id)
                response = adapter.infer(payload)
            except AdapterError as exc:
                attempts.append(
                    {
                        "model_id": candidate_id,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                        "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 3),
                    }
                )
                self._record(trace_id, candidate_id, "error", exc, attempt_started, payload)
                continue
            attempts.append(
                {
                    "model_id": candidate_id,
                    "status": "ok",
                    "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 3),
                }
            )
            self._record(trace_id, candidate_id, "ok", None, attempt_started, payload)
            return InferenceResult(
                response=response, decision=decision, attempts=attempts, trace_id=trace_id
            )

        self._record(
            trace_id,
            decision.model_id,
            "failed",
            AllModelsFailed("todos os modelos autorizados falharam"),
            started,
            None,
        )
        raise AllModelsFailed(
            "todos os modelos autorizados falharam: %s"
            % "; ".join("%s: %s" % (a["model_id"], a.get("error", "")) for a in attempts)
        )

    # ------------------------------------------------------------------ #
    # Auditoria
    # ------------------------------------------------------------------ #
    def _record(
        self,
        trace_id: str,
        model_id: str,
        status: str,
        error: Optional[BaseException],
        started: float,
        payload: Optional[InferenceRequest],
    ) -> None:
        entry = {
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_id": model_id,
            "status": status,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_type": type(error).__name__ if error else None,
            # O texto do usuário não é armazenado; apenas um hash para correlação.
            "input_digest": _digest(payload) if payload else None,
            "simulated": model_id.startswith("sp-echo"),
        }
        self.execution_log.append(entry)
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _digest(payload: InferenceRequest) -> str:
    joined = "\n".join("%s:%s" % (m.role, m.content) for m in payload.messages)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
