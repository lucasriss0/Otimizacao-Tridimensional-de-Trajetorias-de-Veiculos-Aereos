# Guia das evidências para a defesa

A série de commits foi organizada em 03/11/2026 a partir de alterações já
desenvolvidas e testadas. As datas nos relatórios identificam os experimentos;
a data de um commit não indica quando um voo foi realizado.

## Pergunta e estado da hipótese

Investigamos se o planejamento de trajetória reduz a energia necessária para
concluir a mesma missão, mantendo cobertura e segurança. O veículo modelado é
elétrico. O projeto estima energia em Wh a partir das trajetórias no simulador;
não possui medição de tensão e corrente de uma bateria real.

O planejador é uma busca heurística A* em 2,5D: escolhe células no plano XY,
com altitude derivada do terreno e margem fixa. Não há modelo aprendido ou
treinado. A execução percorre uma trajetória 3D no CoppeliaSim.

## Experimentos que devem ser apresentados separadamente

| Registro | O que sustenta | Limite principal |
| --- | --- | --- |
| [Lote histórico de 28/10](RESULTADOS_20261028.md) | Execução, telemetria e comparação entre variantes de A* | Também havia A* na referência; não demonstra vantagem sobre a referência convencional |
| [Relevo ampliado histórico](RESULTADOS_RELEVO_20261029.md) | Comportamento em relevo original e amplificações sintéticas, com falhas e suplemento preservados | Mesmos recortes amplificados não são fazendas independentes; referência histórica também usava A* |
| [Referência corrigida de 29/10](RESULTADOS_CONVENCIONAL_20261029.md) | 18 voos, nove pares elegíveis; proposta gastou mais nos nove casos, entre 2,46% e 10,46% | Resultado negativo sobre energia estimada nas condições demonstrativas |
| [Protótipo de 30/10](PROTOTIPO_ENERGIA_20261030.md) | No norte 10× conhecido, versão refinada registrou 200,47 Wh, referência 206,80 Wh e A* anterior 211,89 Wh | Redução exploratória de 3,06%; mesma rota obtida por geometria sem A*, sem vantagem isolada do A* |

No protótipo, seis voos foram iniciados: cinco elegíveis e um interrompido
pela suspensão do computador. A tabela principal apresenta a repetição
completa dos três métodos; a tentativa incompleta continua registrada e seu
consumo parcial não conta como economia.

## Onde conferir cada decisão

- [Referência convencional](REFERENCIA_CONVENCIONAL.md): faixas e conexões
  geométricas sem A*, sem afirmar reprodução do algoritmo fechado de fabricante.
- [Comparação das contribuições](COMPARACAO_CONTRIBUICOES.md): separação entre
  orientação, subida e estratégia de conexão; o contraste geométrico versus
  A* 3D não isola somente o efeito da altitude.
- [Benchmark](BENCHMARK_ENERGIA.md): elegibilidade, cobertura, falhas,
  identidade do modelo de energia e exportação dos dados.
- [Sensibilidade energética](SENSIBILIDADE_ENERGIA.md) e
  [resolução temporal](RESOLUCAO_TEMPORAL.md): limites do modelo e do controlador.
- [Cena de comparação](CENA_COMPARACAO.md): a apresentação lado a lado é replay
  das telemetrias; não representa nova coleta física simultânea.
- [Plano de desenvolvimento](PLANO_ENERGIA.md): hipóteses e validações ainda
  necessárias, incluindo terrenos novos e calibração elétrica independente.

Os commits separam preparação dos dados e da cena, referência, execução física,
comparação, relatórios, registros experimentais e protótipo. Para localizar as
mudanças de um componente, use `git log --oneline -- caminho/do/arquivo` e
`git show HASH_DO_COMMIT`.

## Rastreabilidade e arquivos locais

Os relatórios, figuras, CSVs e protocolos exportados estão versionados em
`docs/resultados/`. Os registros incluem resultados negativos, falhas,
critérios de seleção e limitações. Os arquivos históricos são mantidos sem
normalização de finais de linha para preservar os hashes já registrados.

As telemetrias completas, cenas `.ttt`, logs e cópias congeladas da implementação
permanecem em `output/experiments/`, ignorado pelo Git. Um clone do repositório
contém os resultados exportados, mas não esse conjunto bruto completo. Para
auditar integralmente as coletas, é necessário conservar também essas pastas:

- `output/experiments/benchmark_20261028_v2/`;
- `output/experiments/relief_benchmark_20261028_isolated/`, junto aos
  suplementos identificados no relatório histórico;
- `output/experiments/conventional_benchmark_20261029/`;
- `output/experiments/energy_development_20261030/`.

Os protocolos apontam para caminhos e versões usados nas coletas, inclusive
alterações ainda não commitadas naquela data. Os manifestos e snapshots
preservam a identidade desses experimentos; não foram reescritos para indicar
os novos commits de organização.

Para verificar o código atual, sem iniciar voos:

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest -q
```

Passar nos testes verifica o comportamento implementado. A evidência de economia
real de bateria continua dependendo de calibração e validação independentes.
