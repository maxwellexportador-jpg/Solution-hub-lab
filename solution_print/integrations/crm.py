"""Integração com o CRM Solution Hub AI (somente por API).

Proibições explícitas desta camada:

* não abre conexão com Supabase, Postgres ou Cloudflare do CRM;
* não lê nem escreve dados de clientes;
* não copia dados reais para datasets do laboratório;
* recusa qualquer payload com PII (nome de campo ou padrão detectável).

A soberania sobre dados e regras de negócio permanece com o CRM.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..errors import IntegrationError
from .contracts import CrmAiTask, assert_no_pii
from .http_client import JsonHttpClient

TASKS_PATH = "/api/ai/tasks"


class CrmAiClient:
    """Cliente do CRM para tarefas autorizadas de IA."""

    def __init__(
        self,
        base_url: str,
        token_env: str = "CRM_AI_INTEGRATION_TOKEN",
        path: str = TASKS_PATH,
        **kwargs: Any,
    ):
        self.http = JsonHttpClient(base_url, token_env=token_env, **kwargs)
        self.path = path

    def submit_task(self, task: CrmAiTask) -> Dict[str, Any]:
        task.validate()
        response = self.http.post(self.path, task.to_dict())
        if not isinstance(response.get("result"), (str, dict)) and "error" not in response:
            raise IntegrationError("resposta do CRM sem campo 'result'")
        return response

    # ------------------------------------------------------------------ #
    # Atalhos por tipo de tarefa
    # ------------------------------------------------------------------ #
    def classify(self, text: str, labels: Optional[list] = None) -> Dict[str, Any]:
        assert_no_pii(text, "text")
        payload: Dict[str, Any] = {"text": text}
        if labels:
            payload["labels"] = [str(label) for label in labels]
        return self.submit_task(CrmAiTask(task_type="classify", payload=payload, max_tokens=64))

    def summarize(self, text: str, max_tokens: int = 256) -> Dict[str, Any]:
        assert_no_pii(text, "text")
        return self.submit_task(
            CrmAiTask(task_type="summarize", payload={"text": text}, max_tokens=max_tokens)
        )

    def draft_reply(self, context: str, tone: str = "cordial") -> Dict[str, Any]:
        assert_no_pii(context, "context")
        return self.submit_task(
            CrmAiTask(
                task_type="draft_reply",
                payload={"context": context, "tone": tone},
                max_tokens=320,
            )
        )


def build_crm_task(task_type: str, payload: Dict[str, Any]) -> CrmAiTask:
    """Constrói e valida uma tarefa antes de qualquer chamada de rede."""
    task = CrmAiTask(task_type=task_type, payload=payload)
    task.validate()
    return task
