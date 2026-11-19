# Contratos de integração

Contratos para os projetos do ecossistema Solution Print. CRM e JARVIS receberam os documentos
nos próprios repositórios (PR #50 e PR #2). AI CORE, Android e Studio 3D seguem aqui como
contrato de referência porque a publicação nos repositórios de destino não foi possível nesta
execução — ver `evidence/10_publicacao_externa.txt` para o registro exato das tentativas.

- [AI CORE](solution-print-ai-core.md)
- [Android](minha-ia-android.md)
- [Studio 3D](solution-print-studio-3d.md)

Regra comum: endpoint OpenAI-compatible, Bearer fora do loopback, corpo ≤ 128 KB, nenhuma PII de
cliente, nenhuma ferramenta executada pelo laboratório e independência de fornecedor (qualquer
provedor com o mesmo contrato substitui o laboratório).
