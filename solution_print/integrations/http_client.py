"""Cliente HTTP mínimo (stdlib) para os contratos de integração.

Sem SDK, sem retentativa automática, sem credenciais em código: o token vem
sempre de variável de ambiente e nunca é incluído em mensagens de erro.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..errors import IntegrationError

DEFAULT_TIMEOUT = 20.0


def _is_local_host(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    if host in {"localhost", "127.0.0.1", "::1", "host.docker.internal"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def validate_base_url(base_url: str) -> str:
    """HTTPS obrigatório fora da máquina local; sem credenciais na URL."""
    if not base_url:
        raise IntegrationError("base_url não configurada")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise IntegrationError("base_url deve usar http(s)")
    if parsed.username or parsed.password:
        raise IntegrationError("base_url não pode conter credenciais")
    if not parsed.hostname:
        raise IntegrationError("base_url sem host")
    if not _is_local_host(parsed.hostname) and parsed.scheme != "https":
        raise IntegrationError("integração remota exige HTTPS")
    return base_url.rstrip("/")


@dataclass
class HttpResponse:
    status: int
    body: Dict[str, Any]
    latency_ms: float


class JsonHttpClient:
    """POST/GET JSON com timeout, tratamento de erro e log de metadados."""

    def __init__(
        self,
        base_url: str,
        token_env: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        environ: Optional[Dict[str, str]] = None,
    ):
        self.base_url = validate_base_url(base_url)
        self.token_env = token_env
        self.timeout = timeout
        self._env = environ if environ is not None else os.environ
        self.last_response: Optional[HttpResponse] = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = self._env.get(self.token_env or "", "").strip() if self.token_env else ""
        if token:
            headers["Authorization"] = "Bearer %s" % token
        return headers

    def _request(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        import time

        url = self.base_url + (path if path.startswith("/") else "/" + path)
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read(300).decode("utf-8", "replace")
            except Exception:  # pragma: no cover - defensivo
                body = ""
            token = self._env.get(self.token_env or "", "") if self.token_env else ""
            if token:
                body = body.replace(token, "***")
            raise IntegrationError(
                "integração respondeu HTTP %d em %s: %s" % (exc.code, path, body[:160])
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise IntegrationError("timeout ao chamar %s" % path) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise IntegrationError("timeout ao chamar %s" % path) from exc
            raise IntegrationError(
                "integração inacessível (%s): %s" % (path, type(reason).__name__)
            ) from exc
        except OSError as exc:  # pragma: no cover - rede
            raise IntegrationError("falha de rede em %s: %s" % (path, type(exc).__name__)) from exc

        latency_ms = (time.perf_counter() - started) * 1000
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrationError("resposta de %s não é JSON" % path) from exc
        if not isinstance(decoded, dict):
            raise IntegrationError("resposta de %s não é um objeto JSON" % path)
        self.last_response = HttpResponse(status=status, body=decoded, latency_ms=latency_ms)
        return decoded

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", path, payload)

    def get(self, path: str, query: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if query:
            path = path + "?" + urllib.parse.urlencode(query)
        return self._request("GET", path)
