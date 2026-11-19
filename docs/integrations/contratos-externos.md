# Contratos externos — AI CORE, Android e Studio 3D

Contrato `1.0` · provider `solution-hub-lab` · estado: **preparação**
Publicação nos repositórios de destino: **não realizada** (HTTP 403 — `evidence/10_publicacao_externa.txt`).

## Regra comum

Endpoint OpenAI-compatible, `Authorization: Bearer <token>` fora do loopback, corpo ≤ 128 KB,
nenhuma PII de cliente, nenhuma ferramenta executada pelo laboratório (só proposta), e
independência de fornecedor: qualquer provedor com o mesmo contrato substitui o laboratório.

## 1. AI CORE (`solution-print-ai-core`)

O AI CORE decide identidade, sessão, grants e auditoria; falta a origem da inferência. O
laboratório entra como provedor registrado, com manifesto e envelope.

| Uso | Endpoint |
|---|---|
| Saúde | `GET /health` |
| Catálogo OpenAI | `GET /v1/models` |
| Inferência OpenAI | `POST /v1/chat/completions` |
| Manifesto de provedor | `GET /api/providers/solution-hub-lab/manifest` |
| Inferência como provedor | `POST /api/providers/solution-hub-lab/infer` |

Envelope: `contract_version`, `tenant` (`tenant_id`, `user_id`, `grant_id`, `scopes`, `request_id`),
`messages`. Resposta: `model_id`, `text`, `usage`, `latency_ms`, `cost`, `simulated`.

- **Permissão:** escopo obrigatório `ai.infer`; o laboratório não cria nem amplia permissão.
- **Dados:** circulam identificadores, mensagens e metadados técnicos; NÃO circulam credenciais,
  tokens de sessão, dados de cliente do CRM, banco de produção, chaves de terceiros.
- **Autorização:** AI CORE (usuário/tenant/grant/escopo), laboratório (modelo), supervisor (ferramenta).
- **Concluído:** contrato, `AiCoreClient`, recusa sem `ai.infer`, testes com servidor falso, CI verde
  (run `44490005099`). **Pendente:** adapter no AI CORE, token como segredo, endpoint publicado,
  teste ponta a ponta com auditoria, política de fallback.
- **Testar:** manifesto com `contract_version: "1.0"`; envelope com `scopes: ["ai.infer"]` responde
  com `simulated`; com `scopes: []` é recusado.

## 2. `minha-ia-android`

O app conversa por HTTP/WebSocket (`server/server.mjs`); o laboratório permite escolher modelo por
tarefa e medir latência antes de prometer qualidade. UI, histórico e sessão continuam no app.

- **Comunicação:** `GET /health`, `GET /v1/models`, `POST /v1/chat/completions`.
- **Permissão:** token de serviço do app em variável de ambiente no servidor — nunca no APK.
- **Dados:** circulam texto da conversa, idioma, `request_id`, modelo, latência, tokens; NÃO circulam
  agenda, contatos, localização, IMEI, telefone, mídia do usuário, credenciais, dados do CRM.
- **Concluído:** contrato e clientes com testes; CI verde. **Pendente:** `LabChatClient` no app,
  endpoint e token no servidor, teste de latência em rede móvel, streaming (esta versão não tem SSE).

## 3. `solution-print-studio-3d`

Usos opcionais, fora do núcleo de modelagem: descrever uma peça a partir de texto; sugerir
parâmetros de impressão como **sugestão revisável**; gerar nome/descrição de catálogo. Nada altera
geometria, malha ou arquivo do usuário sem confirmação.

- **Comunicação:** `POST /v1/chat/completions`.
- **Dados:** circulam descrição textual, dimensões aproximadas, material, `request_id`; NÃO circulam
  `.stl`/`.obj` brutos, malhas, imagens do cliente, dados de pedido do CRM, contato do cliente final.
- **Permissão:** token de serviço do Studio no servidor/CLI; sugestão fica `pending_approval`.
- **Concluído:** contrato `Studio3DRequest` e testes; CI verde. **Pendente:** revisar arquitetura atual
  para escolher o ponto de chamada, painel x CLI, teste com peças reais, versionamento de prompts.
