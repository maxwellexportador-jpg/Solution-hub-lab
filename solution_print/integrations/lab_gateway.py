"""Cliente do endpoint compatível com OpenAI exposto pelo laboratório.

Usado pelos adaptadores de Android e Studio 3D. Mantém o formato padrão para
que qualquer cliente existente consiga falar com o laboratório sem SDK novo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..errors import IntegrationError
from .http_client import JsonHttpClient

CHAT_PATH = "/v1/chat/completions"


class LabChatClient:
    def __init__(
        self,
        base_url: str,
        token_env: str = "SOLUTION_PRINT_API_TOKEN",
        path: str = CHAT_PATH,
        **kwargs: Any,
    ):
        self.http = JsonHttpClient(base_url, token_env=token_env, **kwargs)
        self.path = path

    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if model_id:
            payload["model"] = model_id
        response = self.http.post(self.path, payload)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise IntegrationError("resposta do laboratório sem 'choices'")
        message = (choices[0] or {}).get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            raise IntegrationError("resposta do laboratório sem conteúdo textual")
        return {
            "text": text,
            "model": response.get("model"),
            "simulated": bool(response.get("simulated")),
            "usage": response.get("usage") or {},
        }
