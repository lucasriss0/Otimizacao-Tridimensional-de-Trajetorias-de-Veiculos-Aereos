# Planejamento de trajetórias para drone agrícola

Este projeto compara duas formas de planejar a cobertura de uma área agrícola:
nosso A*, que considera distância 3D e subida, e uma referência de faixas
paralelas com conexões geométricas. Usamos relevo do TOPODATA/INPE e o
CoppeliaSim para executar os voos e analisar as trajetórias.

## Instalação

Você precisa do Python 3.13 e do CoppeliaSim Edu, com o add-on ZeroMQ Remote API
habilitado na porta 23000. Abra o PowerShell na pasta do projeto e execute:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

## Como executar

Abra o CoppeliaSim e deixe a simulação parada com **Stop (■)**.

| Comando | O que faz |
| --- | --- |
| `.\apresentar.cmd` | Abre a comparação do cenário principal. |
| `.\apresentar.cmd --novo` | Executa somente nosso A* no cenário principal. |
| `.\apresentar.cmd --objetos` | Compara os métodos em um cenário com 12 árvores. |
| `.\apresentar.cmd serra_do_cipo` | Compara os métodos na Serra do Cipó. |
| `.\apresentar.cmd monte_verde` | Compara os métodos em Monte Verde. |
| `.\apresentar.cmd --novo serra_do_cipo` | Executa somente o A* na Serra do Cipó. |
| `.\apresentar.cmd --novo monte_verde` | Executa somente o A* em Monte Verde. |
| `.\apresentar.cmd todos` | Mostra os quatro cenários e suas oito rotas planejadas. |

Os comandos de comparação abrem uma cena salva quando ela está disponível.
Caso contrário, executam os dois voos em sequência e montam a cena ao final.
Durante a coleta aparece um terreno por vez. Aguarde o terminal e aperte
**Play** quando a comparação lado a lado estiver aberta. O A* fica à esquerda,
em laranja, e a referência à direita, em azul.

O comando `--novo` inicia o voo automaticamente. Mantenha o terminal aberto
até ele terminar.

No modo `todos`, aperte **Play** para animar as oito rotas a 8×. A animação
percorre os planos calculados, sem executar o controlador ou coletar telemetria.
As colunas seguem a ordem da legenda, com o A* em laranja na linha superior
e o convencional em azul na linha inferior. Nos replays individuais, o botão
**Métricas dos voos** abre os dados da comparação.

## Como funciona

O programa recorta o mapa de elevação, cria uma grade e marca as células
ocupadas pelos obstáculos. Depois gera passadas em zigue-zague para cobrir
a área e calcula as conexões entre os pontos da missão.

Nosso A* busca caminhos em oito direções e escolhe entre passadas horizontais
e verticais. O custo usado na busca é:

~~~text
custo = distância 3D + 0,304 × subida acumulada
~~~

A referência segue o maior lado da área. Usa conexões retas quando estão livres
e Dijkstra em um grafo de visibilidade para desviar dos obstáculos. Essa é a
referência geométrica que implementamos para o estudo; os resultados se
referem a ela.

Os dois métodos acompanham o relevo com uma margem de altura. A busca é 2,5D:
escolhe as posições horizontais e calcula a altitude a partir do mapa.

## Cenários

Todos usam um mapa de 3 × 3 km, com células de 30 m e uma janela central de
missão de 600 × 600 m. A velocidade é de 8 m/s e a altura-alvo é de 60 m.
As configurações ficam em `configs/`.

| Cenário | Arquivo | Obstáculos | Desnível na janela da missão |
| --- | --- | ---: | ---: |
| Principal | `demo_coverage.yaml` | 1 árvore | 35,64 m |
| Vários obstáculos | `demo_obstacles.yaml` | 12 árvores | 35,64 m |
| Serra do Cipó | `serra_do_cipo.yaml` | 3 árvores | 207,43 m |
| Monte Verde | `monte_verde.yaml` | 3 árvores | 148,91 m |

Nos cenários montanhosos, uma borda amplia o terreno físico para 840 × 840 m.
A janela de missão continua com 600 × 600 m.

## Resultados

Nos dois pares completos executados no CoppeliaSim, ambos os métodos atingiram
100% de cobertura geométrica.

| Cenário | Referência | Nosso A* | Variação da energia estimada |
| --- | ---: | ---: | ---: |
| Principal | 289,25 Wh | 293,48 Wh | +1,46% |
| 12 árvores | 304,09 Wh | 334,76 Wh | +10,09% |

No cenário principal, o A* subiu 18,87 m a menos, mas percorreu 105,58 m a mais.
O aumento da distância e do tempo de voo superou a economia na subida.

Também calculamos a energia prevista para percorrer os quatro planos a
velocidade constante, sem o controlador:

| Cenário | Referência | Nosso A* | Variação prevista |
| --- | ---: | ---: | ---: |
| Principal | 279,22 Wh | 283,58 Wh | +1,56% |
| 12 árvores | 292,83 Wh | 324,80 Wh | +10,92% |
| Serra do Cipó | 320,41 Wh | 311,56 Wh | -2,76% |
| Monte Verde | 303,49 Wh | 318,16 Wh | +4,84% |

Na Serra do Cipó, reduzir a subida compensou o percurso mais longo nessa
previsão. Os dois cenários montanhosos ainda precisam de pares de voo para
confirmar os valores.

A energia vem de um modelo teórico aplicado à trajetória. A cobertura mede
a faixa geométrica percorrida. Medições de bateria, dose e deposição ficam
como etapas futuras.

## Código e arquivos

- `src/astar.py`, `coverage.py` e `conventional.py` calculam as rotas.
- `src/coverage_comparison.py` organiza o planejamento e os voos.
- `src/coppelia_scene.py` e `coppelia_benchmark.py` preparam e executam a cena.
- `src/energy.py`, `telemetry_metrics.py` e `executed_coverage.py` avaliam os voos.
- `src/benchmark.py`, `benchmark_report.py` e `comparison_scene.py` geram a comparação.
- `src/scenario_presentation.py` monta a apresentação dos quatro cenários.

Cada execução cria uma pasta em `output/experiments/`. O terminal informa
os caminhos das cenas e relatórios. Os principais arquivos são `protocol.json`
(configuração e planos), `comparison.csv` (resultados), `telemetry.csv`
(amostras do voo) e `report/index.html` (relatório).

Os estudos anteriores estão em `docs/`. O
[relatório de estudo atualizado](output/pdf/relatorio_atualizado_c85319f.pdf),
quando disponível na cópia local, explica o código e os experimentos em mais
detalhes.

## Testes e problemas comuns

Para rodar os testes:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests -q
~~~

Se a conexão falhar, confira se o CoppeliaSim terminou de abrir, se está parado
e se o add-on ZeroMQ está ativo. Se a cena final não aparecer, veja a mensagem
do terminal e o campo `presentation_error` em `session.json`.

As comparações salvas representam os voos que as geraram. Depois de alterar
o algoritmo, o mapa ou o modelo de energia, gere um novo par para atualizar
os resultados:

~~~powershell
.\.venv\Scripts\python.exe -m src.benchmark --scenario configs/demo_coverage.yaml
~~~

Dados de elevação fornecidos pelo [TOPODATA/INPE](https://data.inpe.br/dados/topodata/).
