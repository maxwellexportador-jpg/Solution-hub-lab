"""Registro de modelos com metadados verificáveis.

O registro é a fonte única de verdade sobre o que o laboratório conhece: nome,
origem, licença, capacidades, requisitos de hardware, custo e limitações. Ele
não presume que um modelo está pronto — ``status`` e ``endpoint_env`` deixam
claro o que ainda depende de configuração local.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import ModelNotFound, ValidationError
from .hardware import HardwareInfo, check_requirements, detect_hardware

SCHEMA_VERSION = 1
CATALOG_PATH = Path(__file__).with_name("catalog.json")

MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")

CAPABILITIES = frozenset(
    {
        "chat",
        "ptbr",
        "instruction",
        "reasoning",
        "tool_calling",
        "code",
        "vision",
        "embeddings",
        "summarization",
        "classification",
    }
)
PROVIDERS = frozenset({"local", "mock", "openai_compatible", "minimind"})
COSTS = frozenset({"free", "paid"})
STATUSES = frozenset({"available", "requires_setup", "planned", "unavailable"})
ADAPTERS = frozenset({"echo", "openai_compatible", "minimind"})
REQUIRED_FIELDS = ("id", "name", "origin", "license", "adapter", "provider")


@dataclass
class ModelSpec:
    """Especificação de um modelo conhecido pelo laboratório."""

    id: str
    name: str
    origin: str
    license: str
    adapter: str
    provider: str
    version: str = "1.0"
    family: str = ""
    parameters_m: Optional[float] = None
    quantization: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    input_formats: List[str] = field(default_factory=lambda: ["text"])
    output_formats: List[str] = field(default_factory=lambda: ["text"])
    min_ram_gb: float = 2.0
    recommended_ram_gb: Optional[float] = None
    min_vram_gb: Optional[float] = None
    cost: str = "free"
    status: str = "requires_setup"
    tool_calling: bool = False
    endpoint: Optional[str] = None
    endpoint_env: Optional[str] = None
    source_url: Optional[str] = None
    limitations: List[str] = field(default_factory=list)
    notes: str = ""
    tags: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Serialização
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelSpec":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValidationError(
                "Campos desconhecidos no modelo: %s" % ", ".join(sorted(unknown))
            )
        missing = [key for key in REQUIRED_FIELDS if not data.get(key)]
        if missing:
            raise ValidationError(
                "Modelo sem campos obrigatórios: %s" % ", ".join(missing)
            )
        payload = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        spec = cls(**payload)
        spec.capabilities = list(spec.capabilities)
        spec.limitations = list(spec.limitations)
        spec.tags = list(spec.tags)
        spec.input_formats = list(spec.input_formats)
        spec.output_formats = list(spec.output_formats)
        return spec

    # ------------------------------------------------------------------ #
    # Validação
    # ------------------------------------------------------------------ #
    def validate(self) -> List[str]:
        """Retorna a lista de problemas encontrados (vazia = válido)."""
        problems: List[str] = []
        if not MODEL_ID_RE.match(self.id or ""):
            problems.append(
                "id inválido (use minúsculas, números, ponto, hífen; 3-64 chars): %r" % self.id
            )
        for key in REQUIRED_FIELDS:
            if not getattr(self, key, None):
                problems.append("campo obrigatório vazio: %s" % key)
        if self.adapter not in ADAPTERS:
            problems.append("adapter desconhecido: %s" % self.adapter)
        if self.provider not in PROVIDERS:
            problems.append("provider desconhecido: %s" % self.provider)
        if self.cost not in COSTS:
            problems.append("cost inválido: %s" % self.cost)
        if self.status not in STATUSES:
            problems.append("status inválido: %s" % self.status)
        unknown_caps = set(self.capabilities) - CAPABILITIES
        if unknown_caps:
            problems.append("capacidades desconhecidas: %s" % ", ".join(sorted(unknown_caps)))
        if not self.capabilities:
            problems.append("nenhuma capacidade declarada")
        if self.min_ram_gb < 0:
            problems.append("min_ram_gb negativo")
        if self.recommended_ram_gb is not None and self.recommended_ram_gb < self.min_ram_gb:
            problems.append("recommended_ram_gb menor que min_ram_gb")
        if self.min_vram_gb is not None and self.min_vram_gb < 0:
            problems.append("min_vram_gb negativo")
        if self.tool_calling and "tool_calling" not in self.capabilities:
            problems.append("tool_calling=True exige a capacidade 'tool_calling'")
        if self.endpoint_env and not re.match(r"^[A-Z][A-Z0-9_]{2,63}$", self.endpoint_env):
            problems.append("endpoint_env deve ser um nome de variável de ambiente")
        if self.endpoint and not re.match(r"^https?://", self.endpoint):
            problems.append("endpoint deve ser http(s)://")
        if self.status in {"available", "requires_setup"} and not self.limitations:
            problems.append("modelo operacional deve declarar limitações conhecidas")
        if self.provider not in {"local", "mock"} and self.cost == "free" and self.status == "available":
            # Permitido, mas precisa estar documentado para não virar suposição.
            if not any("remot" in item.lower() or "local" in item.lower() for item in self.limitations):
                problems.append(
                    "modelo gratuito não-local deve documentar a dependência de rede/serviço"
                )
        return problems

    def assert_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ValidationError("Modelo %s inválido: %s" % (self.id, "; ".join(problems)))

    # ------------------------------------------------------------------ #
    # Derivados
    # ------------------------------------------------------------------ #
    def required_ram_gb(self) -> float:
        return float(self.recommended_ram_gb or self.min_ram_gb)

    def resolved_endpoint(self, environ: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Resolve o endpoint declarado ou via variável de ambiente."""
        if self.endpoint:
            return self.endpoint
        if not self.endpoint_env:
            return None
        env = environ if environ is not None else os.environ
        value = env.get(self.endpoint_env, "").strip()
        return value or None

    def requirements_met(self, info: Optional[HardwareInfo] = None) -> Tuple[bool, List[str]]:
        return check_requirements(self.min_ram_gb, self.min_vram_gb, info)

    def fits_recommended(self, info: HardwareInfo) -> bool:
        return info.ram_total_gb >= self.required_ram_gb()

    def public_view(self) -> Dict[str, Any]:
        """Visão sem detalhes internos, para expor via API."""
        data = self.to_dict()
        data.pop("endpoint", None)
        data.pop("endpoint_env", None)
        return data


