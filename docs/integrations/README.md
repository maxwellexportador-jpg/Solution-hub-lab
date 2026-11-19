# Contratos de integração preparados no laboratório

Contratos de integração para os projetos do ecossistema Solution Print. Os documentos de CRM e
JARVIS foram publicados nos próprios repositórios (PRs #50 e #2). Os de AI CORE, Android e
Studio 3D ficam aqui até o proprietário liberar a publicação no repositório de destino; neste
laboratório eles são o mesmo contrato, apenas no invólucro do projeto de origem.

- [AI CORE](solution-print-ai-core.md)
- [Android](minha-ia-android.md)
- [Studio 3D](solution-print-studio-3d.md)

Regra comum aos três: endpoint OpenAI-compatible, Bearer fora do loopback, corpo ≤ 128 KB,
nada de PII de cliente, nenhuma ferramenta executada pelo laboratório, e independência de
fornecedor (qualquer provedor com o mesmo contrato substitui o laboratório).
