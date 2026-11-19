"""Apoio de testes: servidor HTTP falso em loopback e fixtures de modelos."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from solution_print.adapters import BaseAdapter, InferenceResponse
from solution_print.errors import AdapterUnavailable
from solution_print.registry import ModelRegistry, ModelSpec

Route = Callable[[str, Dict[str, Any]], Tuple[int, Any]]


class MockServer:
    """Servidor HTTP local com rotas programáveis e registro de requisições."""

    def __init__(self, routes: Dict[str, Route], default: Optional[Route] = None):
        self.routes = routes
        self.default = default
        self.requests: List[Dict[str, Any]] = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MockServer/1.0"

            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except json.JSONDecodeError:
                    body = {"_raw": raw.decode("utf-8", "replace")}
                path = self.path.split("?")[0]
                mock.requests.append(
                    {
                        "method": method,
                        "path": path,
                        "body": body,
                        "authorization": self.headers.get("Authorization"),
                    }
                )
                route = mock.routes.get(path) or mock.default
                if route is None:
                    status, payload = 404, {"error": "not found"}
                else:
                    status, payload = route(method, body)
                encoded = (
                    payload
                    if isinstance(payload, bytes)
                    else json.dumps(payload).encode("utf-8")
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:  # noqa: N802
                self._handle("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._handle("POST")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def __enter__(self) -> "MockServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=5)


def chat_route(text: str = "resposta de teste", model: str = "mock-model") -> Route:
    def route(method: str, body: Dict[str, Any]) -> Tuple[int, Any]:
        return 200, {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

    return route


def make_spec(
    model_id: str = "test-local",
    provider: str = "openai_compatible",
    adapter: str = "openai_compatible",
    capabilities: Optional[List[str]] = None,
    endpoint: Optional[str] = None,
    min_ram_gb: float = 0.1,
    status: str = "available",
    cost: str = "free",
    endpoint_env: Optional[str] = None,
) -> ModelSpec:
    limitations = ["depende de servidor local configurado"]
    return ModelSpec(
        id=model_id,
        name="Modelo de teste %s" % model_id,
        origin="teste local",
        license="Apache-2.0",
        adapter=adapter,
        provider=provider,
        capabilities=capabilities or ["chat"],
        min_ram_gb=min_ram_gb,
        status=status,
        cost=cost,
        endpoint=endpoint,
        endpoint_env=endpoint_env,
        limitations=limitations,
    )


def registry_with(*specs: ModelSpec) -> ModelRegistry:
    return ModelRegistry(specs)


class FailingAdapter(BaseAdapter):
    name = "failing"

    def __init__(self, spec: ModelSpec, error: Optional[Exception] = None):
        super().__init__(spec, {})
        self.error = error or AdapterUnavailable("falha programada")
        self.calls = 0

    def available(self) -> Tuple[bool, str]:
        return True, "falha programada"

    def infer(self, request: Any) -> InferenceResponse:
        self.calls += 1
        raise self.error


def adapter_factory(mapping: Dict[str, BaseAdapter]) -> Callable[..., BaseAdapter]:
    def factory(spec: ModelSpec, environ: Optional[Dict[str, str]] = None, **_: Any) -> BaseAdapter:
        return mapping[spec.id]

    return factory
