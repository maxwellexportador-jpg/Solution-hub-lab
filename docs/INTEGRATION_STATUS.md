# Situação das Integrações — Solution Print AI Lab

Data: 2026-11-19 · Contrato: `1.0` · Provider id: `solution-hub-lab`
Regra: cada projeto é um sistema autônomo. O laboratório **não** substitui IAM,
supervisão, memória ou banco de dados de ninguém — ele apenas oferece inferência
e metadados, e solicita autorização a quem é dono da decisão.

## Como o laboratório se apresenta

| Item | Valor |
|---|---|
| Endpoint de saúde | `GET /health` |
| Catálogo (formato OpenAI) | `GET /v1/models` |
| Inferência | `POST /v1/chat/completions` |
| Decisão de roteamento (transparência) | `GET /v1/lab/route` |
| Manifesto de provedor (AI CORE) | `GET /api/providers/solution-hub-lab/manifest` |
| Inferência como provedor (AI CORE) | `POST /api/providers/solution-hub-lab/infer` |
| Autenticação local | `Authorization: Bearer <token>` (`SOLUTION_PRINT_API_TOKEN`), obrigatório fora do loopback |
| Custo | sempre `free`; `allow_paid=True` é rejeitado com `PolicyViolation` |

Envelope de inferência (`InferenceEnvelopeRequest`) exige `tenant`
(`tenant_id`, `user_id`, `grant_id`, `scopes`, `request_id`), `messages`,
`contract_version`. Escopo mínimo: `ai.infer`. O laboratório **não** amplia
escopos: se o grant recebido não tem `ai.infer`, a chamada falha.

## 1. AI CORE — `maxwellexportador-jpg/solution-print-ai-core`

| Aspecto | Situação |
|---|---|
| Arquitetura observada | Node/JS com `src/adapters`, `src/providers`, `authz.js`, `session.js`, `openapi.json`; docs `ADAPTERS.md`, `MODEL-ROUTER.md`, `PROVIDERS.md` |
| Contrato no laboratório | **PRONTO** (`integrations/ai_core.py`: `AiCoreClient`, `ProviderManifest`, `build_manifest`) |
| Testes | 33 testes de contrato em `tests/test_integrations.py`, com servidor HTTP falso — **EXECUTADOS OK** |
| Integração real | **NÃO EXECUTADA** — depende de credencial, grant `ai.infer` e deploy do laboratório |
| Documentação no repositório externo | **PENDENTE** (`docs/INTEGRATION_SOLUTION_HUB_LAB.md` + `docs/SOLUTION_HUB_LAB_CONTRACT.md` na branch `docs/solution-hub-lab-integration`) |
| O que o laboratório preserva | `authz.js`/`session.js` continuam donos de identidade e permissão; o laboratório só recebe envelope já autorizado e devolve `tenant_id`/`request_id` recebidos |
| O que **não** trafega | dados de cliente, credenciais do AI CORE, segredos de provedor, conteúdo de sessão |

## 2. JARVIS — `maxwellexportador-jpg/solution-print-jarvis`

| Aspecto | Situação |
|---|---|
| Arquitetura observada | repositório essencialmente documental nesta leitura (README extenso + pacotes `.zip`), sem árvore de código navegável no conteúdo retornado |
| Contrato no laboratório | **PRONTO** (`integrations/jarvis.py`: `JarvisBridge`, `JarvisSupervisorClient`, `ToolProposalEnvelope` → `POST /api/supervisor/tool-proposals`) |
| Testes | bridge + supervisor cobertos nos 33 testes de integração — **EXECUTADOS OK** |
| Integração real | **NÃO EXECUTADA** — JARVIS continua responsável por memória, ferramentas e autorização |
| Documentação externa | **PENDENTE** (o README precisa ser lido na íntegra antes de commitar docs nele) |
| Regra inviolável | o laboratório **nunca** executa ferramenta: só produz `ToolProposal` e envia ao supervisor; qualquer ferramenta privilegiada (`shell`, `db`, `whatsapp`, `deploy`, ...) é recusada na origem |

## 3. CRM — `maxwellexportador-jpg/solution-hub-ai`

