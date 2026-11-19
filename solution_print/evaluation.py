"""Suíte de avaliação em português brasileiro com métricas reprodutíveis.

Os casos são sintéticos e não contêm dados de clientes. A pontuação é
determinística (regras explícitas) para que o resultado seja reproduzível e
auditável, sem depender de outro modelo como juiz.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .adapters import BaseAdapter, InferenceRequest, Message
from .errors import AdapterError, ValidationError
from .hardware import classify_profile, detect_hardware, summarise

CASES_PATH = Path(__file__).with_name("eval_cases_ptbr.json")
KNOWN_CHECKS = frozenset(
    {
        "not_empty",
        "min_words",
        "max_words",
        "contains_any",
        "contains_all",
        "not_contains",
        "regex",
        "consistency",
    }
)


def _words(text: str) -> List[str]:
    return re.findall(r"[0-9A-Za-zÀ-ÿ_]+", text.lower())


def _jaccard(first: str, second: str) -> float:
    a, b = set(_words(first)), set(_words(second))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class EvalCase:
    id: str
    category: str
    prompt: str
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        if not self.id or not re.match(r"^[a-z0-9][a-z0-9-]{2,40}$", self.id):
            raise ValidationError("id de caso inválido: %r" % self.id)
        if not self.category:
            raise ValidationError("caso %s sem categoria" % self.id)
        if not self.prompt.strip():
            raise ValidationError("caso %s sem prompt" % self.id)
        if not self.checks:
            raise ValidationError("caso %s sem verificações" % self.id)
        for check in self.checks:
            if check.get("type") not in KNOWN_CHECKS:
                raise ValidationError(
                    "caso %s usa verificação desconhecida: %r" % (self.id, check.get("type"))
                )


def load_cases(path: Optional[Path] = None) -> List[EvalCase]:
    location = Path(path) if path else CASES_PATH
    with location.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    cases = [EvalCase(**item) for item in data.get("cases", [])]
    if not cases:
        raise ValidationError("suíte de avaliação vazia")
    seen = set()
    for case in cases:
        case.validate()
        if case.id in seen:
            raise ValidationError("caso duplicado: %s" % case.id)
        seen.add(case.id)
    return cases


def run_check(check: Dict[str, Any], text: str, second: Optional[str] = None) -> Tuple[bool, str]:
    """Executa uma verificação declarativa. Retorna ``(ok, detalhe)``."""
    kind = check.get("type")
    value = check.get("value")
    if kind == "not_empty":
        return bool(text.strip()), "vazio" if not text.strip() else "ok"
    if kind == "min_words":
        count = len(_words(text))
        return count >= int(value), "%d palavras (min %s)" % (count, value)
    if kind == "max_words":
        count = len(_words(text))
        return count <= int(value), "%d palavras (max %s)" % (count, value)
    if kind == "contains_any":
        hits = [token for token in value if token.lower() in text.lower()]
        return bool(hits), "encontrados: %s" % (", ".join(hits) or "nenhum")
    if kind == "contains_all":
        missing = [token for token in value if token.lower() not in text.lower()]
        return not missing, "faltando: %s" % (", ".join(missing) or "nada")
    if kind == "not_contains":
        found = [token for token in value if token.lower() in text.lower()]
        return not found, "proibidos encontrados: %s" % (", ".join(found) or "nenhum")
    if kind == "regex":
        return bool(re.search(value, text, flags=re.MULTILINE)), "regex %r" % value
    if kind == "consistency":
        if second is None:
            return False, "segunda execução ausente"
        score = _jaccard(text, second)
        return score >= float(value), "similaridade %.2f (min %s)" % (score, value)
    return False, "verificação desconhecida"


class Evaluator:
    """Executa a suíte contra um adaptador e grava resultados."""

    def __init__(
        self,
        cases: Optional[Sequence[EvalCase]] = None,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ):
        self.cases = list(cases or load_cases())
        self.max_tokens = max_tokens
        self.temperature = temperature

    def run(
        self,
        adapter: BaseAdapter,
        model_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        model_id = model_id or adapter.spec.id
        hardware = detect_hardware()
        started_at = datetime.now(timezone.utc).isoformat()
        results: List[Dict[str, Any]] = []
        simulated_flags: List[bool] = []

        for case in self.cases:
            entry: Dict[str, Any] = {
                "id": case.id,
                "category": case.category,
                "prompt_sha256": _digest(case.prompt),
            }
            try:
                first = adapter.infer(
                    InferenceRequest(
                        model=model_id,
                        messages=[Message("user", case.prompt)],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        metadata=dict(metadata or {}),
                    )
                )
                second_text: Optional[str] = None
                if any(check.get("type") == "consistency" for check in case.checks):
                    second = adapter.infer(
                        InferenceRequest(
                            model=model_id,
                            messages=[Message("user", case.prompt)],
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                            metadata=dict(metadata or {}),
                        )
                    )
                    second_text = second.text
                checks = []
                for check in case.checks:
                    ok, detail = run_check(check, first.text, second_text)
                    checks.append(
                        {"type": check.get("type"), "passed": ok, "detail": detail[:200]}
                    )
                passed = all(item["passed"] for item in checks)
                entry.update(
                    {
                        "status": "ok" if passed else "failed",
                        "passed": passed,
                        "checks": checks,
                        "latency_ms": round(first.latency_ms, 3),
                        "output_chars": len(first.text),
                        "output_preview": first.text[:200],
                        "simulated": first.simulated,
                    }
                )
                simulated_flags.append(first.simulated)
            except AdapterError as exc:
                entry.update(
                    {
                        "status": "error",
                        "passed": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                    }
                )
            results.append(entry)

        report = {
            "schema_version": 1,
            "generated_at": started_at,
            "model": model_id,
            "adapter": adapter.name,
            "provider": adapter.spec.provider,
            "simulated": any(simulated_flags) if simulated_flags else True,
            "environment": {
                "summary": summarise(hardware),
                "profile": classify_profile(hardware).key,
                "python": hardware.python_version,
                "platform": hardware.platform,
                "ram_total_gb": hardware.ram_total_gb,
                "gpu": hardware.gpu_name,
            },
            "cases": results,
            "summary": self._summarise(results),
        }
        return report

    @staticmethod
    def _summarise(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(results)
        passed = sum(1 for item in results if item.get("passed"))
        errors = sum(1 for item in results if item.get("status") == "error")
        latencies = [item["latency_ms"] for item in results if "latency_ms" in item]
        by_category: Dict[str, Dict[str, int]] = {}
        for item in results:
            bucket = by_category.setdefault(item["category"], {"total": 0, "passed": 0})
            bucket["total"] += 1
            if item.get("passed"):
                bucket["passed"] += 1
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "errors": errors,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "by_category": by_category,
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
                "p50": round(statistics.median(latencies), 2) if latencies else 0.0,
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
        }


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_report(report: Dict[str, Any], directory: Path) -> Tuple[Path, Path]:
    """Grava o relatório em JSON e Markdown; devolve os caminhos."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"].replace("+00:00", "Z").replace(":", "-")
    stem = "%s_%s" % (report["model"].replace("/", "_"), stamp)
    json_path = target / (stem + ".json")
    markdown_path = target / (stem + ".md")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = report["summary"]
    lines = [
        "# Relatório de avaliação — %s" % report["model"],
        "",
        "- Gerado em: %s" % report["generated_at"],
        "- Adaptador: %s (%s)" % (report["adapter"], report["provider"]),
        "- Simulado: %s" % ("sim" if report["simulated"] else "não"),
        "- Ambiente: %s" % report["environment"]["summary"],
        "- Casos: %d | Aprovados: %d | Reprovados: %d | Erros: %d | Taxa: %.1f%%"
        % (
            summary["total"],
            summary["passed"],
            summary["failed"],
            summary["errors"],
            summary["pass_rate"] * 100,
        ),
        "- Latência (ms): média %.2f | p50 %.2f | máx %.2f"
        % (
            summary["latency_ms"]["mean"],
            summary["latency_ms"]["p50"],
            summary["latency_ms"]["max"],
        ),
        "",
        "| Caso | Categoria | Status | Detalhe |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["cases"]:
        detail = ""
        if item.get("error"):
            detail = "%s: %s" % (item.get("error_type"), item["error"])
        elif item.get("checks"):
            failures = [c for c in item["checks"] if not c["passed"]]
            detail = "; ".join("%s (%s)" % (c["type"], c["detail"]) for c in failures) or "todas as verificações passaram"
        lines.append(
            "| %s | %s | %s | %s |"
            % (item["id"], item["category"], item.get("status", "?"), detail.replace("|", "/")[:180])
        )
    if report["simulated"]:
        lines += [
            "",
            "> **Aviso:** resultados marcados como simulados vêm do adaptador de fixture e **não**",
            "> representam qualidade de modelo real. Não use esta tabela como benchmark.",
        ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def compare_reports(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Compara dois relatórios e devolve diferenças por caso e agregadas."""
    base_cases = {item["id"]: item for item in baseline.get("cases", [])}
    cand_cases = {item["id"]: item for item in candidate.get("cases", [])}
    changes = []
    for case_id in sorted(set(base_cases) | set(cand_cases)):
        before = base_cases.get(case_id, {})
        after = cand_cases.get(case_id, {})
        before_passed = bool(before.get("passed"))
        after_passed = bool(after.get("passed"))
        changes.append(
            {
                "id": case_id,
                "before": before.get("status", "missing"),
                "after": after.get("status", "missing"),
                "regression": before_passed and not after_passed,
                "improvement": after_passed and not before_passed,
            }
        )
    base_rate = baseline.get("summary", {}).get("pass_rate", 0.0)
    cand_rate = candidate.get("summary", {}).get("pass_rate", 0.0)
    return {
        "baseline_model": baseline.get("model"),
        "candidate_model": candidate.get("model"),
        "pass_rate_delta": round(cand_rate - base_rate, 4),
        "regressions": [item["id"] for item in changes if item["regression"]],
        "improvements": [item["id"] for item in changes if item["improvement"]],
        "cases": changes,
    }
