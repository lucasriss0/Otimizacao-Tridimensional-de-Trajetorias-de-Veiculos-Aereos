# Benchmark de energia de trajetórias executadas

O relatório compara a referência com a proposta em pares do mesmo recorte
geográfico e da mesma repetição. A energia vem das posições registradas durante
os voos do simulador e do modelo energético declarado. O relatório não recebe tensão
e corrente de uma bateria e não comprova economia física de bateria.

A referência atual é `parallel_geometric_v1`, com faixas paralelas e
desvios geométricos, sem A*. Consulte `REFERENCIA_CONVENCIONAL.md`.
A chave `referencia_2d` foi mantida nos CSVs; os protocolos dos lotes
anteriores a essa revisão usavam A* também na referência e não devem ser
misturados aos novos resultados.

## Executar o fluxo completo

Abra o CoppeliaSim e deixe a simulação parada. No Windows, `apresentar.cmd`
executa um par com a referência e a proposta, gera o relatório e prepara a cena
de replay lado a lado. `benchmark.cmd` executa a grade completa de
`configs/validation_suite.json`: **três recortes × duas repetições × cinco
métodos = 30 voos**. Ao terminar, abra o relatório e aperte **Play** na cena
preparada para apresentar os dois voos do primeiro par com ambas as missões
completas em ordem de coleta. A seleção consulta disponibilidade dos dados;
não se procura o par com maior economia.

O orquestrador também pode ser chamado diretamente, sempre com pasta nova:

```powershell
.venv/Scripts/python.exe -m src.benchmark --output output/experiments/benchmark_completo_01
.venv/Scripts/python.exe -m src.benchmark --scenario configs/demo_coverage.yaml --output output/experiments/benchmark_par_01
```

Use `--dry-run` para validar os planos e registrar a configuração sem conectar
ao simulador. Essa opção não gera voos nem resultados energéticos observados.
`--no-scene` executa o benchmark sem montar a cena de apresentação. O arquivo
`session.json` conserva o estado da execução, os caminhos dos resultados e
eventuais erros; `implementation/` preserva uma cópia dos códigos e configurações
usados, inclusive alterações que ainda não tenham sido commitadas.

Os cinco métodos são `referencia_2d`, `distancia_3d`, `somente_subida`,
`somente_orientacao` e `proposta_completa`. A ordem usa a rotação cíclica
pré-definida `balanced_rotation` entre os pares, registrada em `attempts.json`
e no protocolo de cada par. Com seis pares e cinco métodos, essa rotação não
constitui contrabalanceamento completo. Os recortes são o centro de estudo e
deslocamentos fixos de 0,02 grau para norte e sul, definidos antes de observar
os resultados do lote. O centro é cenário de desenvolvimento; norte e sul são
validação exploratória. As repetições verificam a execução no mesmo recorte.

O protocolo registra também o ajuste de desenvolvimento do espaçamento entre
faixas após um piloto com cobertura incompleta. A largura geométrica e o
espaçamento de faixas são parâmetros diferentes e idênticos entre métodos no
mesmo par. Os pilotos e seus resultados permanecem disponíveis; um ajuste de
desenvolvimento não transforma o cenário central em validação independente.

## Gerar o relatório

Após executar o lote, use uma pasta de saída nova:

```powershell
.venv/Scripts/python.exe -m src.benchmark_report output/experiments/suite_flights_01 --output output/experiments/benchmark_01
```

Para o comparador de dois métodos, que usa outro nome para a proposta:

```powershell
.venv/Scripts/python.exe -m src.benchmark_report output/experiments/coverage_01 --proposed proposta_subida_orientacao --output output/experiments/benchmark_pair_01
```

Também é possível fornecer diretamente `all_flights.csv` ou `comparison.csv`.
O programa não conecta ao simulador nem altera os resultados originais. Abra
`index.html` no navegador para apresentar. Os gráficos PNG e SVG de energia
podem ser usados em apresentações; o gráfico de trajetórias usa a telemetria
original dos primeiros seis pares que têm arquivos disponíveis, identificados
na figura. Todos os pares entram no resumo e na tabela, independentemente da
amostra visual.

## O que é calculado

Para um par elegível, a redução estimada é
`100 * (Wh_referencia - Wh_proposta) / Wh_referencia`.
Um resultado negativo indica aumento de energia. Empates permanecem no
relatório. Só se calcula redução quando os dois voos têm conclusão segura,
cobertura observada suficiente, ausência de lacunas, energia válida e nenhum
intervalo fora do envelope energético, além da elegibilidade explícita do
comparador. As áreas cultiváveis precisam ser conhecidas, positivas e iguais.
O relatório recusa modelos energéticos com nomes diferentes e exige também
o mesmo `energy_model_sha256` em ambos os voos. Esse SHA-256 identifica o
manifesto energético serializado pelo executor, incluindo os parâmetros; nomes
iguais não autorizam comparar parametrizações diferentes. A identidade também
fica registrada no protocolo. Hash ausente deixa o par inelegível, inclusive
em logs antigos; o relatório não inventa uma identidade retroativa.

