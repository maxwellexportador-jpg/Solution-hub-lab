"""Fábrica de adaptadores da camada Solution Print."""

from __future__ import annotations

from typing import Dict, Optional, Type

from ..errors import ValidationError
from ..registry import ModelSpec
from .base import BaseAdapter, InferenceRequest, InferenceResponse, Message
from .echo import EchoAdapter
from .minimind import MiniMindAdapter
from .openai_compat import OpenAICompatibleAdapter, validate_endpoint

ADAPTER_CLASSES: Dict[str, Type[BaseAdapter]] = {
    "echo": EchoAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
    "minimind": MiniMindAdapter,
}


def create_adapter(
    spec: ModelSpec,
    environ: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
) -> BaseAdapter:
    """Instancia o adaptador declarado pelo modelo."""
    try:
        adapter_class = ADAPTER_CLASSES[spec.adapter]
    except KeyError as exc:
        raise ValidationError("adaptador não implementado: %s" % spec.adapter) from exc
    if adapter_class is OpenAICompatibleAdapter:
        return OpenAICompatibleAdapter(spec, environ=environ, timeout=timeout)
    return adapter_class(spec, environ=environ)


__all__ = [
    "ADAPTER_CLASSES",
    "BaseAdapter",
    "EchoAdapter",
    "InferenceRequest",
    "InferenceResponse",
    "Message",
    "MiniMindAdapter",
    "OpenAICompatibleAdapter",
    "create_adapter",
    "validate_endpoint",
]
