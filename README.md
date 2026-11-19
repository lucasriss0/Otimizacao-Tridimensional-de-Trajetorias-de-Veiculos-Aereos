# Planejamento de trajetórias para drone agrícola

O projeto usa relevo do TOPODATA/INPE para comparar nosso A* com uma referência
de faixas paralelas alternadas. O CoppeliaSim executa os voos e registra as
trajetórias para calcular cobertura, segurança e energia estimada.

## Preparar o computador

Use Python 3.13 e CoppeliaSim Edu com o add-on ZeroMQ Remote API habilitado.
Abra o PowerShell na pasta do projeto e instale as dependências uma vez.

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

## Os dois comandos da apresentação

Abra o CoppeliaSim e clique em **Stop (■)** antes de executar um comando.

~~~powershell
.\apresentar.cmd
~~~

Esse comando abre a comparação salva, com nosso A* à esquerda e as faixas
convencionais à direita. Aperte **Play** para reproduzir os registros juntos.
Se faltar uma comparação completa compatível com o cenário, o programa coleta
dois voos em sequência e monta a cena. Durante essa coleta aparece um terreno
por vez.

~~~powershell
.\apresentar.cmd --novo
~~~

Esse comando prepara um terreno e executa **somente nosso A***, com o voo visível.
O programa inicia a simulação automaticamente, cria terreno, obstáculos fixos e
quadricóptero e registra o percurso. A cena aberta é copiada na pasta da execução.

Mantenha o terminal aberto durante o voo. Aguarde o término antes de iniciar outro
comando. Para repetir a apresentação individual, pare a simulação e execute
novamente o segundo comando.

## O que explicar durante a apresentação

### Comparação com vários obstáculos

Com o CoppeliaSim aberto e parado, execute:

~~~powershell
.\apresentar.cmd --objetos
~~~

Esse cenário coloca 12 árvores ao longo das passadas, com raio de segurança
de 35 m, e usa os mesmos obstáculos para ambos os métodos. Os parâmetros estão
em configs/demo_obstacles.yaml. A primeira execução coleta os dois voos em
sequência e abre o replay lado a lado. Aperte Play para reproduzir os registros.
As execuções seguintes abrem uma comparação completa salva desse cenário.

O painel mostra custo normalizado planejado e executado, cobertura e Wh
estimados. O relatório HTML e os CSVs ficam na pasta informada pelo terminal.
O custo normalizado soma distância 3D e peso vezes subida. Os Wh dependem da
trajetória registrada no simulador.

No planejamento inicial desse cenário, ambos atingiram 100% de cobertura.
O custo foi 5.678,44 na referência e 6.301,51 no A*. Esses números descrevem
as rotas planejadas. A energia e a segurança executadas serão avaliadas na coleta.

### Como os métodos funcionam

A referência usa faixas alternadas na direção do maior lado. Conecta pontos por
geometria e Dijkstra em XY quando há exclusões. Nosso A* conecta os alvos numa
grade de oito movimentos e escolhe entre as orientações horizontal e vertical.
Ambos recebem o mesmo terreno, obstáculos, altura, velocidade e controlador.

O custo de busca soma a distância 3D e 0.304 vezes a subida acumulada.
O planejamento é 2,5D. A busca escolhe células no plano horizontal e deriva
a altitude do terreno mais uma margem de segurança.

A comparação visual reproduz os dois voos previamente registrados com o
mesmo relógio. A coleta executa cada método separadamente.

## Cenário e resultados

Os parâmetros da apresentação ficam em configs/demo_coverage.yaml.

| Parâmetro | Valor |
| --- | --- |
| Mapa e grade | 3 × 3 km, 100 × 100 células |
| Janela central de missão | 600 × 600 m |
| Largura e espaçamento das faixas | 120 m e 90 m |
| Velocidade e altura-alvo | 8 m/s e 60 m sobre o relevo |
| Margem mínima e peso de subida | 55 m e 0.304 |
| Vento e obstáculos | Sem vento, obstáculos fixos do YAML |

No par completo registrado no mapa principal, ambos atingiram 100% de cobertura
geométrica.

| Método | Energia estimada | Distância executada | Duração |
| --- | ---: | ---: | ---: |
| Referência geométrica | 289,25 Wh | 5.432,05 m | 692,85 s |
| Nosso A* | 293,48 Wh | 5.537,63 m | 705,10 s |

O A* subiu 18,87 m a menos, percorreu 105,58 m a mais e apresentou energia
estimada 1,46% maior. A coleta está em
output/experiments/custo_vs_convencional_nova_coleta.

O modelo de energia é teórico e ainda exige calibração elétrica para um veículo
definido. A cobertura representa a faixa geométrica percorrida no grid. Dose e
deposição exigem outra avaliação.

O peso 0.304 foi estimado para 4 m/s. A mesma aproximação do modelo a 8 m/s dá
cerca de 0.680. Nos recortes atuais, os pesos testados produziram a mesma rota
A* selecionada.

## Organização do código

| Arquivo ou grupo | Função |
| --- | --- |
| apresentar.cmd | Escolhe comparação ou apresentação individual. |
| benchmark.py | Coordena coleta, relatório e cena de comparação. |
| coverage_comparison.py | Planeja e executa o par ou somente nosso A*. |
| astar.py, coverage.py, conventional.py | Busca A*, passadas e referência geométrica. |
| scenario.py, terrain.py, obstacles.py, waypoints.py | Cenário, relevo, exclusões e coordenadas. |
| coppelia_scene.py, coppelia_terrain.py | Preparação do simulador e do terreno. |
| coppelia_benchmark.py, coppeliasim.py | Execução do controlador e coleta de telemetria. |
| energy.py, metrics.py, telemetry_metrics.py, executed_coverage.py | Energia estimada, geometria, segurança e cobertura. |
| comparison_scene.py, benchmark_report.py | Replay lado a lado e relatório. |
| planning_experiments.py | Estruturas de caso e plano, carregamento do cenário e seleção da orientação A*. |
| wind.py | Estruturas compartilhadas pelo cenário e pelo custo; a apresentação usa vento zero. |
| tests/ | Testes dos componentes mantidos. |

Os utilitários manuais de importação de árvores, voo por CSV, calibração e
demonstração secundária foram retirados dos comandos de entrada do projeto.
Algumas rotinas internas de execução continuam compartilhadas.
As evidências em docs/ registram experimentos anteriores e podem mencionar
comandos retirados. As configurações auxiliares também servem como dados dos testes.

## Saídas e problemas comuns

Cada execução nova cria uma pasta em output/experiments. O voo individual grava
uma pasta coverage_... com protocol.json, comparison.csv e runs/.
O comparativo informa o caminho do relatório e da cena no terminal.
O session.json registra os erros de preparação do replay.

Se a conexão falhar, confira se o CoppeliaSim terminou de abrir, se está parado
e se o add-on ZeroMQ está ativo na porta 23000. Se aparecer um terreno durante
uma coleta do par, aguarde os dois voos terminarem. Depois aperte Play na cena
lado a lado. Após alterar algoritmo, GeoTIFF ou modelo energético, colete um novo
par pelo módulo benchmark antes de usar os números como resultado atualizado.

Para conferir os componentes mantidos após uma alteração, execute
.\.venv\Scripts\python.exe -m pytest tests -q.

O PDF em output/pdf/, quando presente, descreve a revisão anterior à simplificação.
Este README registra o fluxo atual de apresentação.