A igualdade de cenário, carga e controlador deve ser garantida pelo executor
e registrada no protocolo; o relatório não refaz os voos. A igualdade dos
hashes verifica a identidade do modelo usado e não demonstra sua validade para
uma bateria física. A cena de replay aplica a mesma reauditoria do relatório.

O limiar de cobertura vem do protocolo ou manifesto; sem esse registro, usa
100%. As áreas e coberturas de cada método ficam visíveis na tabela. Se um
experimento admitir cobertura menor, superar o limiar não demonstra igualdade
exata de área atendida. Não alterar critérios depois de observar resultados.

O relatório preserva a lista de recortes e repetições prevista em
`manifest.json` e as falhas em `attempts.json`. Tentativas não iniciadas,
falhas antes da conexão e pares com apenas um voo ficam no denominador de
pares previstos. Caso o comparador falhe após salvar parte dos voos, o
relatório recupera o `comparison.csv` parcial mesmo que ele ainda não tenha
sido acrescentado a `all_flights.csv`. Um método duplicado no mesmo par é
rejeitado: o programa não escolhe a execução mais favorável.

Os resumos distinguem três ponderações:

- média das reduções percentuais dos pares elegíveis;
- média por terreno: primeiro calcula a média das repetições elegíveis de
  cada recorte, depois atribui o mesmo peso a cada recorte;
- redução na soma dos Wh dos pares elegíveis, que dá mais peso a missões
  com maior energia de referência.

Nenhuma dessas médias inclui uma redução inventada para falhas ou dados
ausentes. A quantidade de pares elegíveis, a quantidade total e a quantidade
de aumentos de consumo acompanham todas as conclusões. Repetições no mesmo
terreno não aumentam a quantidade de terrenos independentes. Não são
calculados valores-p nem intervalos de confiança de generalização para os
recortes exploratórios e determinísticos deste projeto.

## Arquivos para auditoria

- `benchmark.json`: resumos, cada par, motivos de exclusão, modelo registrado
  e SHA-256 dos arquivos de origem; cada voo mantém `energy_model_sha256`.
- `pairs.csv`: tabela pareada, com redução em branco quando inelegível.
- `all_recorded_flights.csv`: todos os métodos recebidos, inclusive outras
  variantes da ablação e voos inelegíveis.
- `energy_comparison.png` e `.svg`: Wh estimados e redução de cada par.
- `trajectory_comparison.png`: trajetórias observadas quando disponíveis.
- `index.html`: relatório local, sem dependências de rede.

Os campos `real_battery_saving_proven` permanecem `false`, mesmo que exista
um ajuste parcial de parâmetros energéticos. A ferramenta de ajuste e a
coleta elétrica descritas em [CALIBRACAO_ENERGIA.md](CALIBRACAO_ENERGIA.md)
continuam necessárias para aproximar a estimativa do drone estudado.
Cobertura geométrica também não mede deposição ou eficácia agronômica.

## Coleta física com menos chamadas remotas

O comparador oferece `--executor lua`. O módulo `src.coppelia_benchmark`
instala temporariamente um script Lua que comanda os mesmos waypoints no
target do Quadcopter. O controlador original e a física continuam ativos;
o corpo do drone recebe pose inicial somente com a simulação parada.
Durante o voo, a trajetória é medida em `sysCall_sensing`, após cada passo
físico. O horário da amostra representa o fim desse intervalo físico.

A interpolação de velocidade 3D, estabilização, tolerância e limites de tempo
seguem a mesma política do executor Python. O script considera todas as
shapes do drone, o terreno e todas as shapes dos obstáculos. Falha de leitura,
colisão indisponível, dinâmica desligada, blocos ausentes, tempo inválido e
divergência dos contadores invalidam a execução. Os dados são transmitidos
em blocos CBOR de até 128 amostras, preservando os números de precisão dupla.
O Python recebe progresso e blocos, em vez de consultar cada objeto a cada
passo. O modelo energético continua sendo aplicado à trajetória observada.

`--disable-rendering` pode acelerar a coleta física ao suspender a exibição
durante cada voo. A exibição é restaurada ao final, inclusive em erros.
O arquivo `effective_configuration.json` registra o executor, presença de
física, convenção de tempo, tempo de relógio e SHA-256 do script, que também
é salvo em `executor.lua`. O protocolo do comparador identifica o executor
para permitir reproduzir e auditar o experimento. Comparações devem usar o
mesmo executor nos dois métodos.
