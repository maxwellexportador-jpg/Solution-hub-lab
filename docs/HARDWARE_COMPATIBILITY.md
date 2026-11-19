# Compatibilidade de Hardware — Solution Print AI Lab

Data: 2026-11-19 · Base: detecção real (`solution_print/hardware.py`) + catálogo (`catalog.json`) + perfis declarados.

## Ambiente medido nesta execução

| Item | Valor real | Comando |
|---|---|---|
| RAM total | **3,82 GB** | `python3 -m solution_print doctor --json` |
| RAM disponível | 3,44 GB | idem |
| Núcleos de CPU | **2** | idem |
| GPU | **nenhuma** (`nvidia-smi` não existe) | `nvidia-smi` |
| Disco livre | 9,65 GB | `doctor` |
| Perfil classificado | **`cpu-low`** | idem |
| PyTorch / transformers | ausentes | `importlib.util.find_spec` |

O perfil foi classificado automaticamente como `cpu-low` (não como `ram-8gb`),
porque a regra usa a RAM **disponível**, não a nominal. Isso é intencional: um
modelo que só cabe na RAM total, mas não na livre, faria o processo ser morto
pelo OOM killer no meio da inferência.

## Perfis obrigatórios e o que cada um suporta

| Perfil (`key`) | RAM mínima | VRAM | Modelos que cabem hoje | Observação |
|---|---|---|---|---|
| `cpu-low` | < 6 GB | — | `sp-echo-baseline-v1` (fixture) | ambiente desta validação |
| `ram-8gb` | 8 GB | — | Qwen2.5-0.5B (Q4), MiniMind-3-small (64M) | máquina principal do proprietário |
| `ram-16gb` | 16 GB | — | Qwen2.5-1.5B/3B Q4, MiniMind + LoRA SFT leve | CPU inference lenta, mas viável |
| `ram-32gb` | 32 GB | — | Qwen2.5-7B Q4 (CPU), fine-tuning LoRA pequeno | ainda sem treino pleno |
| `gpu-limited` | 8 GB+ | ≥ 6 GB | 7B Q4 em GPU, SFT MiniMind | requer CUDA compatível |
| `gpu-large` | 32 GB+ | ≥ 16 GB | 7B–14B, full SFT MiniMind, DPO/GRPO | fora do escopo local |

## Modelos do catálogo × requisitos declarados

| Modelo | Provider | RAM | VRAM | Custo | Status | Cabe em `cpu-low`? |
|---|---|---|---|---|---|---|
| `sp-echo-baseline-v1` | mock | 0,1 GB | — | free | available | **sim** (fixture, não é LLM) |
| `minimind-3-small` | local (torch) | 4,0 GB | — | free | needs_setup | não (RAM disponível 3,44 GB) e falta checkpoint/torch |
| `local-openai-compatible` | local http | 2,0 GB | — | free | needs_setup | depende de endpoint; não configurado |
| `qwen2.5-0.5b-instruct-gguf` | http | 1,5 GB | — | free | needs_setup | depende de endpoint (llama.cpp/Ollama) |
| `qwen2.5-1.5b-instruct-gguf` | http | 4,0 GB | — | free | needs_setup | não |
| `qwen2.5-7b-instruct-gguf` | http | 12,0 GB | 6,0 GB | free | needs_setup | não |
| `llama-3.2-3b-instruct-gguf` | http | 6,0 GB | — | free | planned | não |

Nenhum modelo pago existe no catálogo — garantido por teste
(`tests/test_upstream.py::test_catalog_has_no_paid_model`).

## Regras de segurança de memória aplicadas

1. `doctor` mede RAM **disponível** e reserva margem (`hardware.py`); o roteador
   recusa modelo cujo `min_ram_gb` não cabe no orçamento calculado.
2. Motivo da recusa é sempre explícito (`RAM insuficiente: requer 6.0 GB,
   disponível 3.8 GB`), nunca um "não encontrado" genérico — evidência em
   `evidence/04_route_ptbr.log`.
3. GPU só é considerada quando detectada de fato; ausência de GPU não é
   inferida como "talvez tenha".

## O que **não** foi testado (e por quê)

| Item | Bloqueio |
|---|---|
| Inferência MiniMind real | sem `torch`, sem `transformers`, sem checkpoint `.pth` |
| Inferência Qwen/Llama GGUF | nenhum endpoint llama.cpp/Ollama configurado |
| Medição de VRAM / CUDA | nenhuma GPU no ambiente |
| Treino (pretrain/SFT/LoRA/DPO/GRPO) | proibido pela missão e inviável neste hardware |
| Throughput tokens/s em 8 GB | exige a máquina do proprietário com modelo baixado |

## Recomendação para a máquina de 8 GB

1. Rodar `python3 -m solution_print doctor` para confirmar o perfil real.
2. Usar Qwen2.5-0.5B/1.5B em GGUF Q4 via llama.cpp ou Ollama (endpoint local
   OpenAI-compatible) e registrar com `SOLUTION_PRINT_ENDPOINT_*`.
3. Nunca iniciar treino nesse equipamento; SFT/LoRA do MiniMind só em GPU
   alugada **com orçamento aprovado** (custo atual: R$ 0,00).
