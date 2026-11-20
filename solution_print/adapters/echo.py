"""Adaptador determinístico usado como fixture de testes e demonstração.

Ele **não é** um modelo de linguagem. Toda resposta carrega
``simulated=True`` para impedir que resultados de fixture sejam confundidos
com inferência real — exigência explícita do plano do laboratório.
"""

from __future__ import annotations

import hashlib
from typing import Dict, Optional, Tuple

from ..errors import AdapterUnavailable
from ..registry import ModelSpec
from .base import BaseAdapter, InferenceRequest, InferenceResponse


class EchoAdapter(BaseAdapter):
    """Devolve uma resposta espelhada, estável e identificada como simulada."""

    name = "echo"

    def __init__(self, spec: ModelSpec, environ: Optional[Dict[str, str]] = None):
        super().__init__(spec, environ)
        self._calls = 0

    def available(self) -> Tuple[bool, str]:
        return True, "fixture local sempre disponível (simulada, sem pesos)"

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        started = self._start_timer()
        request.validate()
        if request.model != self.spec.id:
            raise AdapterUnavailable(
                "adaptador de fixture %s não atende %s" % (self.spec.id, request.model)
            )
        self._calls += 1
        last_user = ""
        for message in reversed(request.messages):
            if message.role == "user":
                last_user = message.content.strip()
                break
        digest = hashlib.sha256(last_user.encode("utf-8")).hexdigest()[:12]
        text = (
            "[SIMULADO:%s] Recebi %d mensagem(ns). Última entrada (%d chars, sha256:%s): %s"
            % (
                self.spec.id,
                len(request.messages),
                len(last_user),
                digest,
                last_user[:280],
            )
        )
        return InferenceResponse(
            model=self.spec.id,
            text=text,
            provider=self.spec.provider,
            usage={
                "prompt_chars": sum(len(m.content) for m in request.messages),
                "completion_chars": len(text),
                "calls": self._calls,
            },
            latency_ms=self._elapsed_ms(started),
            simulated=True,
            finish_reason="stop",
        )

    def describe(self) -> Dict[str, object]:
        data = super().describe()
        data["simulated"] = True
        return data
