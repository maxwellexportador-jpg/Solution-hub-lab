"""CLI do laboratório: diagnóstico, catálogo, roteamento, avaliação e API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from . import CONTRACT_VERSION, __version__
from .adapters import Message, create_adapter
from .errors import LabError
from .evaluation import Evaluator, write_report
from .experiments import ExperimentRecorder
from .hardware import classify_profile, detect_hardware, summarise
from .registry import ModelRegistry
from .router import ModelRouter, RoutingPolicy, RoutingRequest


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solution_print",
        description="Solution Print AI Lab — camada de modelos sobre o MiniMind (Apache-2.0).",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="diagnóstico de hardware, catálogo e adaptadores")
    doctor.add_argument("--json", action="store_true")

    models = sub.add_parser("models", help="listar, validar ou detalhar modelos")
    models.add_argument("action", nargs="?", default="list", choices=["list", "show", "validate"])
    models.add_argument("model_id", nargs="?")
    models.add_argument("--json", action="store_true")

    route = sub.add_parser("route", help="mostrar decisão de roteamento")
    route.add_argument("--task", default="chat")
    route.add_argument("--model", default=None)
    route.add_argument("--json", action="store_true")

    infer = sub.add_parser("infer", help="executar inferência via roteador")
    infer.add_argument("--prompt", required=True)
    infer.add_argument("--system", default=None)
    infer.add_argument("--model", default=None)
    infer.add_argument("--task", default="chat")
    infer.add_argument("--max-tokens", type=int, default=256)
    infer.add_argument("--temperature", type=float, default=0.2)
    infer.add_argument("--json", action="store_true")

    evaluate = sub.add_parser("eval", help="executar a suíte PT-BR")
    evaluate.add_argument("--model", default=None)
    evaluate.add_argument("--out", default="evidence/eval")
    evaluate.add_argument("--max-tokens", type=int, default=256)
    evaluate.add_argument("--json", action="store_true")

    serve = sub.add_parser("serve", help="subir a API HTTP")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)

    experiments = sub.add_parser("experiments", help="listar experimentos registrados")
    experiments.add_argument("--root", default="experiments")
    experiments.add_argument("--json", action="store_true")

    return parser


def _doctor(as_json: bool) -> int:
    hardware = detect_hardware()
    registry = ModelRegistry.builtin()
    router = ModelRouter(registry=registry, hardware=hardware)
    adapters: List[dict] = []
    for spec in registry.all():
        adapter = create_adapter(spec, environ=None)
        data = adapter.describe()
        data["hardware_ok"], data["hardware_reasons"] = spec.requirements_met(hardware)
        adapters.append(data)

    payload = {
        "version": __version__,
        "contract_version": CONTRACT_VERSION,
        "hardware": hardware.to_dict(),
        "profile": classify_profile(hardware).to_dict(),
        "summary": summarise(hardware),
        "models": len(registry),
        "adapters": adapters,
    }
    if as_json:
        _print_json(payload)
        return 0

    print("Solution Print AI Lab %s (contrato %s)" % (__version__, CONTRACT_VERSION))
    print("Hardware: %s" % summarise(hardware))
    print("Perfil: %s" % classify_profile(hardware).label)
    if hardware.notes:
        for note in hardware.notes:
            print("  nota: %s" % note)
    print("\nModelos conhecidos: %d" % len(registry))
    for item in adapters:
        state = "OK" if item["available"] else "INDISPONÍVEL"
        fits = "cabe" if item["hardware_ok"] else "não cabe"
        print(
            "  - %-34s %-18s %s (%s) | %s"
            % (item["model"], item["adapter"], state, fits, item["reason"][:80])
        )
    return 0


def _models(args: argparse.Namespace) -> int:
    registry = ModelRegistry.builtin()
    if args.action == "validate":
        problems = 0
        for spec in registry.all():
            errors = spec.validate()
            if errors:
                problems += len(errors)
                print("INVÁLIDO %s: %s" % (spec.id, "; ".join(errors)))
        print("Catálogo: %d modelos, %d problemas" % (len(registry), problems))
        return 1 if problems else 0

    if args.action == "show":
        if not args.model_id:
            print("informe o id do modelo", file=sys.stderr)
            return 2
        spec = registry.get(args.model_id)
        payload = spec.to_dict()
        payload["endpoint_configured"] = bool(spec.resolved_endpoint())
        if args.json:
            _print_json(payload)
        else:
            for key, value in payload.items():
                print("%-22s %s" % (key + ":", value))
        return 0

    rows = registry.report(detect_hardware())
    if args.json:
        _print_json(rows)
        return 0
    print("%-34s %-18s %-14s %-6s %-5s" % ("id", "provider", "status", "custo", "cabe"))
    for row in rows:
        print(
            "%-34s %-18s %-14s %-6s %-5s"
            % (row["id"], row["provider"], row["status"], row["cost"], "sim" if row["fits"] else "não")
        )
    return 0


def _route(args: argparse.Namespace) -> int:
    router = ModelRouter()
    decision = router.route(RoutingRequest(task=args.task, preferred_model=args.model))
    if args.json:
        _print_json(decision.to_dict())
        return 0
    print("Modelo escolhido: %s (%s)" % (decision.model_id, decision.adapter))
    print("Cadeia autorizada: %s" % ", ".join(decision.chain))
    print("Motivos:")
    for reason in decision.reasons:
        print("  - %s" % reason)
    if decision.rejected:
        print("Recusados:")
        for item in decision.rejected:
            print("  - %s: %s" % (item.model_id, "; ".join(item.reasons)))
    return 0


def _infer(args: argparse.Namespace) -> int:
    router = ModelRouter()
    messages = []
    if args.system:
        messages.append(Message("system", args.system))
    messages.append(Message("user", args.prompt))
    result = router.infer(
        request=RoutingRequest(
            task=args.task,
            preferred_model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        ),
        messages=messages,
    )
    if args.json:
        _print_json(result.to_dict())
        return 0
    if result.response.simulated:
        print("[SIMULADO — não é inferência real]")
    print("Modelo: %s" % result.response.model)
    print("Latência: %.1f ms" % result.response.latency_ms)
    print("Resposta:\n%s" % result.response.text)
    return 0


def _eval(args: argparse.Namespace) -> int:
    router = ModelRouter()
    if args.model:
        spec = router.registry.get(args.model)
        decision_model = spec.id
    else:
        decision_model = router.route(RoutingRequest(task="ptbr")).model_id
    adapter = router.adapter_for(decision_model)
    evaluator = Evaluator(max_tokens=args.max_tokens, temperature=0.0)
    report = evaluator.run(adapter, model_id=decision_model)
    json_path, markdown_path = write_report(report, Path(args.out))
    if args.json:
        _print_json(report["summary"])
    else:
        summary = report["summary"]
        print(
            "Avaliação %s: %d/%d aprovados (%.1f%%) em %.2f ms médio"
            % (
                decision_model,
                summary["passed"],
                summary["total"],
                summary["pass_rate"] * 100,
                summary["latency_ms"]["mean"],
            )
        )
        if report["simulated"]:
            print("Aviso: resultado SIMULADO (fixture), não é benchmark de modelo real.")
        print("Relatórios: %s | %s" % (json_path, markdown_path))
    return 0


def _serve(args: argparse.Namespace) -> int:
    from .api import serve

    serve(host=args.host, port=args.port)
    return 0


def _experiments(args: argparse.Namespace) -> int:
    recorder = ExperimentRecorder(Path(args.root))
    items = recorder.list()
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("Nenhum experimento registrado em %s" % args.root)
        return 0
    for item in items:
        print(
            "%s | %s | %s | %s"
            % (item["experiment_id"], item["status"], item["name"], item["created_at"])
        )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(args.json)
        if args.command == "models":
            return _models(args)
        if args.command == "route":
            return _route(args)
        if args.command == "infer":
            return _infer(args)
        if args.command == "eval":
            return _eval(args)
        if args.command == "serve":
            return _serve(args)
        if args.command == "experiments":
            return _experiments(args)
    except LabError as exc:
        print("erro (%s): %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    parser.error("comando não implementado")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
