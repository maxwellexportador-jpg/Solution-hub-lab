"""Adaptador de integração do app Minha IA Android (Expo/React Native).

O app fala com o próprio servidor (`server/index.js`) e este laboratório é um
provedor opcional. Nada no app é alterado por este módulo: ele apenas prepara
o contrato e o cliente que o app poderá usar.
"""

from __future__ import annotations

from typing import Any, Dict

from .contracts import MobileChatRequest
from .lab_gateway import LabChatClient


class AndroidChatClient:
    """Cliente que o servidor do app pode usar para consultar o laboratório."""

    def __init__(self, base_url: str, token_env: str = "SOLUTION_PRINT_API_TOKEN", **kwargs: Any):
        self.lab = LabChatClient(base_url, token_env=token_env, **kwargs)

    def chat(self, request: MobileChatRequest) -> Dict[str, Any]:
        request.validate()
        result = self.lab.chat(
            messages=request.messages,
            model_id=request.model_id,
            max_tokens=request.max_tokens,
        )
        result["contract_version"] = request.contract_version
        result["locale"] = request.locale
        result["app_version"] = request.app_version
        return result

    def health(self) -> Dict[str, Any]:
        return self.lab.http.get("/health")


def build_mobile_request(
    messages: list, locale: str = "pt-BR", app_version: str = "", model_id: str = None
) -> MobileChatRequest:
    request = MobileChatRequest(
        messages=messages,
        locale=locale,
        app_version=app_version or "",
        model_id=model_id,
    )
    request.validate()
    return request
