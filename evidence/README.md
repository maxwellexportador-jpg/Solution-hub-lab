# Evidências de execução — Solution Print AI Lab

Logs reais produzidos nesta máquina (não são exemplos ilustrativos).
Cada arquivo começa com um cabeçalho fixo:

```
DATA (UTC): ...      data/hora da execução
BRANCH: ...          branch git local
COMMIT: ...          SHA do commit de trabalho
LOTE: ...            lote da matriz de execução
COMANDO: ...         comando exato executado
AMBIENTE: ...        python, sistema, RAM, núcleos
SAIDA (exit): ...    código de saída do processo
```

Regras aplicadas:

- nenhuma chave, token, senha ou dado pessoal aparece nos logs;
- resultados de fixture (`sp-echo-baseline-v1`) estão marcados como SIMULADOS;
- nada aqui prova inferência real de MiniMind: não há checkpoint nem `torch`
  nesta máquina (ver `07_bloqueios.txt`).
