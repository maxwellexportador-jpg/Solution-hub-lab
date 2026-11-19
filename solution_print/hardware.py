"""Detecção de hardware e perfis de recursos.

Nada aqui assume GPU ou muita memória: o perfil é calculado a partir do que a
máquina realmente oferece. Em contêineres, o limite de memória do cgroup é
respeitado, porque ``/proc/meminfo`` do host não representa o que o processo
pode alocar.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

GIB = 1024 ** 3

MEMINFO_PATH = "/proc/meminfo"
CGROUP_LIMITS = (
    "/sys/fs/cgroup/memory.max",
    "/sys/fs/cgroup/memory/memory.limit_in_bytes",
)
CGROUP_USAGE = (
    "/sys/fs/cgroup/memory.current",
    "/sys/fs/cgroup/memory/memory.usage_in_bytes",
)


@dataclass(frozen=True)
class HardwareProfile:
    """Perfil de hardware usado para decidir quais modelos são viáveis."""

    key: str
    label: str
    ram_gb: float
    cpu_cores: int
    vram_gb: Optional[float]
    accelerator: str
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HardwareInfo:
    """Fotografia real (detectada) do ambiente de execução."""

    ram_total_gb: float
    ram_available_gb: float
    cpu_cores: int
    cpu_model: str = ""
    gpu_name: Optional[str] = None
    vram_gb: Optional[float] = None
    disk_free_gb: float = 0.0
    platform: str = ""
    python_version: str = ""
    cgroup_limited: bool = False
    notes: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def has_gpu(self) -> bool:
        return bool(self.gpu_name) and (self.vram_gb or 0) > 0


#: Perfis exigidos pelo plano: CPU/pouca memória, 8, 16, 32 GB e GPUs.
PROFILES: Tuple[HardwareProfile, ...] = (
    HardwareProfile(
        key="cpu-low",
        label="CPU / pouca memória",
        ram_gb=4.0,
        cpu_cores=2,
        vram_gb=None,
        accelerator="cpu",
        description="Inferência apenas de modelos minúsculos quantizados ou adaptadores simulados.",
    ),
    HardwareProfile(
        key="cpu-8gb",
        label="CPU 8 GB",
        ram_gb=8.0,
        cpu_cores=4,
        vram_gb=None,
        accelerator="cpu",
        description="Perfil do computador principal Solution Print. Modelos <= 1.5B quantizados.",
    ),
    HardwareProfile(
        key="cpu-16gb",
        label="CPU 16 GB",
        ram_gb=16.0,
        cpu_cores=8,
        vram_gb=None,
        accelerator="cpu",
        description="Modelos até ~3B quantizados em CPU; fine-tuning pequeno inviável.",
    ),
    HardwareProfile(
        key="cpu-32gb",
        label="CPU 32 GB",
        ram_gb=32.0,
        cpu_cores=16,
        vram_gb=None,
        accelerator="cpu",
        description="Modelos até ~7B quantizados em CPU com latência alta.",
    ),
    HardwareProfile(
        key="gpu-8gb",
        label="GPU 8 GB VRAM",
        ram_gb=16.0,
        cpu_cores=8,
        vram_gb=8.0,
        accelerator="cuda",
        description="Modelos até ~3B em fp16 ou 7B quantizados; LoRA pequeno viável.",
    ),
    HardwareProfile(
        key="gpu-24gb",
        label="GPU 24 GB VRAM",
        ram_gb=32.0,
        cpu_cores=16,
        vram_gb=24.0,
        accelerator="cuda",
        description="Perfil de referência do README upstream (RTX 3090) para SFT curto.",
    ),
)

PROFILE_BY_KEY: Dict[str, HardwareProfile] = {p.key: p for p in PROFILES}


def _read_meminfo() -> Dict[str, str]:
    data: Dict[str, str] = {}
    try:
        with open(MEMINFO_PATH, "r", encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                data[key.strip()] = value.strip()
    except OSError:
        return {}
    return data


def _to_gib(raw: str) -> Optional[float]:
    """Converte um valor de /proc/meminfo (ex.: '16384000 kB') em GiB."""
    parts = raw.split()
    if not parts:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    unit = parts[1].lower() if len(parts) > 1 else "kb"
    if unit == "kb":
        return value * 1024 / GIB
    if unit == "mb":
        return value * 1024 * 1024 / GIB
    if unit == "gb":
        return value
    return None


def _read_first(paths) -> Optional[str]:
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            continue
    return None


def _cgroup_limits() -> Tuple[Optional[float], Optional[float]]:
    limit_raw = _read_first(CGROUP_LIMITS)
    usage_raw = _read_first(CGROUP_USAGE)
    limit_gb = usage_gb = None
    if limit_raw and limit_raw != "max":
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = None
        # Valores gigantes significam "sem limite" no cgroup v1.
        if limit is not None and 0 < limit < (1 << 60):
            limit_gb = limit / GIB
    if usage_raw:
        try:
            usage_gb = int(usage_raw) / GIB
        except ValueError:
            usage_gb = None
    return limit_gb, usage_gb


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.partition(":")[2].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _detect_gpu() -> Tuple[Optional[str], Optional[float], list]:
    notes: list = []
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        notes.append("nvidia-smi ausente: nenhuma GPU CUDA detectada por esta via.")
        return None, None, notes
    try:
        out = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - ambiente
        notes.append("Falha ao executar nvidia-smi: %s" % type(exc).__name__)
        return None, None, notes
    if out.returncode != 0 or not out.stdout.strip():
        notes.append("nvidia-smi retornou código %s sem dados de GPU." % out.returncode)
        return None, None, notes
    first = out.stdout.strip().splitlines()[0]
    name, _, memory = first.partition(",")
    try:
        vram_gb = round(float(memory.strip()) / 1024, 2)
    except ValueError:
        vram_gb = None
    return name.strip(), vram_gb, notes


def detect_hardware(path: str = ".") -> HardwareInfo:
    """Detecta CPU, memória (respeitando cgroup) e GPU."""
    meminfo = _read_meminfo()
    total = _to_gib(meminfo.get("MemTotal", "")) or 0.0
    available = _to_gib(meminfo.get("MemAvailable", "")) or total

    limit_gb, usage_gb = _cgroup_limits()
    cgroup_limited = False
    if limit_gb is not None:
        cgroup_limited = limit_gb < total
        total = min(total, limit_gb)
        if usage_gb is not None:
            available = min(available, max(limit_gb - usage_gb, 0.0))

    try:
        cores = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        cores = os.cpu_count() or 1

    gpu_name, vram_gb, notes = _detect_gpu()

    try:
        disk_free = round(shutil.disk_usage(path).free / GIB, 2)
    except OSError:
        disk_free = 0.0

    if total <= 0:
        notes.append("Memória total não pôde ser lida; assumindo 0 GB.")
    if available < total * 0.15:
        notes.append("Memória disponível abaixo de 15%% do total: evitar modelos grandes.")

    return HardwareInfo(
        ram_total_gb=round(total, 2),
        ram_available_gb=round(available, 2),
        cpu_cores=cores,
        cpu_model=_cpu_model(),
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        disk_free_gb=disk_free,
        platform=platform.platform(),
        python_version=sys.version.split()[0],
        cgroup_limited=cgroup_limited,
        notes=notes,
    )


def classify_profile(info: HardwareInfo) -> HardwareProfile:
    """Escolhe o menor perfil que cobre a memória real detectada."""
    if info.has_gpu:
        if (info.vram_gb or 0) >= 20:
            return PROFILE_BY_KEY["gpu-24gb"]
        return PROFILE_BY_KEY["gpu-8gb"]
    for profile in PROFILES:
        if profile.accelerator != "cpu":
            continue
        if info.ram_total_gb <= profile.ram_gb:
            return profile
    return PROFILE_BY_KEY["cpu-32gb"]


def check_requirements(
    min_ram_gb: float,
    min_vram_gb: Optional[float] = None,
    info: Optional[HardwareInfo] = None,
) -> Tuple[bool, list]:
    """Verifica se o modelo cabe no ambiente. Retorna ``(ok, motivos)``."""
    info = info or detect_hardware()
    reasons: list = []
    if info.ram_total_gb < float(min_ram_gb):
        reasons.append(
            "RAM insuficiente: requer %.1f GB, disponível %.1f GB"
            % (float(min_ram_gb), info.ram_total_gb)
        )
    if min_vram_gb:
        if not info.has_gpu:
            reasons.append("Requer GPU com %.1f GB VRAM; nenhuma GPU detectada" % min_vram_gb)
        elif (info.vram_gb or 0) < float(min_vram_gb):
            reasons.append(
                "VRAM insuficiente: requer %.1f GB, disponível %.1f GB"
                % (float(min_vram_gb), info.vram_gb or 0)
            )
    return (not reasons), reasons


def available_headroom_gb(info: HardwareInfo) -> float:
    """Memória que ainda pode ser usada com margem de segurança de 20%."""
    return round(max(info.ram_available_gb - info.ram_total_gb * 0.2, 0.0), 2)


def summarise(info: HardwareInfo) -> str:
    """Resumo de uma linha para CLI/health-check."""
    profile = classify_profile(info)
    gpu = "%s (%.1f GB)" % (info.gpu_name, info.vram_gb) if info.has_gpu else "sem GPU dedicada"
    return (
        "RAM %.1f GB (livre %.1f) | CPU %d núcleos | %s | perfil %s | disco livre %.1f GB"
        % (
            info.ram_total_gb,
            info.ram_available_gb,
            info.cpu_cores,
            gpu,
            profile.key,
            info.disk_free_gb,
        )
    )