| Aspecto | Situação |
|---|---|
| Arquitetura observada | Node/Express (`app/server.mjs`, `security.mjs`, `db.mjs`), Supabase + Cloudflare Workers, docs em `docs/` |
| Contrato no laboratório | **PRONTO** (`integrations/crm.py`: `CrmAiClient`, `CrmAiTask` → `POST /api/ai/tasks`) com `assert_no_pii()` |
| Testes | tarefa válida, campos PII, padrões CPF/telefone/e-mail e resposta do CRM — **EXECUTADOS OK** |
| Integração real | **NÃO EXECUTADA** — nenhuma chamada a Worker/Supabase de produção |
| Dados proibidos | CPF, e-mail, telefone, endereço, payload de cliente; o laboratório falha fechado ao detectar `cpf`, `email`, `telefone`, `documento`, `endereco` em qualquer nível do JSON |
| Documentação externa | **PENDENTE** (branch própria; nunca alterar `main`) |
| Soberania | o CRM decide o que classificar/assistir; o laboratório não lê o banco nem copia dados para datasets |

## 4. ANDROID — `maxwellexportador-jpg/minha-ia-android`

| Aspecto | Situação |
|---|---|
| Arquitetura observada | Expo/React Native + `server/index.js` |
| Contrato no laboratório | **PRONTO** (`integrations/android.py`: `MobileChatRequest`, `AndroidChatClient`, `build_mobile_request`) |
| Testes | montagem de requisição, limites e cliente HTTP — **EXECUTADOS OK** |
| Integração real | **NÃO EXECUTADA** — app não foi executado nem recompilado |
| Documentação externa | **PENDENTE** |
| Pontos de comunicação identificados | `server/index.js` (proxy do app) → laboratório `POST /v1/chat/completions` com Bearer token; resposta precisa manter `simulated` para o app poder avisar o usuário quando não é modelo real |

## 5. STUDIO 3D — `maxwellexportador-jpg/solution-print-studio-3d`

| Aspecto | Situação |
|---|---|
| Arquitetura observada | repositório praticamente vazio no conteúdo acessível (README de ~65 bytes + `.zip` v20) — arquitetura real não inspecionável |
| Contrato no laboratório | **PRONTO** (`integrations/studio3d.py`: `Studio3DClient`, `Studio3DRequest`, `build_studio_request`) |
| Testes | validação de requisição e metadados de modelo — **EXECUTADOS OK** |
| Integração real | **NÃO EXECUTADA** — sem código-fonte disponível para integração |
| Documentação externa | **PENDENTE** — só faz sentido depois de o `.zip` ser descompactado no repositório |

## Situação de publicação (branches/PRs)

| Repositório | Branch criada | Commit | PR | Observação |
|---|---|---|---|---|
| Solution-hub-lab | `freebuff/b87b49b1c898496c7819ae81` (local) | — | — | worktree do chat sem remote autenticado; publicação pela integração GitHub |
| solution-print-ai-core | não | não | não | requer credencial de escrita; docs redigidos prontos para commit |
| solution-print-jarvis | não | não | não | requer leitura integral do README antes |
| solution-hub-ai | não | não | não | requer credencial; não tocar em produção |
| minha-ia-android | não | não | não | requer credencial |
| solution-print-studio-3d | não | não | não | requer código-fonte (zip) |

**Nenhuma integração externa está concluída.** O que existe é contrato
implementado, testado contra mock e documentado — não chamada real.

## Conteúdo obrigatório dos documentos a commitar em cada repositório

1. o que é o Solution-hub-lab; 2. por que integrar; 3. funcionalidades
disponíveis; 4. como é a comunicação; 5. contratos e interfaces; 6. permissões
necessárias; 7. quais dados podem circular; 8. quais não podem; 9. quem
autoriza; 10. etapas concluídas; 11. etapas pendentes; 12. como testar a
integração; 13. como evitar dependência de um único provedor (o laboratório é
apenas **um** provider: `openai_compatible`, `minimind` e `local` coexistem no
mesmo roteador, e qualquer um pode ser removido sem alterar os clientes).
