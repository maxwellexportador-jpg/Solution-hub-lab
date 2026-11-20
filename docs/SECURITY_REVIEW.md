# Revisão de Segurança — Solution Print AI Lab

Data: 2026-11-19 · Escopo: `solution_print/` e `tests/` (o MiniMind upstream não foi modificado)
Método: leitura de código + 17 testes de segurança executados + varredura de
segredos no repositório (`tests/test_upstream.py`).

## Princípios adotados

1. **Inferência ≠ execução.** O laboratório gera texto e *propostas* de
   ferramentas. Ele não tem caminho de código que execute comando, faça HTTP
   para serviços de cliente, escreva arquivo de negócio ou toque banco.
2. **Negar por padrão.** Provedor, custo, ferramenta, argumento e endpoint
   precisam estar explicitamente autorizados.
3. **Sem segredo em código.** Nenhum token é hardcoded; apenas nomes de
   variáveis de ambiente (`SOLUTION_PRINT_API_TOKEN`,
   `SOLUTION_PRINT_MODEL_API_KEY`, `SOLUTION_PRINT_MINIMIND_CHECKPOINT`).
4. **Falhar fechado.** Check desconhecido de avaliação reprova; resposta
   malformada vira erro tipado; PII detectada aborta a chamada.

## Controles implementados (com teste)

| Controle | Implementação | Teste |
|---|---|---|
| Validação de entrada | `validate_input`: tipo, vazio, 20 000 chars, byte nulo | `tests/test_safety.py` |
| Sanitização de saída | remove ANSI e caracteres de controle, trunca em 64 000, sinaliza injeção de prompt e marcadores `<tool_call>` | idem |
| Detecção/redação de segredos | 9 padrões (OpenAI, GitHub PAT, AWS, Slack, Google, JWT, chave privada, Bearer) — retorna **tipo**, nunca o valor | idem |
| Ferramenta privilegiada | lista de prefixos proibidos (`shell`, `exec`, `system`, `process`, `filesystem`, `file`, `http`, `network`, `database`, `db`, `sql`, `whatsapp`, `meta`, `billing`, `payment`, `deploy`, `cloud`) → `PolicyViolation` | idem |
| Argumentos de ferramenta | limite de bytes, chaves permitidas, marcadores de shell (`$(`, `` ` ``, `&&`, `;`, `>`, `../`) | idem |
| Limite de chamadas | máximo 3 propostas por resposta | idem |
| Custo pago | `RoutingPolicy(allow_paid=True)` levanta `PolicyViolation` no construtor | `tests/test_router.py` |
| Endpoint remoto | bloqueado salvo `SOLUTION_PRINT_ALLOW_REMOTE_MODELS=1`; credenciais na URL recusadas | `tests/test_adapters.py` |
| Vazamento de chave em erro | resposta HTTP de erro é truncada e a API key é substituída por `***` antes de virar mensagem | idem |
| Corpo de requisição | limite de 128 KB e `Content-Length` inválido recusado | `tests/test_api.py` |
| Autenticação da API | Bearer obrigatório fora do loopback; servidor se recusa a subir sem token nesse caso | idem |
| PII no contrato do CRM | `assert_no_pii` em qualquer profundidade (campos e padrões CPF/telefone/e-mail) | `tests/test_integrations.py` |
| Log sem prompt | log do roteador grava digest sha256, nunca o texto do usuário | `tests/test_router.py` |
| Escopo de integração | sem `ai.infer` no grant, a chamada é recusada; o laboratório não cria permissões | `tests/test_integrations.py` |
| Segredos no repositório | varredura de `solution_print/` e `tests/` por 5 padrões → nenhuma ocorrência | `tests/test_upstream.py` |
| Catálogo sem modelo pago | `cost != "free"` reprova o teste de higiene | idem |

## Falhas encontradas e corrigidas nesta execução

| # | Falha | Severidade | Correção |
|---|---|---|---|
| 1 | `MinimindAdapter.infer()` importava `torch` antes de `_load()`, convertendo "sem checkpoint" em `ModuleNotFoundError` (quebra de contrato de erro e de teste de indisponibilidade) | média | `_load()` primeiro; import de `torch` só depois |
| 2 | `JarvisBridge.register_tool_permission()` escrevia em `gateway._permissions` (atributo privado), permitindo contornar a validação | média | `ToolCallGateway.grant()` público, que valida antes de registrar |
| 3 | Regra de validação do catálogo exigia nota de rede em modelos `mock`, invalidando fixture legítima | baixa | exceção explícita para `provider == "mock"` |
| 4 | `.gitignore` sem `*.pth`, `*.gguf`, `*.safetensors`, `.env`, `checkpoints/` — risco de vazar pesos/segredos em commit | **alta** | entradas adicionadas e verificadas por teste |

## Lacunas conhecidas (não corrigidas — declaradas)

| # | Lacuna | Risco | Recomendação |
|---|---|---|---|
| 1 | Comparação de token com `==` (não constante no tempo) | baixo (API local/loopback) | usar `hmac.compare_digest` |
| 2 | Sem rate limiting nem quota por cliente | médio se exposto | limitar no proxy reverso (AI CORE/CRM) antes de expor |
| 3 | Sem TLS próprio | baixo (loopback) | terminar TLS no proxy; nunca expor a 0.0.0.0 sem TLS |
| 4 | Log de acesso em memória (500 entradas, volátil) | baixo | enviar para log estruturado do projeto consumidor |
| 5 | Sem varredura automática de dependências vulneráveis | médio | habilitar `pip-audit`/Dependabot no CI (não há dependência além da stdlib hoje) |
| 6 | `openai_compatible` confia no endpoint configurado pelo operador | baixo | manter allow-list de host e nunca aceitar endpoint vindo de requisição |
| 7 | Sem testes de fuzzing nos parsers | baixo | próxima iteração de L6 |

## Escopo explicitamente fora do laboratório

- não altera IAM, sessões, grants ou permissões de AI CORE/JARVIS/CRM;
- não faz deploy nem escrita em Cloudflare/Supabase;
- não envia mensagens em WhatsApp/Meta;
- não baixa pesos automaticamente nem chama API paga;
- não lê banco do CRM;
- não executa ferramentas propostas por modelo.
