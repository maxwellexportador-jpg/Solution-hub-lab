# Estado final verificado — 2026-11-19

Documento autoritativo. Substitui as linhas L12/L14/L15 de
`MASTER_EXECUTION_MATRIX.md` e a seção "Situação de publicação" de `INTEGRATION_STATUS.md`,
escritas antes destas execuções.

## Lotes (15)

Concluídos: L0, L1, L2, L3, L4, L5, L6, L7, L8, L9, L10, L13 (12).
Parciais: L11 (contrato testado, integração real não executada), L12 (CI criado **e executado**:
run `44490005099`, success), L15 (branch + commit + PR #1; merge em `main` não feito).
Bloqueado: L14 (CRM e JARVIS publicados em PR; AI CORE, Android e Studio 3D recusaram escrita
com HTTP 403 — registro em `evidence/10_publicacao_externa.txt`).

## Testes

143 casos, 143 aprovados, 0 reprovados, 0 erros, ~9,7 s (`evidence/01_unittest_lote1_5.log`).
No runner do GitHub Actions: run `44489665564` (success) e `44490005099` (success).
Não executáveis aqui: inferência MiniMind real, avaliação com LLM real, GPU/CUDA — sem `torch`,
sem checkpoint, sem GPU (`evidence/08_bloqueios.txt`).

## Funciona de verdade

registro e validação de catálogo; roteamento com recusas motivadas; adaptadores echo e
OpenAI-compatible (contra servidor falso); avaliação PT-BR; sanitização e gateway de ferramentas;
perfis de hardware; experimentos reprodutíveis; API HTTP local; CLI; contratos de integração.

## Preparado, não funcionando

Integrações com AI CORE, JARVIS, CRM, Android e Studio 3D (contrato + testes com servidor falso).
Inferência de MiniMind (adaptador existe, caminho real não executado). Publicação de endpoint
fora do loopback. Merge do PR #1.

## Links verificados

- PR do laboratório: https://github.com/maxwellexportador-jpg/Solution-hub-lab/pull/1
- PR do CRM: https://github.com/maxwellexportador-jpg/solution-hub-ai/pull/50 (commit `e4d8c401`)
- PR do JARVIS: https://github.com/maxwellexportador-jpg/solution-print-jarvis/pull/2 (commit `4f538ac1`)
- CI: https://github.com/maxwellexportador-jpg/Solution-hub-lab/actions/runs/44490005099
- Bootstrap de publicação: https://github.com/maxwellexportador-jpg/Solution-hub-lab/actions/runs/44489665564

## Custo

R$ 0,00. Nenhum serviço contratado, nenhuma GPU paga, nenhum peso/dataset baixado, nenhum deploy.