@dataclass
class RegistryDocument:
    schema_version: int
    models: List[ModelSpec]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "models": [model.to_dict() for model in self.models],
        }


class ModelRegistry:
    """Coleção validada de modelos, com persistência em JSON."""

    def __init__(self, models: Iterable[ModelSpec]):
        self._models: Dict[str, ModelSpec] = {}
        for model in models:
            self.add(model)

    # ------------------------------------------------------------------ #
    # Construção
    # ------------------------------------------------------------------ #
    @classmethod
    def builtin(cls) -> "ModelRegistry":
        return cls.load(CATALOG_PATH)

    @classmethod
    def load(cls, path: os.PathLike) -> "ModelRegistry":
        location = Path(path)
        if not location.exists():
            raise ValidationError("Catálogo não encontrado: %s" % location)
        with location.open("r", encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValidationError("Catálogo com JSON inválido: %s" % exc) from exc
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValidationError(
                "schema_version não suportada: %r (esperado %d)" % (version, SCHEMA_VERSION)
            )
        models = [ModelSpec.from_dict(item) for item in data.get("models", [])]
        if not models:
            raise ValidationError("Catálogo vazio: nenhum modelo declarado")
        return cls(models)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelRegistry":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError("schema_version não suportada")
        return cls(ModelSpec.from_dict(item) for item in data.get("models", []))

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def add(self, model: ModelSpec) -> None:
        model.assert_valid()
        if model.id in self._models:
            raise ValidationError("Modelo duplicado: %s" % model.id)
        self._models[model.id] = model

    def update(self, model: ModelSpec) -> None:
        if model.id not in self._models:
            raise ModelNotFound(model.id)
        model.assert_valid()
        self._models[model.id] = model

    def remove(self, model_id: str) -> None:
        if model_id not in self._models:
            raise ModelNotFound(model_id)
        del self._models[model_id]

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise ModelNotFound("Modelo não encontrado: %s" % model_id) from exc

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #
    def all(self) -> List[ModelSpec]:
        return [self._models[key] for key in sorted(self._models)]

    def ids(self) -> List[str]:
        return sorted(self._models)

    def __len__(self) -> int:
        return len(self._models)

    def __contains__(self, model_id: object) -> bool:
        return model_id in self._models

    def filter(
        self,
        capabilities: Sequence[str] = (),
        max_cost: Optional[str] = "free",
        providers: Optional[Sequence[str]] = None,
        statuses: Optional[Sequence[str]] = None,
    ) -> List[ModelSpec]:
        result: List[ModelSpec] = []
        for model in self.all():
            if capabilities and not set(capabilities).issubset(model.capabilities):
                continue
            if max_cost == "free" and model.cost != "free":
                continue
            if providers and model.provider not in providers:
                continue
            if statuses and model.status not in statuses:
                continue
            result.append(model)
        return result

    def runnable(self, info: Optional[HardwareInfo] = None) -> List[ModelSpec]:
        """Modelos cujo status é operacional e cujo hardware mínimo é atendido."""
        info = info or detect_hardware()
        result = []
        for model in self.all():
            if model.status not in {"available", "requires_setup"}:
                continue
            ok, _ = model.requirements_met(info)
            if ok:
                result.append(model)
        return result

    def report(self, info: Optional[HardwareInfo] = None) -> List[Dict[str, Any]]:
        """Tabela de compatibilidade modelo x hardware real."""
        info = info or detect_hardware()
        rows = []
        for model in self.all():
            ok, reasons = model.requirements_met(info)
            rows.append(
                {
                    "id": model.id,
                    "name": model.name,
                    "provider": model.provider,
                    "status": model.status,
                    "cost": model.cost,
                    "min_ram_gb": model.min_ram_gb,
                    "fits": ok,
                    "reasons": reasons,
                    "endpoint_configured": bool(model.resolved_endpoint()),
                }
            )
        return rows

    # ------------------------------------------------------------------ #
    # Persistência
    # ------------------------------------------------------------------ #
    def save(self, path: os.PathLike) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = RegistryDocument(SCHEMA_VERSION, self.all()).to_dict()
        with destination.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return destination
