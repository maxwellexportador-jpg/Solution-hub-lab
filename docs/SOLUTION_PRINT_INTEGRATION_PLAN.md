# Solution Print AI Lab — plano de integração

## Objetivo

Transformar este laboratório em uma camada experimental de modelos pequenos e treinamento, preservando o MiniMind upstream e conectando-o aos projetos Solution Print somente por adaptadores explícitos e testáveis.

## Regra de preservação

- O código upstream MiniMind permanece identificável e seus avisos/licença Apache-2.0 são preservados.
- Não reescrever arquivos upstream para encaixar integrações Solution Print.
- Código próprio fica em diretórios separados: `solution_print/`, `adapters/`, `tests/` e `docs/`.
- Toda alteração em arquivo upstream deve ser mínima, documentada e marcada conforme a licença.
- Este laboratório não substitui nem absorve os repositórios AI CORE, JARVIS, CRM, Android ou Studio 3D.

## Arquitetura alvo

```text
MiniMind upstream
  ├── model / tokenizer
  ├── trainer (pretrain, SFT, LoRA, DPO, PPO, GRPO, agent RL)
  ├── datasets / evaluation
  └── OpenAI-compatible inference API
          │
          ▼
Solution Print AI Lab
  ├── model registry + metadata
  ├── model router (local/cloud only when explicitly configured)
  ├── evaluation + regression suite
  ├── inference adapter (OpenAI-compatible)
  ├── safety gateway for tool calls
  ├── resource profiles (CPU / low RAM / GPU)
  └── experiment records + reproducibility
          │
          ▼
Explicit connectors (later, isolated)
  ├── AI CORE: model capability/provider adapter; IAM remains authoritative
  ├── JARVIS: inference + tool proposal; JARVIS supervisor approves every action
  ├── CRM: no direct database or customer-data access; only approved API contracts
  ├── Android / Studio 3D: future adapters after interface review
  └── no cross-project writes without separate authorization
```

## Fases de execução

### Fase 0 — Importação e preservação
- [x] Importar o MiniMind upstream para este laboratório.
- [x] Manter LICENSE, README, imagens, tokenizer, modelo, datasets auxiliares e scripts.
- [x] Registrar origem e execução da importação.
- [ ] Verificar árvore importada contra a árvore upstream e registrar commit upstream de referência.

### Fase 1 — Auditoria técnica isolada
- [x] Ler requisitos, README, arquitetura do modelo, scripts de treino e API.
- [x] Documentar limitações do computador Solution Print (8 GB RAM).
- [ ] Criar ambiente virtual isolado e instalar somente dependências mínimas aprovadas.
- [ ] Rodar smoke tests sem treinamento e sem baixar checkpoints grandes.
- [ ] Revisar segurança da API e do processamento de tool calls.

### Fase 2 — Camada Solution Print
- [ ] Criar registro de modelos e capacidades, sem assumir que o MiniMind é um modelo pronto para produção.
- [ ] Criar adaptador de inferência com contrato OpenAI-compatible e testes.
- [ ] Criar roteador que respeite limites de hardware, disponibilidade e política de custo.
- [ ] Criar gateway de ferramentas: saída do modelo é apenas proposta; nunca executa comandos diretamente.
- [ ] Criar avaliação PT-BR com casos reais anonimizados e dados sintéticos, sem importar dados de clientes.

### Fase 3 — Integrações controladas
- [ ] AI CORE: integrar por adaptador de provedor/modelo; IAM, grants, auditoria e isolamento do AI CORE continuam soberanos.
- [ ] JARVIS: integrar como backend de inferência/experimento; supervisor, memória e permissões do JARVIS continuam soberanos.
- [ ] CRM: somente API formal autorizada; sem conexão direta ao Supabase ou acesso a dados de clientes nesta fase.
- [ ] Android e Studio 3D: avaliar contratos antes de escrever conectores.

### Fase 4 — Treinamento e publicação
- [ ] Escolher dataset e objetivo mensurável.
- [ ] Estimar GPU, memória, armazenamento e custo antes da execução.
- [ ] Obter aprovação explícita para qualquer GPU cloud paga.
- [ ] Treinar, avaliar, versionar pesos e publicar apenas após aprovação.

## Critérios de aceite

1. MiniMind original continua rastreável e licenciado.
2. Nenhum projeto existente sofre alterações indiretas.
3. Inferência e tool calling passam por contratos e controles explícitos.
4. Testes cobrem compatibilidade, segurança, regressão e comportamento PT-BR.
5. Treino não começa sem orçamento, hardware e dados definidos.
6. Nenhum provedor pago é acionado sem autorização.

## Decisões já fixadas

- Laboratório separado: `Solution-hub-lab`.
- Preferência por soluções gratuitas e custos transparentes.
- PC local de 8 GB RAM: desenvolvimento e testes leves, não treinamento completo.
- Sem fallback pago automático.
- Integrações isoladas, sem alterar os projetos originais nesta etapa.
