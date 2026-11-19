# Matriz de Testes e Evidências

Data da execução: **2026-11-19 (UTC)** · Branch de trabalho: `freebuff/b87b49b1c898496c7819ae81`
Suíte: `unittest` da biblioteca padrão, sem PyTorch, sem GPU, sem rede externa.

## Resultado consolidado

| Métrica | Valor |
|---|---|
| Arquivos de teste | 10 (`tests/test_*.py`) + `tests/helpers.py` |
| Casos de teste | **143** |
| Aprovados | **143** |
| Reprovados | **0** |
| Erros | **0** |
| Tempo | ~9,7 s |
| Código de saída | **0** |
| Log | `evidence/01_unittest_lote1_5.log` (com cabeçalho de data/branch/comando) |

Comando exato:

```bash
python3 -m unittest discover -s tests -t .
```

## Cobertura por arquivo

| Arquivo | Casos | O que verifica | Lote |
|---|---|---|---|
| `tests/test_upstream.py` | 7 | preservação de README/LICENSE/autoria, separação da camada, ausência de segredos no código, catálogo sem modelo pago, `.gitignore` | L0 |
| `tests/test_registry.py` | 13 | carga do catálogo, validação de campos, duplicata, id inválido, campo desconhecido, filtro por capacidade/custo, relatório de hardware, `public_view`, round-trip de save/load | L2 |
| `tests/test_router.py` | 14 | rota por tarefa, modelo preferido, modelo inexistente, indisponível com motivo, custo pago recusado, tarefa desconhecida, orçamento de hardware, fallback autorizado/não autorizado, timeout, resposta malformada, log sem prompt, log em disco | L3 |
| `tests/test_adapters.py` | 17 | echo determinístico e marcado como simulado, entrada vazia recusada, endpoint público bloqueado, endpoint com credenciais recusado, sucesso HTTP, erro HTTP, 401 sem vazar chave, JSON malformado, timeout, `choices` ausente, tool calling não suportado, MiniMind indisponível sem checkpoint e **sem importar torch** | L4 |
| `tests/test_evaluation.py` | 15 | todos os checks, consistência entre execuções, check desconhecido falha fechado, validação da suíte PT-BR, execução com adaptador com falha, comparação de relatórios, escrita de relatório | L5 |
| `tests/test_safety.py` | 17 | entrada vazia/não-texto/nula/oversized, remoção de ANSI/controle, detecção de injeção de prompt, truncamento, tipos de segredo e redação, ferramenta desconhecida negada, ferramenta privilegiada proibida, argumento não permitido, limite de chamadas, ferramenta autorizada nunca executa (`pending_approval`) | L6 |
| `tests/test_hardware.py` | 7 | detecção real, 6 perfis obrigatórios, classificação CPU/GPU, requisitos de RAM/VRAM, resumo legível, margem de segurança | L7 |
| `tests/test_experiments.py` | 8 | hash canônico estável, snapshot de ambiente, versão de código, start/finish, status inválido, nome vazio, list/load, config persistida com hash | L8 |
| `tests/test_api.py` | 12 | `/health`, `/v1/models` marcando simulados, token obrigatório (401), chat completion, modelo desconhecido (404), JSON inválido (400), mensagens ausentes, corpo grande, taxa de `simulated`, manifesto | L9 |
| `tests/test_integrations.py` | 33 | `TenantContext`, envelope de inferência, versão de contrato, bloqueio de PII, manifesto de provedor, cliente AI CORE (mock HTTP), bridge JARVIS + supervisor de ferramentas, CRM (tarefa + PII), Android (chat), Studio 3D, `lab_gateway`, validação de base URL | L11 |

## Execuções de CLI registradas (saída real, não simulada de máquina)

| Evidência | Comando | Resultado |
|---|---|---|
| `evidence/02_doctor.json` | `python3 -m solution_print doctor --json` | RAM 3,82 GB · 2 núcleos · sem GPU · perfil `cpu-low` · 7 adaptadores, 1 habilitado (`sp-echo-baseline-v1`) |
| `evidence/03_models_validate.log` | `python3 -m solution_print models validate` | `Catálogo: 7 modelos, 0 problemas` |
| `evidence/04_route_ptbr.log` | `python3 -m solution_print route --task ptbr` | escolhe `sp-echo-baseline-v1`; 6 recusas com motivo individual |
| `evidence/05_infer_fixture.json` | `python3 -m solution_print infer --prompt "..." --json` | `simulated: true`, latency e trace_id |
| `evidence/06_eval_fixture.log` | `python3 -m solution_print eval --model sp-echo-baseline-v1` | `3/11 aprovados (27.3%)` + aviso de simulação + relatórios gerados |
| `evidence/07_experiments.log` | `python3 -m solution_print experiments --json` | lista de experimentos (vazia nesta máquina) |
| `evidence/08_bloqueios.txt` | verificações de ambiente | `torch`/`transformers`/checkpoint/GPU ausentes |

## Testes previstos e não executados

| Teste | Bloqueio real | Alternativa executada |
|---|---|---|
| Inferência MiniMind (pesos reais) | sem checkpoint e sem `torch` | teste de indisponibilidade + `AdapterUnavailable` verificado |
| Inferência via endpoint local | nenhum llama.cpp/Ollama configurado | servidor HTTP falso em loopback (`tests/helpers.py`) exercitando o mesmo código de cliente |
| Testes de GPU/CUDA | máquina sem GPU | perfis de hardware e recusa por VRAM testados com `HardwareInfo` sintético |
| Workflows GitHub Actions | sem execução disparada | workflow criado; **não** contabilizado como executado |
| Integração real com AI CORE/JARVIS/CRM/Android/Studio 3D | serviços não disponíveis/credenciais não concedidas | contratos + clientes testados contra mock local |
| Load/estresse e rate limit | não implementado | documentado como lacuna em `SECURITY_REVIEW.md` |

## Regra de honestidade aplicada

- Nenhum resultado de fixture foi apresentado como inferência real:
  toda resposta do adaptador `echo` carrega `simulated: true` e o relatório de
  avaliação imprime "resultado SIMULADO (fixture)".
- Nenhum teste foi marcado como executado sem log com código de saída.
