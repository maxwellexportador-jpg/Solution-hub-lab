"""Registro de experimentos com reprodutibilidade.

Cada experimento vira um diretório com ``experiment.json`` contendo versão de
código, hash da configuração, dataset/checkpoint declarados, hardware, métricas
e caminhos de evidência. Nada é inventado: campos desconhecidos ficam ``null``.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .hardware import classify_profile, detect_hardware


def canonical_hash(payload: Any) -> str:
    """SHA-256 estável de um objeto JSON-serializável."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_version(repo_root: Path) -> Dict[str, Any]:
    """Commit e estado de trabalho do repositório (sem falhar fora de git)."""
    info: Dict[str, Any] = {"commit": None, "branch": None, "dirty": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if commit.returncode == 0:
            info["commit"] = commit.stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if branch.returncode == 0:
            info["branch"] = branch.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if status.returncode == 0:
            info["dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - ambiente
        pass
    return info


def environment_snapshot() -> Dict[str, Any]:
    hardware = detect_hardware()
    data = hardware.to_dict()
    data["profile"] = classify_profile(hardware).key
    data["python_executable"] = sys.executable
    data["machine"] = platform.machine()
    return data


@dataclass
class ExperimentRecord:
    experiment_id: str
    name: str
    created_at: str
    status: str
    code_version: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    config_sha256: str = ""
    dataset_id: Optional[str] = None
    checkpoint_ids: List[str] = field(default_factory=list)
    model_ids: List[str] = field(default_factory=list)
    environment: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    results_path: Optional[str] = None
    notes: str = ""
    finished_at: Optional[str] = None
    log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExperimentRecorder:
    """Cria, finaliza e lista experimentos em disco."""

    def __init__(self, root: Path, repo_root: Optional[Path] = None):
        self.root = Path(root)
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
        self.root.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        dataset_id: Optional[str] = None,
        checkpoint_ids: Sequence[str] = (),
        model_ids: Sequence[str] = (),
        notes: str = "",
    ) -> ExperimentRecord:
        if not name.strip():
            raise ValueError("nome do experimento é obrigatório")
        stamp = datetime.now(timezone.utc)
        experiment_id = "%s-%s" % (stamp.strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])
        config = config or {}
        record = ExperimentRecord(
            experiment_id=experiment_id,
            name=name.strip(),
            created_at=stamp.isoformat(),
            status="running",
            code_version=git_version(self.repo_root),
            config=config,
            config_sha256=canonical_hash(config),
            dataset_id=dataset_id,
            checkpoint_ids=list(checkpoint_ids),
            model_ids=list(model_ids),
            environment=environment_snapshot(),
            notes=notes,
        )
        record.log.append("started at %s" % record.created_at)
        self._write(record)
        return record

    def finish(
        self,
        record: ExperimentRecord,
        status: str,
        metrics: Optional[Dict[str, Any]] = None,
        results_path: Optional[str] = None,
    ) -> Path:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("status final inválido: %s" % status)
        record.status = status
        record.finished_at = datetime.now(timezone.utc).isoformat()
        record.metrics = dict(metrics or {})
        record.results_path = results_path
        record.log.append("finished with status=%s" % status)
        return self._write(record)

    def _write(self, record: ExperimentRecord) -> Path:
        directory = self.root / record.experiment_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "experiment.json"
        path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, experiment_id: str) -> ExperimentRecord:
        path = self.root / experiment_id / "experiment.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return ExperimentRecord(**data)

    def list(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for path in sorted(self.root.glob("*/experiment.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append(
                {
                    "experiment_id": data.get("experiment_id"),
                    "name": data.get("name"),
                    "status": data.get("status"),
                    "created_at": data.get("created_at"),
                    "finished_at": data.get("finished_at"),
                    "config_sha256": data.get("config_sha256"),
                    "commit": (data.get("code_version") or {}).get("commit"),
                }
            )
        return items
