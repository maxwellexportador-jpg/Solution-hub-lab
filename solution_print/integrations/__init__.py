"""Integrações do laboratório com o ecossistema Solution Print."""

from __future__ import annotations

from .ai_core import AiCoreClient, LabProviderService, build_manifest
from .android import AndroidChatClient, build_mobile_request
from .contracts import (
    CONTRACT_VERSION,
    PROVIDER_ID,
    CrmAiTask,
    InferenceEnvelopeRequest,
    InferenceEnvelopeResponse,
    MobileChatRequest,
    ModelDescriptor,
    ProviderManifest,
    Studio3DRequest,
    TenantContext,
    ToolProposalEnvelope,
    assert_no_pii,
)
from .crm import CrmAiClient, build_crm_task
from .jarvis import JarvisBridge, JarvisSupervisorClient
from .lab_gateway import LabChatClient
from .studio3d import Studio3DClient, build_studio_request

__all__ = [
    "AiCoreClient",
    "AndroidChatClient",
    "CONTRACT_VERSION",
    "CrmAiClient",
    "CrmAiTask",
    "InferenceEnvelopeRequest",
    "InferenceEnvelopeResponse",
    "JarvisBridge",
    "JarvisSupervisorClient",
    "LabChatClient",
    "LabProviderService",
    "MobileChatRequest",
    "ModelDescriptor",
    "PROVIDER_ID",
    "ProviderManifest",
    "Studio3DClient",
    "Studio3DRequest",
    "TenantContext",
    "ToolProposalEnvelope",
    "assert_no_pii",
    "build_crm_task",
    "build_manifest",
    "build_mobile_request",
    "build_studio_request",
]
