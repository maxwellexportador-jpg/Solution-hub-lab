"""Adaptador para qualquer servidor local compatível com a API da OpenAI.

Cobre llama.cpp, Ollama (``/v1``), vLLM e LM Studio. Regras de segurança:

* só aceita endpoints locais/privados por padrão; endpoint público exige
  ``SOLUTION_PRINT_ALLOW_REMOTE_MODELS=1`` explícito do operador;
* nunca envia a chave de API em log, erro ou resposta;
* não faz retentativa automática (evita duplicar custo/latência);
* valida o formato da resposta e falha de forma tipada.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from ..errors import AdapterTimeout, AdapterUnavailable, ConfigurationError, MalformedResponse
from ..registry import ModelSpec
from .base import BaseAdapter, InferenceRequest, InferenceResponse

ALLOW_REMOTE_ENV = "SOLUTION_PRINT_ALLOW_REMOTE_MODELS"
API_KEY_ENV = "SOLUTION_PRINT_MODEL_API_KEY"
DEFAULT_TIMEOUT = 30.0
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"})


def _is_local_host(host: str) -> bool:
    if not host:
        return False
    host = host.lower().strip("[]")
    if host in LOCAL_HOSTS or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def validate_endpoint(url: str, allow_remote: bool = False) -> str:
    """Valida esquema/host e devolve a URL normalizada (sem credenciais)."""
    if not url:
        raise ConfigurationError("endpoint não configurado para o modelo")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigurationError("endpoint deve usar http ou https")
    if parsed.username or parsed.password:
        raise ConfigurationError("endpoint não pode embutir credenciais na URL")
    if not parsed.hostname:
        raise ConfigurationError("endpoint sem host")
    if not allow_remote and not _is_local_host(parsed.hostname):
        raise ConfigurationError(
            "endpoint remoto bloqueado por política (%s). Use um servidor local ou "
            "defina %s=1 com autorização explícita." % (parsed.hostname, ALLOW_REMOTE_ENV)
        )
    return url


class OpenAICompatibleAdapter(BaseAdapter):
    """Cliente HTTP mínimo para ``POST {base}/chat/completions``."""

    name = "openai_compatible"

    def __init__(
        self,
        spec: ModelSpec,
        environ: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(spec, environ)
        self._timeout = timeout
        self._env = environ if environ is not None else os.environ

    # ------------------------------------------------------------------ #
    # Configuração
    # ------------------------------------------------------------------ #
    def _endpoint(self) -> Tuple[Optional[str], Optional[str]]:
        endpoint = self.spec.resolved_endpoint(self._env)
        if not endpoint:
            return None, (
                "endpoint não configurado: defina %s"
                % (self.spec.endpoint_env or "SOLUTION_PRINT_LOCAL_ENDPOINT")
            )
        try:
            validate_endpoint(
                endpoint, allow_remote=self._env.get(ALLOW_REMOTE_ENV) == "1"
            )
        except ConfigurationError as exc:
            return None, str(exc)
        return endpoint, None

    def available(self) -> Tuple[bool, str]:
        endpoint, error = self._endpoint()
        if not endpoint:
            return False, error or "endpoint indisponível"
        return True, "endpoint local configurado: %s" % endpoint

    # ------------------------------------------------------------------ #
    # Inferência
    # ------------------------------------------------------------------ #
    def infer(self, request: InferenceRequest) -> InferenceResponse:
        started = self._start_timer()
        request.validate()
        endpoint, error = self._endpoint()
        if not endpoint or error:
            raise AdapterUnavailable(error or "endpoint indisponível")

        payload: Dict[str, Any] = {
            "model": request.metadata.get("provider_model") or self.spec.name,
            "messages": request.as_chat_payload(),
            "temperature": float(request.temperature),
            "max_tokens": int(request.max_tokens),
            "stream": False,
        }
        if request.tools:
            if not self.spec.tool_calling:
                raise AdapterUnavailable(
                    "modelo %s não declara suporte a tool calling" % self.spec.id
                )
            payload["tools"] = request.tools

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = self._env.get(API_KEY_ENV, "").strip()
        if api_key:
            headers["Authorization"] = "Bearer %s" % api_key

        url = endpoint.rstrip("/") + "/chat/completions"
        http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(400).decode("utf-8", "replace")
            except Exception:  # pragma: no cover - leitura defensiva
                detail = ""
            detail = detail.replace(api_key, "***") if api_key else detail
            if exc.code in (401, 403):
                raise AdapterUnavailable(
                    "autenticação recusada pelo endpoint (HTTP %d)" % exc.code
                ) from exc
            raise AdapterUnavailable(
                "endpoint respondeu HTTP %d: %s" % (exc.code, detail[:200])
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise AdapterTimeout(
                "timeout de %.1fs ao chamar %s" % (self._timeout, endpoint)
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise AdapterTimeout("timeout ao chamar %s" % endpoint) from exc
            raise AdapterUnavailable("endpoint inacessível: %s" % type(reason).__name__) from exc
        except OSError as exc:  # pragma: no cover - rede
            raise AdapterUnavailable("falha de rede: %s" % type(exc).__name__) from exc

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedResponse("resposta não é JSON válido") from exc

        return self._parse(decoded, request, started)

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    def _parse(
        self, decoded: Any, request: InferenceRequest, started: float
    ) -> InferenceResponse:
        if not isinstance(decoded, dict):
            raise MalformedResponse("resposta JSON não é um objeto")
        choices = decoded.get("choices")
        if not isinstance(choices, list) or not choices:
            raise MalformedResponse("resposta sem 'choices'")
        first = choices[0]
        if not isinstance(first, dict):
            raise MalformedResponse("'choices[0]' inválido")
        message = first.get("message") or {}
        if not isinstance(message, dict):
            raise MalformedResponse("'message' inválido")
        text = message.get("content")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise MalformedResponse("'content' não é texto")

        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise MalformedResponse("'tool_calls' inválido")
        if not text.strip() and not tool_calls:
            raise MalformedResponse("resposta vazia do modelo")

        usage = decoded.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}

        return InferenceResponse(
            model=str(decoded.get("model") or self.spec.id),
            text=text,
            provider=self.spec.provider,
            usage=usage,
            latency_ms=self._elapsed_ms(started),
            finish_reason=str(first.get("finish_reason") or "stop"),
            simulated=False,
            tool_calls=[call for call in tool_calls if isinstance(call, dict)],
            raw=None,
        )
