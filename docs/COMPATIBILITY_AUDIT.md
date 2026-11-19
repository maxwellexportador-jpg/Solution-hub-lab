# MiniMind — auditoria inicial de compatibilidade

Data: 2026-11-19  
Escopo: leitura estática dos arquivos importados. Nenhum treinamento, instalação de dependências ou download de pesos foi iniciado.

## Resultado da importação

- Workflow GitHub Actions `Import MiniMind upstream`: execução #1 concluída com `success`.
- Código, documentação, tokenizer, imagens e scripts foram encontrados na árvore `main`.
- Licença upstream Apache License 2.0 e avisos de origem foram mantidos.
- Origem: https://github.com/jingyaogong/minimind

## Componentes confirmados

- Arquitetura de modelo: `model/model_minimind.py` (PyTorch + Transformers).
- LoRA: `model/model_lora.py`.
- Dados: `dataset/lm_dataset.py`.
- Treinamento: pretraining, full SFT, LoRA, DPO, PPO, GRPO, distillation e agentic RL em `trainer/`.
- Inferência/API: `eval_llm.py`, `scripts/serve_openai_api.py`, `scripts/chat_api.py` e `scripts/web_demo.py`.
- Tool calling e tags de raciocínio são tratados no template/tokenizer e na camada de serviço.

## Dependências e ambiente

O `requirements.txt` fixa várias bibliotecas Python, mas deixa PyTorch comentado. A instalação de PyTorch deve ser uma etapa separada, escolhida conforme SO, CPU/GPU e CUDA. Não instalar cegamente todas as dependências opcionais em uma única máquina.

O README upstream usa como referência Python 3.10.16, Ubuntu 20.04, CUDA 12.2 e GPUs RTX 3090 (24 GB); esse perfil não corresponde ao computador Solution Print informado (8 GB de RAM e sem GPU dedicada confirmada).

## Limites práticos para o ambiente Solution Print

- Não iniciar pretraining, full SFT, DPO, PPO, GRPO ou Agentic RL no computador de 8 GB.
- Os padrões dos scripts de treino usam configurações pesadas (por exemplo, batch size 16 e sequências de até 768 tokens em full SFT); não são presets adequados para o equipamento local.
- A referência de “2 horas / custo baixo” no README é apenas uma epoch de SFT em uma NVIDIA RTX 3090, não treinamento completo nem promessa para CPU.
- Primeiro caminho de validação: análise estática, testes pequenos de tokenizer/configuração/modelo em ambiente isolado e sem baixar datasets ou checkpoints grandes.
- Treinamento de verdade deve ser avaliado em GPU cloud com orçamento e limite de custo aprovados antes de qualquer execução.

## Riscos e correções necessárias antes de expor serviço

- Revisar API FastAPI: autenticação, CORS, limites de tokens, concorrência, timeouts, tratamento de erros e exposição de endpoints.
- Tool calling do MiniMind deve ser tratado como saída não confiável. Nunca executar ferramenta diretamente sem passar pelo supervisor de permissões do JARVIS/AI CORE.
- Não habilitar `trust_remote_code=True` para modelos externos sem revisão do código baixado.
- Separar dependências de treinamento, inferência e interface; evitar instalar `wandb`, `swanlab`, `ngrok`, Streamlit e bibliotecas de treino quando não necessárias.
- Pesos pré-treinados e datasets não estão incluídos automaticamente nesta cópia do código; obter apenas quando necessário e verificar origem, licença e tamanho.

## Status

Auditoria estática inicial concluída. Não equivale a teste de execução. Ainda não foram executados testes Python, instaladas dependências, baixados pesos/datasets ou iniciado treinamento.
