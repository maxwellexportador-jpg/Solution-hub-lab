"""Adaptador de integração do Solution Print Studio 3D.

O Studio 3D mantém seu núcleo de visualização/cena. O laboratório fornece
apenas texto assistivo (descrição de cena, sugestão de material, geração de
prompt). Nenhuma funcionalidade central é alterada por este módulo.
"""

from __future__ import annotations

from typing import Any, Dict

from .contracts import Studio3DRequest
from .lab_gateway import LabChatClient


class Studio3DClient:
    def __init__(self, base_url: str, token_env: str = "SOLUTION_PRINT_API_TOKEN", **kwargs: Any):
        self.lab = LabChatClient(base_url, token_env=token_env, **kwargs)

    def request_ai(self, request: Studio3DRequest) -> Dict[str, Any]:
        request.validate()
        result = self.lab.chat(
            messages=request.to_messages(),
            model_id=request.model_id,
            max_tokens=request.max_tokens,
        )
        result["contract_version"] = request.contract_version
        result["operation"] = request.operation
        result["scene_id"] = request.scene_id
        return result

    def health(self) -> Dict[str, Any]:
        return self.lab.http.get("/health")


def build_studio_request(
    operation: str, prompt: str, scene_id: str = None, model_id: str = None
) -> Studio3DRequest:
    request = Studio3DRequest(
        operation=operation, prompt=prompt, scene_id=scene_id, model_id=model_id
    )
    request.validate()
    return request
