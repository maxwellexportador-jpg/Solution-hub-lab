# Matriz Mestre de Execução — Solution Print AI Lab

Repositório: `maxwellexportador-jpg/Solution-hub-lab`
Camada: `solution_print/` (própria) sobre o MiniMind upstream (Apache-2.0, Jingyao Gong)
Contrato de integração: `1.0` · Versão da camada: `0.1.0`
Última atualização: 2026-11-19 (UTC)

## Regra de conclusão

Um lote só é **CONCLUÍDO** quando tem: código, revisão, testes executados,
resultado registrado, falhas corrigidas/documentadas, evidência em `evidence/`,
esta matriz atualizada e commit registrado. Caso contrário é **PARCIAL** ou
**BLOQUEADO** — nunca "concluído por existir o arquivo".

## Visão geral

| Lote | Nome | Estado | Evidência |
|---|---|---|---|
| L0 | Diagnóstico e preservação do upstream | CONCLUÍDO | `docs/COMPATIBILITY_AUDIT.md`, `tests/test_upstream.py` (7 testes), `evidence/01_unittest_lote1_5.log` |
| L1 | Base da camada (pacote, erros, contrato) | CONCLUÍDO | `solution_print/__init__.py`, `errors.py`, `tests/test_upstream.py` |
| L2 | Registro de modelos | CONCLUÍDO | `solution_print/registry.py`, `catalog.json`, `tests/test_registry.py` (13), `evidence/03_models_validate.log` |
| L3 | Roteador de modelos | CONCLUÍDO | `solution_print/router.py`, `tests/test_router.py` (14), `evidence/04_route_ptbr.log` |
| L4 | Adaptadores (echo / OpenAI-compat / MiniMind) | CONCLUÍDO¹ | `solution_print/adapters/`, `tests/test_adapters.py` (17) |
| L5 | Avaliação PT-BR | CONCLUÍDO² | `solution_print/evaluation.py`, `eval_cases_ptbr.json`, `tests/test_evaluation.py` (15), `evidence/06_eval_fixture.log` |
| L6 | Segurança de entrada/saída e de ferramentas | CONCLUÍDO | `solution_print/safety.py`, `tests/test_safety.py` (17) |
| L7 | Hardware e perfis de recursos | CONCLUÍDO | `solution_print/hardware.py`, `tests/test_hardware.py` (7), `evidence/02_doctor.json` |
| L8 | Experimentos e reprodutibilidade | CONCLUÍDO | `solution_print/experiments.py`, `tests/test_experiments.py` (8), `evidence/07_experiments.log` |
| L9 | API HTTP local | CONCLUÍDO | `solution_print/api.py`, `tests/test_api.py` (12) |
| L10 | CLI operacional | CONCLUÍDO | `solution_print/cli.py`, `evidence/02..07` (execuções reais) |
| L11 | Contratos de integração (5 projetos) | PARCIAL | `solution_print/integrations/`, `tests/test_integrations.py` (33) — contrato + testes com mock; integração real não autorizada/indisponível |
| L12 | CI GitHub Actions | PARCIAL | `.github/workflows/solution-print-ci.yml` criado; **execução não comprovada** (sem run id) |
| L13 | Documentação, matrizes e evidências | CONCLUÍDO | este arquivo + `TEST_EVIDENCE_MATRIX.md`, `INTEGRATION_STATUS.md`, `SECURITY_REVIEW.md`, `HARDWARE_COMPATIBILITY.md`, `FINAL_ACCEPTANCE_REPORT.md`, `evidence/` |
| L14 | Publicação nos repositórios externos (branches/PRs) | PENDENTE | nenhum branch/PR criado até o momento; plano em `docs/INTEGRATION_STATUS.md` |
| L15 | Publicação no repositório principal | PARCIAL | `evidence/08_bloqueios.txt` (item 7) — sem remote autenticado no worktree |

¹ L4 é concluído no que diz respeito ao código e aos testes; a inferência
**real** de MiniMind está bloqueada por ausência de checkpoint + `torch`
(`evidence/08_bloqueios.txt`).

² L5 executa o pipeline completo de avaliação, mas as respostas vêm do
adaptador de fixture (`simulated=True`). Não é benchmark de LLM.

## Detalhe dos lotes executáveis

### L0 — Diagnóstico e preservação
- Objetivo: confirmar que o MiniMind importado permanece reconhecível e separado.
- Arquivos: `model/`, `trainer/`, `dataset/`, `scripts/`, `images/`, `README.md`, `LICENSE` (intocados).
- Testes: `tests/test_upstream.py` — README contém "MiniMind" e "jingyaogong";
  `LICENSE` contém Apache 2.0; diretórios upstream existem; a camada é um pacote
  separado; `SOLUTION_PRINT_ORIGIN.md` existe.
- Resultado: 7/7 OK.

### L1 — Base da camada
- `solution_print/__init__.py` declara versão, `CONTRACT_VERSION = "1.0"` e
  crédito upstream; `errors.py` define a hierarquia tipada de erros.
