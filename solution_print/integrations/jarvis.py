"""Integração com o JARVIS Solution Print.

O JARVIS continua dono da memória, das ferramentas e do supervisor de
permissões. O laboratório só oferece: seleção de modelo, inferência e
**propostas** de ferramentas que o supervisor do JARVIS aprova ou recusa.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..adapters import Message
from ..errors import PolicyViolation
from ..router import ModelRouter, RoutingRequest
from ..safety import ToolCallGateway, ToolDecision, ToolPermission, ToolProposal
from .contracts import TenantContext, ToolProposalEnvelope
from .http_client import JsonHttpClient

SUPERVISOR = "jarvis"
PROPOSALS_PATH = "/api/supervisor/tool-proposals"


class JarvisBridge:
    """Ponte usada pelo JARVIS; nunca executa nada por conta própria."""

    def __init__(
        self,
        router: ModelRouter,
        gateway: Optional[ToolCallGateway] = None,
    ):
        self.router = router
        self.gateway = gateway or ToolCallGateway()
        self.last_selection: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ #
    # Seleção e inferência
    # ------------------------------------------------------------------ #
    def select_model(
        self, task: str = "chat", required_capabilities: Sequence[str] = ()
    ) -> Dict[str, Any]:
        decision = self.router.route(
            RoutingRequest(task=task, required_capabilities=tuple(required_capabilities))
        )
        self.last_selection = decision.to_dict()
        return self.last_selection

    def infer(
        self,
        messages: Sequence[Dict[str, str]],
        task: str = "chat",
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self.router.infer(
            request=RoutingRequest(task=task, preferred_model=model_id),
            messages=[Message(item["role"], item["content"]) for item in messages],
        )
        payload = result.to_dict()
        payload["supervisor"] = SUPERVISOR
        payload["memory_owner"] = "jarvis"
        return payload

    # ------------------------------------------------------------------ #
    # Ferramentas: proposta, nunca execução
    # ------------------------------------------------------------------ #
    def evaluate_tool_calls(
        self,
        raw_tool_calls: Iterable[Dict[str, Any]],
        tenant: TenantContext,
        request_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        proposals: List[ToolProposal] = self.gateway.parse(list(raw_tool_calls))
        decisions: List[ToolDecision] = self.gateway.evaluate(proposals)
        request_id = request_id or uuid.uuid4().hex

        envelopes: List[Dict[str, Any]] = []
        for decision in decisions:
            if decision.status == "denied":
                envelopes.append(
                    {
                        "request_id": request_id,
                        "status": "denied",
                        "supervisor": SUPERVISOR,
                        "tool": decision.proposal.name,
                        "reasons": list(decision.reasons),
                    }
                )
                continue
            envelope = ToolProposalEnvelope(
                request_id=request_id,
                tenant=tenant,
                tool=decision.proposal.name,
                arguments=decision.proposal.arguments,
                status="pending_approval",
                supervisor=SUPERVISOR,
            )
            envelope.validate()
            envelopes.append(envelope.to_dict())
        return envelopes

    def register_tool_permission(self, permission: ToolPermission) -> None:
        """Permissões vêm sempre do supervisor; o laboratório só as aplica."""
        self.gateway.grant(permission)

    def execute_tool(self, *args: Any, **kwargs: Any) -> None:
        raise PolicyViolation(
            "o laboratório não executa ferramentas; envie a proposta ao supervisor do JARVIS"
        )


class JarvisSupervisorClient:
    """Envia propostas ao supervisor do JARVIS para decisão."""

    def __init__(
        self,
        base_url: str,
        token_env: str = "JARVIS_SUPERVISOR_TOKEN",
        path: str = PROPOSALS_PATH,
        **kwargs: Any,
    ):
        self.http = JsonHttpClient(base_url, token_env=token_env, **kwargs)
        self.path = path

    def submit(self, envelopes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        for envelope in envelopes:
            if envelope.get("status") not in {"pending_approval", "denied"}:
                raise PolicyViolation(
                    "somente propostas pendentes ou negadas podem ser enviadas ao supervisor"
                )
        return self.http.post(self.path, {"contract_version": "1.0", "proposals": list(envelopes)})
