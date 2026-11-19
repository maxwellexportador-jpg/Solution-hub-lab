"""API HTTP do laboratório (stdlib, compatível com OpenAI quando possível).

Endpoints:

* ``GET /health``            — estado, hardware e contagem de modelos
* ``GET /v1/models``         — modelos conhecidos e capacidades
* ``GET /v1/lab/route``      — decisão de roteamento para uma tarefa
* ``POST /v1/chat/completions`` — inferência padronizada

Sem dependência de FastAPI/uvicorn. Fora do loopback, exige token de API.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import CONTRACT_VERSION, __version__
from .adapters import Message
from .errors import (
    AdapterTimeout,
    AllModelsFailed,
    ConfigurationError,
    LabError,
    ModelNotFound,
    NoModelAvailable,
    PolicyViolation,
    ValidationError,
)
from .hardware import classify_profile, detect_hardware, summarise
from .router import ModelRouter, RoutingPolicy, RoutingRequest
from .safety import MAX_INPUT_CHARS, find_secrets, sanitize_output, validate_input

MAX_BODY_BYTES = 128 * 1024
TOKEN_ENV = "SOLUTION_PRINT_API_TOKEN"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    token: Optional[str] = None
    token_env: str = TOKEN_ENV
    require_auth: bool = True

    @property
    def is_loopback(self) -> bool:
        return self.host in LOOPBACK_HOSTS


ERROR_STATUS = {
    ValidationError: 400,
    ModelNotFound: 404,
    PolicyViolation: 403,
    NoModelAvailable: 503,
    AdapterTimeout: 504,
    AllModelsFailed: 502,
    ConfigurationError: 500,
}


class LabServer:
    """Servidor HTTP multithread do laboratório."""

    def __init__(
        self,
        router: Optional[ModelRouter] = None,
        config: Optional[ServerConfig] = None,
    ):
        self.router = router or ModelRouter()
        self.config = config or ServerConfig()
        if self.config.token is None:
            self.config.token = os.environ.get(self.config.token_env, "").strip() or None
        if self.config.require_auth and not self.config.token and not self.config.is_loopback:
            raise ConfigurationError(
                "servidor fora do loopback exige %s configurado" % self.config.token_env
            )
        self.hardware = self.router.hardware
        self.started_at = time.time()
        self.access_log: List[Dict[str, Any]] = []
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread = None

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def build(self) -> ThreadingHTTPServer:
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SolutionPrintLab/%s" % __version__
            sys_version = ""

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                server.access_log.append(
                    {
                        "t": time.time(),
                        "client": self.client_address[0] if self.client_address else "",
                        "message": fmt % args,
                    }
                )
                if len(server.access_log) > 500:
                    del server.access_log[:250]

            # ---------------------------------------------------------- #
            def _send(self, status: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status: int, code: str, message: str) -> None:
                self._send(status, {"error": {"code": code, "message": message}})

            def _authorised(self) -> bool:
                if not server.config.token:
                    return server.config.is_loopback
                header = self.headers.get("Authorization", "")
                if not header.startswith("Bearer "):
                    return False
                return header[7:].strip() == server.config.token

            def _read_json(self) -> Optional[Dict[str, Any]]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._error(400, "invalid_content_length", "Content-Length inválido")
                    return None
                if length <= 0:
                    self._error(400, "empty_body", "corpo JSON obrigatório")
                    return None
                if length > MAX_BODY_BYTES:
                    self._error(413, "payload_too_large", "corpo excede o limite permitido")
                    return None
                raw = self.rfile.read(length)
                try:
                    decoded = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._error(400, "invalid_json", "JSON inválido")
                    return None
                if not isinstance(decoded, dict):
                    self._error(400, "invalid_payload", "payload deve ser um objeto")
                    return None
                return decoded

            # ---------------------------------------------------------- #
            def do_GET(self) -> None:  # noqa: N802
                route = urlparse(self.path)
                if not self._authorised():
                    self._error(401, "unauthorized", "token de API ausente ou inválido")
                    return
                if route.path == "/health":
                    self._send(200, server.health())
                    return
                if route.path == "/v1/models":
                    self._send(200, server.models())
                    return
                if route.path == "/v1/lab/route":
                    query = parse_qs(route.query)
                    task = (query.get("task") or ["chat"])[0]
                    model_id = (query.get("model") or [None])[0]
                    try:
                        decision = server.router.route(
                            RoutingRequest(task=task, preferred_model=model_id)
                        )
                    except LabError as exc:
                        server._map_error(self, exc)
                        return
                    self._send(200, decision.to_dict())
                    return
                self._error(404, "not_found", "rota não encontrada")

            def do_POST(self) -> None:  # noqa: N802
                route = urlparse(self.path)
                if not self._authorised():
                    self._error(401, "unauthorized", "token de API ausente ou inválido")
                    return
                if route.path != "/v1/chat/completions":
                    self._error(404, "not_found", "rota não encontrada")
                    return
                payload = self._read_json()
                if payload is None:
                    return
                try:
                    response = server.chat_completions(payload)
                except LabError as exc:
                    server._map_error(self, exc)
                    return
                self._send(200, response)

            def do_OPTIONS(self) -> None:  # noqa: N802
                # CORS não é habilitado: clientes devem ser same-origin ou server-side.
                self.send_response(204)
                self.send_header("Allow", "GET, POST, OPTIONS")
                self.end_headers()

        self._httpd = ThreadingHTTPServer((self.config.host, self.config.port), Handler)
        self._httpd.daemon_threads = True
        return self._httpd

    def start(self) -> int:
        httpd = self._httpd or self.build()
        import threading

        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return httpd.server_address[1]

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def serve_forever(self) -> None:  # pragma: no cover - bloqueante
        httpd = self._httpd or self.build()
        httpd.serve_forever()

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    def health(self) -> Dict[str, Any]:
        report = self.router.registry.report(self.hardware)
        available = sum(
            1 for row in report if row["fits"] and row["status"] in {"available", "requires_setup"}
        )
        return {
            "status": "ok",
            "service": "solution-print-ai-lab",
            "version": __version__,
            "contract_version": CONTRACT_VERSION,
            "uptime_s": round(time.time() - self.started_at, 2),
            "auth_required": bool(self.config.token) or not self.config.is_loopback,
            "hardware": {
                "summary": summarise(self.hardware),
                "profile": classify_profile(self.hardware).key,
                "ram_total_gb": self.hardware.ram_total_gb,
                "cpu_cores": self.hardware.cpu_cores,
                "gpu": self.hardware.gpu_name,
            },
            "models": {"known": len(self.router.registry), "in_hardware_budget": available},
            "upstream": {"project": "jingyaogong/minimind", "license": "Apache-2.0"},
        }

    def models(self) -> Dict[str, Any]:
        data = []
        for spec in self.router.registry.all():
            available, reason = self.router.availability(spec)
            data.append(
                {
                    "id": spec.id,
                    "object": "model",
                    "owned_by": spec.origin,
                    "provider": spec.provider,
                    "capabilities": list(spec.capabilities),
                    "cost": spec.cost,
                    "status": spec.status,
                    "available": available,
                    "availability_note": reason[:160],
                    "simulated": spec.provider == "mock",
                    "license": spec.license,
                }
            )
        return {"object": "list", "data": data}

    def chat_completions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValidationError("'messages' é obrigatório e deve ser uma lista")
        if len(messages) > 60:
            raise ValidationError("histórico excessivo")
        parsed: List[Message] = []
        total = 0
        for item in messages:
            if not isinstance(item, dict):
                raise ValidationError("cada mensagem deve ser um objeto")
            role = item.get("role")
            content = item.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValidationError("role inválido: %r" % (role,))
            text = validate_input(content, max_chars=MAX_INPUT_CHARS)
            total += len(text)
            if total > MAX_INPUT_CHARS * 2:
                raise ValidationError("conversa excede o limite total")
            parsed.append(Message(role=role, content=text))

        temperature = float(payload.get("temperature", 0.2))
        max_tokens = int(payload.get("max_tokens", 512))
        model_id = payload.get("model")
        if model_id is not None and not isinstance(model_id, str):
            raise ValidationError("'model' deve ser texto")

        secrets = find_secrets("\n".join(item.content for item in parsed))
        if secrets:
            raise PolicyViolation(
                "entrada contém possível segredo (%s); remova antes de enviar" % ", ".join(secrets)
            )

        result = self.router.infer(
            request=RoutingRequest(
                task=str(payload.get("task", "chat")),
                preferred_model=model_id or None,
                max_cost="free",
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            messages=parsed,
        )
        text, flags = sanitize_output(result.response.text)
        return {
            "id": "chatcmpl-%s" % result.trace_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": result.response.model,
            "simulated": result.response.simulated,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": result.response.finish_reason,
                }
            ],
            "usage": result.response.usage,
            "solution_print": {
                "trace_id": result.trace_id,
                "decision": result.decision.to_dict(),
                "attempts": result.attempts,
                "output_flags": flags,
            },
        }

    # ------------------------------------------------------------------ #
    # Erros
    # ------------------------------------------------------------------ #
    @staticmethod
    def _map_error(handler: BaseHTTPRequestHandler, exc: LabError) -> None:
        status = 400
        for error_type, code in ERROR_STATUS.items():
            if isinstance(exc, error_type):
                status = code
                break
        body = {
            "error": {
                "code": type(exc).__name__,
                "message": str(exc)[:500],
            }
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(encoded)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(encoded)


def serve(
    host: str = "127.0.0.1",
    port: int = 8787,
    router: Optional[ModelRouter] = None,
    token: Optional[str] = None,
) -> None:  # pragma: no cover - bloqueante
    server = LabServer(router=router, config=ServerConfig(host=host, port=port, token=token))
    print("Solution Print AI Lab em http://%s:%d" % (host, port))
    server.serve_forever()