- Nenhum módulo importa `torch` no nível de módulo (requisito para CI leve).

### L2 — Registro de modelos
- `catalog.json` (schema v1) com 7 modelos; `ModelSpec.validate()` recusa id
  inválido, capacidade desconhecida, status/custo inválidos, `endpoint`
  embutindo credenciais, modelo operacional sem limitações declaradas.
- `ModelRegistry` oferece load/save/filter/runnable/report e `public_view()`
  que esconde endpoint e nome da variável de ambiente.
- Resultado real: `7 modelos, 0 problemas` (`evidence/03_models_validate.log`).

### L3 — Roteador
- `RoutingPolicy(allow_paid=True)` levanta `PolicyViolation` — custo pago é
  estruturalmente impossível, não apenas desencorajado.
- Recusa por: custo, provedor não autorizado, status não operacional,
  capacidade ausente, RAM/VRAM insuficiente, adaptador indisponível.
- Fallback só entre modelos em `authorized_fallbacks`; `max_attempts` 1..3.
- Log de execução sem o texto do usuário (só sha256/digest) e persistência em disco.
- Resultado real em `evidence/04_route_ptbr.log`: escolhe `sp-echo-baseline-v1` e
  registra o motivo da recusa de cada um dos outros 6 modelos.

### L4 — Adaptadores
- `echo`: determinístico, sempre `simulated=True` (impede confundir fixture com LLM).
- `openai_compatible`: valida endpoint (http/https, sem credenciais na URL),
  bloqueia host público salvo `SOLUTION_PRINT_ALLOW_REMOTE_MODELS=1`, mapeia
  HTTP/timeout/JSON inválido para erros tipados, nunca loga a API key.
- `minimind`: carrega checkpoint **antes** de importar `torch`; mensagens de
  indisponibilidade explicam exatamente o que falta.
- Bug corrigido nesta execução: `minimind.infer()` importava `torch` antes de
  `_load()`, gerando `ModuleNotFoundError` em vez de `AdapterUnavailable`.

### L5 — Avaliação
- 11 casos em `eval_cases_ptbr.json`, categorias: conversação, pt-br, instrução,
  raciocínio, consistência, segurança.
- Checks: `not_empty`, `min_words`, `max_words`, `contains_any`, `contains_all`,
  `not_contains`, `regex`, `consistency` (similaridade entre duas execuções).
- Check desconhecido falha fechado.
- Relatórios JSON + Markdown com taxa de aprovação, latência e aviso de simulação.
- Resultado real: `3/11 (27.3%)` com o adaptador de fixture — número sem valor
  de benchmark, apenas prova de que o pipeline mede e reporta.

### L6 — Segurança
Ver `docs/SECURITY_REVIEW.md`. Resumo: validação de entrada, sanitização de
saída (ANSI/controle, injeção de prompt, marcadores de ferramenta), detecção e
redação de segredos, `ToolCallGateway` que **avalia** propostas e nunca executa.

### L7 — Hardware
6 perfis (`cpu-low`, `cpu-8gb`, `cpu-16gb`, `cpu-32gb`, `gpu-8gb`, `gpu-24gb`),
detecção real de RAM (respeitando cgroup), núcleos, disco e GPU via `nvidia-smi`.
Nesta máquina: `3.82 GB`, 2 núcleos, sem GPU, perfil `cpu-low`.

### L8 — Experimentos
`ExperimentRecorder` grava `experiment.json` com config + `config_sha256`,
versão de código (commit/dirty), snapshot de ambiente, dataset, modelos,
métricas e caminho do resultado — sem guardar prompts crus.

### L9 — API
`GET /health`, `GET /v1/models`, `POST /v1/chat/completions`, além do manifesto
de provedor. Corpo limitado a 128 KB, token Bearer obrigatório fora do loopback,
respostas de erro padronizadas (`{"error": {"code", "message"}}`).

### L10 — CLI
`doctor`, `models list|show|validate`, `route`, `infer`, `eval`, `serve`,
`experiments` — todos executados nesta máquina com saída real em `evidence/`.

## Pendências e próximo lote

| # | Pendência | Depende de | Ação |
|---|---|---|---|
| 1 | Inferência MiniMind real | checkpoint + `torch` + 8 GB livres | definir `SOLUTION_PRINT_MINIMIND_CHECKPOINT` e instalar deps |
| 2 | Endpoint OpenAI-compatible | llama.cpp/Ollama local | definir `SOLUTION_PRINT_LOCAL_ENDPOINT` |
| 3 | Execução do workflow CI | push + permissão Actions | verificar run id e anexar URL |
| 4 | Branches/PRs nos 5 repositórios externos | credencial de escrita | seguir `docs/INTEGRATION_STATUS.md` |
| 5 | Assinatura/constante-time do token da API | revisão de segurança | próxima iteração de L9 |
