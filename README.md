# Planejamento inteligente de trajetórias para drone agrícola em relevo 3D

## Visão geral

O projeto utiliza dados de elevação TOPODATA/INPE para representar uma fazenda como um grid. Uma cobertura boustrophedon gera faixas de aplicação alternadas, e o algoritmo A* conecta os pontos da missão considerando distância tridimensional, ganho de altitude e regiões bloqueadas. A rota resultante é convertida em waypoints `(x, y, z)` e executada no CoppeliaSim pela ZeroMQ Remote API.

A contribuição avaliada é busca heurística com penalização de subida e seleção
da orientação das faixas. O projeto ainda não contém um modelo aprendido ou
treinado. A referência atual gera faixas paralelas e conexões geométricas,
sem A*. O A* fica nas variantes da proposta. Consulte a
[definição da referência convencional](docs/REFERENCIA_CONVENCIONAL.md).
Os lotes anteriores comparavam variantes de A* e são históricos; não
demonstram vantagem sobre o padrão operacional de drones comerciais.

```text
GeoTIFF TOPODATA
       ↓
Recorte da fazenda e grid de elevação
       ↓
Cobertura boustrophedon
       ↓
A* com custo de distância, subida e obstáculos
       ↓
Waypoints tridimensionais
       ↓
Heightfield e drone no CoppeliaSim
       ↓
Métricas, CSV e imagens
```

> **Precisão do modelo:** o planejador atual é 2,5D. O A* busca células no plano
> horizontal e cada waypoint recebe a altitude do MDE mais uma margem de segurança.
> O drone executa uma trajetória 3D, mas o algoritmo ainda não escolhe camadas
> verticais independentes.

## Início rápido: comparação sem vento

### Comparar o recorte original com a Serra da Mantiqueira

O cenário principal usa um mapa de 3 × 3 km com grade de 100 × 100
células e janela central de missão de 600 × 600 m. O manifesto
`configs/terrain_comparison.json` compara a referência geométrica e o A*
no recorte original e em Itatiaia, com a mesma geometria de missão e o mesmo
peso de subida (0,304). O GeoTIFF de Itatiaia é um recorte da folha
[22S45 de altimetria do TOPODATA/INPE](https://www.dsr.inpe.br/topodata/data/geotiff/22S45_ZN.zip),
com elevações originais e coordenadas WGS 84.

```powershell
python -m src.benchmark --manifest configs/terrain_comparison.json --dry-run
```

Para coletar os quatro voos, execute o mesmo comando sem `--dry-run`
com o CoppeliaSim aberto e parado. Durante a coleta, a cena exibe o terreno
do voo em execução. Para cada local com os dois voos completos, o benchmark
salva uma cena de replay com referência e A* lado a lado. Os caminhos
aparecem no terminal e em `scenes_by_location` no `session.json`. Para
alternar entre os locais, pare a simulação e abra a cena correspondente
no CoppeliaSim.

O [benchmark corrigido de 29/10/2026](docs/RESULTADOS_CONVENCIONAL_20261029.md)
usa referência geométrica de faixas paralelas **sem A***. Foram executados
18 voos, com 100% de cobertura e nove pares elegíveis. A proposta A* gastou
mais energia estimada nos nove pares, entre 2,46% e 10,46%. A hipótese de
economia não foi confirmada neste lote. Consulte o
[relatório HTML](docs/resultados/convencional_20261029/relatorio.html).

O [protótipo energético de 30/10/2026](docs/PROTOTIPO_ENERGIA_20261030.md)
acrescenta seleção por Wh previstos e refinamento geométrico das conexões,
ativados por `--energy-planning`. No teste de desenvolvimento norte 10×,
os três voos completos registraram 206,80 Wh na referência, 211,89 Wh no
A* anterior e 200,47 Wh na nova seleção: redução estimada de 3,06% frente
à referência, com 100% de cobertura. Uma tentativa interrompida por suspensão
do computador permanece registrada. A mesma rota nova pode ser construída
por geometria sem A*: o teste não isola vantagem do A* nem comprova economia
elétrica de bateria. O lote anterior de nove pares negativos foi preservado.

O [benchmark histórico de 28/10/2026](docs/RESULTADOS_20261028.md) registra
as 30 tentativas, os empates, a pequena economia estimada observada no norte
e a falha do controlador no diagnóstico com passo temporal menor. Esses
resultados ainda não comprovam economia física de bateria.

O [comparativo com relevo ampliado](docs/RELEVO_AMPLIADO.md) testa 1×, 5× e
10× nos mesmos recortes, incluindo desníveis de até 249 m. As versões ampliadas
são sintéticas. Para coletar os nove pares e gerar o relatório comparativo:

```powershell
python -m src.benchmark --manifest configs/relief_suite.json --disable-rendering --output output/experiments/relevo_01
```

O relatório específico fica em `relief_report/index.html`, com gráficos,
CSV e Markdown. A apresentação seleciona o maior nível com os dois voos
completos, pela ordem do manifesto, incluindo qualquer resultado de energia.

O [resultado histórico de 28–29/10/2026](docs/RESULTADOS_RELEVO_20261029.md) registra
16 voos no lote principal e dois no suplemento do centro10×. No norte10×,
a proposta reduziu a energia estimada em 2,68%; no centro5× aumentou em
4,57% e no centro10× suplementar aumentou em 3,92%. O sul empatou em todos
os níveis. A conclusão depende do recorte e não comprova economia real de
bateria. O [relatório HTML com tabelas e gráficos](docs/resultados/relevo_20261029/relatorio.html)
inclui a tentativa bloqueada e o reparo do suporte físico.
Esses dois lotes históricos usavam A* também na referência e não representam
o novo comparativo com a referência convencional.

### Apresentar no Windows

Com o ambiente `.venv` instalado, abra o CoppeliaSim e deixe a simulação
parada. No PowerShell, execute na raiz do projeto:

```powershell
.\apresentar.cmd
```

Esse é o comando da comparação padrão. Se já houver um replay completo
do cenário atual, ele abre a cena salva diretamente. Para coletar novos
voos, rode `.\apresentar.cmd --novo`. Na primeira coleta, o CoppeliaSim
mostra um terreno por vez até gerar o replay. O comando prepara
terreno, árvore e drone e executa dois voos: referência geométrica de
faixas paralelas sem A* e proposta A* com penalização de subida e escolha da orientação.
Ambos saem e retornam à mesma origem, com a mesma velocidade, altura e
controlador. Vento, deriva artificial e replanejamento ficam desativados.
A cena aberta é copiada antes da preparação para a pasta da comparação.
Ao terminar, o programa gera um relatório HTML e abre a cena lado a lado,
com o A* à esquerda e as faixas convencionais à direita. Aperte **Play**
para reproduzir as trajetórias registradas, com
relógio comum e Wh estimados acumulados. Essa cena é um replay; os voos que
alimentam o benchmark são executados separadamente com o mesmo controlador.

Para executar o benchmark completo, use **`benchmark.cmd`**: três recortes
geográficos, duas repetições e cinco variantes, totalizando 30 voos. A ordem
dos métodos gira entre os pares. O recorte central é de desenvolvimento;
norte e sul são validações exploratórias da mesma região. Os resultados,
falhas e pares inelegíveis ficam no relatório, sem seleção por ganho.
Para a cena visual, o orquestrador usa o primeiro par em ordem de coleta com
as duas missões completas. Essa regra verifica disponibilidade para o replay;
a elegibilidade energética é reavaliada separadamente. O caminho escolhido e
a regra ficam em `session.json`, e as tentativas anteriores continuam no relatório.

Também é possível iniciar pelo ambiente Python:

```powershell
.venv/Scripts/python.exe -m src.benchmark --scenario configs/demo_coverage.yaml
.venv/Scripts/python.exe -m src.benchmark --disable-rendering
```

Durante cada voo, a rota aparece em laranja. A mesma cena é recarregada antes
do segundo voo. O cenário principal é `configs/demo_coverage.yaml`.
O fluxo conecta as rotas comparadas à dinâmica do simulador e registra a trajetória
efetivamente executada. Também exporta energia estimada em Wh pelo modelo
teórico de referência, usando os mesmos parâmetros nos dois voos. Essa
estimativa ainda não foi calibrada para um drone agrícola nem mede bateria real.
Consulte [o modelo e suas limitações](docs/MODELO_ENERGIA.md).
O executor padrão do benchmark mantém a física e o controlador do Quadcopter,
controlando o alvo e coletando amostras com um script Lua dentro do CoppeliaSim
para reduzir consultas remotas. Python orquestra a coleta e calcula os resultados.
`--disable-rendering` acelera a coleta e restaura a exibição;
a apresentação final volta a mostrar os dois terrenos. O executor anterior
continua disponível com `--executor python`.

A largura geométrica de aplicação permanece 120 m e o espaçamento das faixas
é 90 m em ambos os métodos, oferecendo sobreposição para o rastreamento.
O critério de comparação continua sendo 100% de cobertura geométrica executada,
sem colisões, violações de altura ou extrapolação do modelo energético.
Consulte [benchmark e relatório](docs/BENCHMARK_ENERGIA.md),
[cena lado a lado](docs/CENA_COMPARACAO.md) e
[sensibilidade energética](docs/SENSIBILIDADE_ENERGIA.md).

O ajuste parcial por medições de tensão/corrente está disponível em
`python -m src.energy_calibration --help`. Ele separa voos de treino e
validação, mantém a origem dos dados e recusa candidatos reprovados.
Consulte [calibração energética](docs/CALIBRACAO_ENERGIA.md) e o cabeçalho
`configs/electrical_measurements_template.csv`. Ainda não há medições reais
do drone do projeto; o modelo não deve ser declarado calibrado.

A cena de voo, a apresentação e os resultados ficam em uma pasta nova de
`output/experiments/benchmark_.../`. `flights/` contém os voos,
`report/index.html` apresenta os resultados e `presentation/comparacao_lado_a_lado.ttt`
permite reabrir o replay. `planned_*.csv` contém os planos em metros;
`comparison.csv` contém os resultados lado a lado, inclusive falhas;
`protocol.json` registra os parâmetros e as duas rotas; `runs/` preserva
telemetria e trajetória registrada de cada voo. A cobertura planejada e a cobertura
geométrica executada são registradas separadamente; nenhuma mede deposição real.
Uma redução de energia só é calculada em `energy_contrasts.csv` quando ambos
os voos concluem com segurança e cumprem o mesmo limiar de cobertura executada.
Consulte [validação da missão](docs/VALIDACAO_MISSAO.md) para o modelo de faixa,
os critérios, as limitações e o lote pré-definido de terrenos e repetições.
O método proposto combina subida e orientação; esta comparação inicial não
isola a contribuição individual de cada melhoria.

Para validar os planos sem abrir o CoppeliaSim:

```powershell
python -m src.coverage_comparison --dry-run --output output/experiments/coverage_check_01
```

Para coletar os voos, execute `src.benchmark` ou remova `--dry-run` do comando
do comparador, sempre com uma pasta nova e a simulação parada.
Durante a coleta, mantenha o programa Python aberto até a exportação dos dados.
A cena final de
replay já contém as trajetórias e pode ser apresentada só com o botão Play.
No comparador `src.coverage_comparison`, a opção `--scene caminho/para/cena.ttt`
usa uma cena já preparada e compatível com o cenário.

### Mostrar a comparação na interface do CoppeliaSim

1. Aguarde a coleta terminar. A cena de comparação será carregada no simulador.
   Para reabri-la depois, use o menu **File** e abra
   `presentation/comparacao_lado_a_lado.ttt` da pasta do benchmark.
2. Clique em **Play** na barra do simulador. O terreno à esquerda mostra a
   proposta em laranja. O da direita mostra a referência em azul. A trilha
   branca acompanha as posições registradas. O painel informa que é um replay.
3. Compare os Wh estimados acumulados e a cobertura final. Os relógios usam
   segundos originais; o drone que termina antes fica parado com o Wh final.
   Ao terminar os dois voos, o replay pausa e mantém o quadro para apresentação.
4. Para começar novamente, clique em **Stop** e depois em **Play**. O arquivo
   contém os dados e o Lua da reprodução, dispensando o processo Python.
5. Apresente também `report/index.html`: ele contém todos os pares previstos,
   falhas e aumentos de consumo. O painel só calcula a redução final quando
   ambos os voos do replay são elegíveis.

A demonstração antiga com vento continua disponível via
`python -m src.presentation`, como experimento secundário.

Para separar as contribuições de cada melhoria, execute as cinco variantes
com `python -m src.coverage_comparison --ablation`. A análise preliminar sem
simulador usa `python -m src.ablation --scenario configs/demo_coverage.yaml --output output/experiments/ablation_01`.
Consulte [comparação das contribuições](docs/COMPARACAO_CONTRIBUICOES.md) para
distinguir energia de uma trajetória ideal das métricas de voo executado.

Se a área 3D ficar preta mesmo numa cena nova: no AMD Software, crie um perfil
para o executável `coppeliaSim.exe`, selecione **Graphics Profile: Default**
somente nesse perfil e reinicie o simulador. Essa combinação corrigiu a
visualização no computador de teste com Radeon RX 560X; não é uma garantia
para outros drivers. A seleção da GPU de alto desempenho é independente do
perfil gráfico. Confirme a GPU na linha `OpenGL ... Renderer` do log.

### Preparação manual da demonstração secundária com vento

Na raiz do projeto, crie e ative o ambiente Python:

```bash
python3 -m virtualenv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Com o CoppeliaSim aberto e a simulação parada, prepare e salve a cena:

```bash
python -m src.coppelia_scene \
  --scenario configs/demo_wind.yaml \
  --save scenes/drone_agricola_wind.ttt
```

Se a cena já existir e você quiser recriá-la, acrescente `--overwrite`. Depois,
execute a missão determinística:

```bash
python -m src.coppeliasim \
  --scenario configs/demo_wind.yaml \
  --speed 8 \
  --scale 0.01
```

Nesse comando, `--speed 8` significa **8 m/s reais**; a conversão para unidades da
cena é automática. O vento começa aos 10 s; aos 30 s e 70 s simulados ele muda,
o A* recalcula a missão
restante e a execução registra telemetria em `output/runs/`.

O cenário usa altitude-alvo de 60 m sobre o MDE e registra violação caso a margem
real medida fique abaixo de 55 m.

Para comparar os casos sem vento, vento fixo e vento variável:

```bash
python -m src.experiments --scenario configs/demo_wind.yaml
```

O resultado é salvo em `output/experiments/wind_comparison.csv`. O custo com vento
é um indicador normalizado, não uma medição em joules.

## Funcionalidades implementadas

- Leitura de arquivos GeoTIFF TOPODATA;
- Recorte de uma área real por latitude, longitude e tamanho em metros;
- Redução do terreno para um grid configurável;
- A* com oito movimentos, incluindo diagonais;
- Distância 3D e penalização por ganho de altitude;
- Bloqueio de diagonais que atravessariam cantos de obstáculos;
- Cobertura boustrophedon em faixas alternadas;
- Cálculo da porcentagem de área cultivável coberta;
- Conversão da rota para waypoints tridimensionais;
- Altura de segurança sobre o relevo;
- Geração automática de heightfield no CoppeliaSim;
- Leitura automática de obstáculos da cena;
- Desvio de árvores e outros obstáculos estáticos;
- Controle do target do quadricóptero em modo sincronizado;
- Executor local em Lua para missões sem vento, mantendo a dinâmica do Quadcopter;
- Cenários determinísticos de vento e replanejamento durante o voo;
- Perturbação visual limitada aplicada ao corpo dinâmico;
- Telemetria de posição, erro, margem, colisão e eventos de replanejamento;
- Exportação de métricas, waypoints e visualizações;
- Benchmark de cinco variantes, energia estimada, cobertura executada e relatório pareado;
- Replay autocontido das telemetrias em uma cena com dois terrenos lado a lado;
- Testes automatizados com pytest.

## Tecnologias

- Python 3;
- NumPy;
- Rasterio;
- Matplotlib;
- pytest;
- CoppeliaSim;
- ZeroMQ Remote API.

## Estrutura principal

```text
Projeto/
├── data/
│   └── raw/
│       └── 22S48_ZN.tif
├── output/
├── src/
│   ├── astar.py
│   ├── benchmark.py
│   ├── benchmark_report.py
│   ├── comparison_scene.py
│   ├── coppelia_benchmark.py
│   ├── coppelia_terrain.py
│   ├── coppeliasim.py
│   ├── coverage.py
│   ├── coverage_comparison.py
│   ├── energy.py
│   ├── executed_coverage.py
│   ├── main.py
│   ├── metrics.py
│   ├── obstacles.py
│   ├── sync_obstacles.py
│   ├── terrain.py
│   ├── validation_suite.py
│   ├── visualization.py
│   └── waypoints.py
├── tests/
├── COPPELIASIM_SETUP.md
├── requirements.txt
└── README.md
```

## Instalação no Windows

Abra o PowerShell na pasta do projeto:

```powershell
cd ...\Projeto
```

Crie o ambiente virtual:

```powershell
python -m venv .venv
```

Ative o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Se o PowerShell impedir a ativação, execute uma vez na janela atual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Executar os testes

### Experimento de planejamento para o artigo

A primeira etapa experimental roda sem CoppeliaSim e sem vento. Consulte
[o protocolo](docs/PLANNING_EXPERIMENTS.md) para as hipóteses, comparações,
critérios e limitações. Com o ambiente ativado:

```powershell
python -m src.planning_experiments --scenario configs/demo_wind.yaml --output output/experiments/planning_01
```

O comando avalia seis casos sintéticos fixos e o recorte real do cenário,
preservando candidatos, falhas, métricas, rotas, gráficos e dados de entrada.
A pasta de saída precisa ser nova para preservar execuções anteriores.

### Etapa 2: métricas do voo executado

As missões com cenário (`python -m src.coppeliasim --scenario ...`) agora
acrescentam ao `metrics.csv` a distância 3D, subida, descida, custo normalizado,
erro médio/RMSE/máximo, menor margem ao terreno e duração observada das
colisões e violações de altura. `mission_completed` indica conclusão dos alvos;
`mission_completed_safely` exige também telemetria presente, ausência de erro,
colisões e violações. O campo antigo `success` foi preservado.

Para resumir uma telemetria antiga sem conectar ao simulador:

```powershell
python -m src.telemetry_metrics output/runs/PASTA_DA_MISSAO/telemetry.csv --climb-weight 0.304
```

O resumo considera apenas o intervalo da primeira à última amostra, incluindo
estabilização registrada. A duração de cada violação usa o estado da amostra
anterior até a próxima; uma violação na última amostra conta como ocorrência,
mas não recebe duração adicional. Médias e RMSE são calculados por amostra.
A distância soma segmentos retos entre posições medidas. O custo normalizado
não representa joules. Ausência de telemetria não comprova segurança.
As margens usam a medição já registrada pelo simulador; esta etapa não calibra
a física, não mede cobertura executada e não atesta segurança entre amostras.

### Etapa 3: mesmo vento, com e sem replanejamento

Com o CoppeliaSim aberto e parado, use uma cena salva que corresponda ao
cenário (terreno, drone e obstáculos). O comando abaixo **recarrega essa cena
antes de cada um dos dois voos**, descartando alterações não salvas na cena
aberta. A rota inicial, o vento e o controlador são iguais; apenas a decisão
de replanejar muda. A deriva artificial comandada do target é desativada nos
dois casos; a força aproximada sobre o drone permanece ativa.

Primeiro valide o protocolo sem conectar ao simulador, usando uma pasta nova:

```powershell
python -m src.wind_comparison --scenario configs/demo_wind.yaml --scene scenes/drone_agricola_wind.ttt --output output/experiments/wind_check_01 --dry-run
```

Para executar os dois voos e salvar as métricas lado a lado:

```powershell
python -m src.wind_comparison --scenario configs/demo_wind.yaml --scene scenes/drone_agricola_wind.ttt --output output/experiments/wind_pair_01
```

`comparison.csv` reúne os resultados, inclusive missões que falharam.
`protocol.json` registra a configuração e a rota inicial comum. Cada voo
preserva telemetria, eventos e métricas em `runs/`; a configuração efetivamente
usada fica em `effective_configuration.json`. Os eventos incluem tempo de
cálculo do replanejamento (tempo de processamento real, não tempo simulado).
O CSV do primeiro voo é preservado se a segunda execução não puder iniciar.
O modo `--dry-run` só produz o protocolo, sem resultados de voo.

Compare conclusão segura, distância, subida, erro de acompanhamento, margem
mínima e duração das violações. Redução de custo em uma missão incompleta não
representa vantagem. Esta comparação não mede cobertura executada nem bateria,
e a força continua sendo uma aproximação sem calibração aerodinâmica. Antes
de interpretar resultados físicos, confirme que o corpo dinâmico foi encontrado
e recebe a força: o mecanismo existente tolera falhas na aplicação da força.
Um par de voos é uma verificação inicial, não evidência de generalização.

Para uma execução individual pelo comando antigo, acrescente `--no-replan`
ao `python -m src.coppeliasim --scenario ...`. Esse comando mantém os efeitos
do YAML original, incluindo a deriva artificial quando configurada. Use o
comparador acima para o protocolo pareado sem essa deriva.

### Rodar os testes

```powershell
python -m pytest -v
```

Os testes cobrem planejamento, conversões, telemetria, critérios de comparação,
energia estimada, coleta e replay. Avisos `PendingDeprecationWarning` emitidos
pelo Rasterio não representam falha.

## Dados utilizados

O exemplo utiliza o arquivo:

```text
data\raw\22S48_ZN.tif
```

Coordenadas centrais usadas para a região de Engenheiro Coelho:

```text
Latitude:  -22.48196
Longitude: -47.26397
```

O sinal deve ser negativo porque as coordenadas estão nos hemisférios Sul e Oeste.

## Planejamento básico entre dois pontos

Sem `--coverage`, o programa compara uma rota de menor distância com uma rota que penaliza subida:

```powershell
python -m src.main `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 `
  --size 50 `
  --climb-weight 0.304 `
  --start-row 5 `
  --start-col 5 `
  --goal-row 44 `
  --goal-col 44
```

Os quatro parâmetros de origem e destino precisam ser informados juntos. Se forem omitidos, o programa utiliza os centros das bordas esquerda e direita.

## Gerar uma missão de cobertura

```powershell
python -m src.main `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 `
  --size 50 `
  --climb-weight 0.304 `
  --coverage `
  --swath-m 120 `
  --clearance-m 60
```

Parâmetros importantes:

- `--area-m`: lado da área quadrada recortada;
- `--size`: quantidade de linhas e colunas do grid;
- `--climb-weight`: peso aplicado ao ganho de altitude, com padrão `0.304`;
- `--swath-m`: largura de aplicação ou pulverização;
- `--clearance-m`: altura do target acima do terreno.

A altura padrão é 60 m. Ela considera o tamanho físico do drone, oscilações e atraso do controlador nas subidas.

## Preparar a cena do CoppeliaSim

1. Abra uma cena nova;
2. Insira o modelo oficial `Quadcopter` pelo Model browser;
3. Não altere o script controlador do modelo;
4. Antes da simulação, mantenha o target original dentro do modelo com alias `target`;
5. Quando a simulação iniciar, o script do modelo moverá o target para a raiz da cena;
6. Deixe habilitado o ZeroMQ Remote API add-on, normalmente na porta `23000`;
7. Salve a cena como um arquivo `.ttt`.

Antes da execução, a hierarquia deve ser semelhante a:

```text
Quadcopter
├── Script
├── propeller[0]
├── propeller[1]
├── propeller[2]
├── propeller[3]
└── target
```

## Criar automaticamente o relevo no CoppeliaSim

Com o CoppeliaSim aberto e a simulação parada, valide primeiro:

```powershell
python -m src.coppelia_terrain `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 `
  --size 50 `
  --scale 0.01 `
  --dry-run
```

Para criar o objeto real na cena, remova `--dry-run`:

```powershell
python -m src.coppelia_terrain `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 `
  --size 50 `
  --scale 0.01
```

Será criado o objeto:

```text
/AgriculturalTerrain
```

Uma nova execução substitui apenas o terreno anterior com esse alias. Remova ou oculte o `Floor` padrão e salve a cena depois da criação.

## Escala da simulação

O valor utilizado é:

```text
scale = 0.01
```

Assim:

```text
100 metros reais = 1 unidade na cena
1.500 metros reais = 15 unidades na cena
60 metros de altura = 0,60 unidade na cena
```

O terreno, os obstáculos e os waypoints devem sempre utilizar a mesma escala.

## Obstáculos informados manualmente

A sintaxe é:

```text
--obstacle "NOME,X_M,Y_M,RAIO_M"
```

Exemplo:

```powershell
python -m src.main `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 `
  --size 50 `
  --climb-weight 0.304 `
  --coverage `
  --swath-m 120 `
  --clearance-m 60 `
  --obstacle "arvore1,0,135,75"
```

Vários obstáculos podem ser informados:

```powershell
--obstacle "arvore1,120,-90,45" `
--obstacle "arvore2,-200,180,60"
```

As coordenadas são relativas ao centro da fazenda e expressas em metros reais.

## Ler árvores automaticamente do CoppeliaSim

Renomeie o objeto principal de cada árvore usando aliases iniciados por `Obstacle`:

```text
ObstacleTree1
ObstacleTree2
ObstaclePost1
```

Com a cena aberta e a simulação parada, execute:

```powershell
python -m src.sync_obstacles `
  --prefix Obstacle `
  --scale 0.01 `
  --margin-m 30 `
  --default-radius-m 15
```

O programa lê automaticamente:

- Alias do objeto;
- Posição `x` e `y`;
- Dimensões da caixa envolvente;
- Raio físico;
- Margem adicional de segurança.

O arquivo gerado será:

```text
output\obstacles_coppelia.json
```

Recalcule a cobertura usando esse arquivo:

```powershell
python -m src.main `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 `
  --size 50 `
  --climb-weight 0.304 `
  --coverage `
  --swath-m 120 `
  --clearance-m 60 `
  --obstacles-file "output\obstacles_coppelia.json"
```

Sempre repita a sincronização e o planejamento depois de mover, adicionar ou redimensionar uma árvore.

## Validar os waypoints

Este comando lê e valida os waypoints sem abrir uma simulação:

```powershell
python -m src.coppeliasim --dry-run
```

## Executar o voo

Com a cena aberta e a simulação parada:

```powershell
python -m src.coppeliasim `
  --object /target `
  --csv "output\waypoints_coppeliasim.csv" `
  --scale 0.01 `
  --speed 2 `
  --warmup-s 5
```

O programa:

1. Conecta-se ao CoppeliaSim;
2. Ativa o modo sincronizado;
3. Inicia a simulação;
4. Aguarda cinco segundos para estabilização;
5. Lê a posição atual do target;
6. Aproxima-o gradualmente do primeiro waypoint;
7. Percorre a rota completa;
8. Para a simulação ao final ou em caso de erro.

Comece com `--speed 2`, agora expresso em metros reais por segundo. Com `--scale 0.01`, o programa converte automaticamente esse valor para `0.02` unidade da cena por segundo.

## Fluxo manual para uma missão individual

Com o ambiente virtual ativado e o CoppeliaSim aberto:

```powershell
# 1. Criar ou atualizar o terreno
python -m src.coppelia_terrain `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 --size 50 --scale 0.01

# 2. Ler as árvores da cena
python -m src.sync_obstacles `
  --prefix Obstacle --scale 0.01 --margin-m 30

# 3. Recalcular a cobertura e os waypoints
python -m src.main `
  --topodata "data\raw\22S48_ZN.tif" `
  --center-lat -22.48196 `
  --center-lon -47.26397 `
  --area-m 1500 --size 50 --climb-weight 0.304 `
  --coverage --swath-m 120 --clearance-m 60 `
  --obstacles-file "output\obstacles_coppelia.json"

# 4. Validar o arquivo gerado
python -m src.coppeliasim --dry-run

# 5. Executar o voo
python -m src.coppeliasim `
  --object auto --scale 0.01 --speed 2 --warmup-s 5
```

Se a cena não possuir objetos com prefixo `Obstacle`, pule a etapa 2 e remova `--obstacles-file` da etapa 3.

## Arquivos gerados

```text
output\topodata_cobertura_boustrophedon.png
output\topodata_menor_distancia.png
output\topodata_subida_penalizada.png
output\metricas_cobertura.csv
output\metricas_rotas.csv
output\waypoints_coppeliasim.csv
output\obstacles_coppelia.json
```

O arquivo de waypoints contém:

```text
sequence,grid_row,grid_column,x_m,y_m,z_m,terrain_z_m,altitude_asl_m
```

## Métricas calculadas

- Distância horizontal;
- Distância tridimensional;
- Ganho de elevação;
- Perda de elevação;
- Inclinação máxima;
- Custo auxiliar de distância e subida;
- Tempo de planejamento;
- Nós expandidos;
- Quantidade de pontos da rota;
- Porcentagem de cobertura.

O custo auxiliar usado pelo planejador é:

```text
custo = distância 3D + peso de subida × ganho de elevação
```

Ele não representa energia em joules ou Wh. O benchmark calcula os Wh
separadamente, usando potência e tempo sobre a telemetria executada, conforme
[MODELO_ENERGIA.md](docs/MODELO_ENERGIA.md).

## Padronizações e melhorias desta versão

O cenário principal reproduzível é `configs/demo_coverage.yaml`, usado no
benchmark sem vento. `configs/demo_wind.yaml` mantém o experimento secundário
de perturbação e replanejamento. Cada YAML define terreno, recorte cultivável,
velocidade, altura de segurança e obstáculos; o cenário complementar também
define eventos de vento. A cena, o planejador e a execução usam as mesmas
coordenadas e unidades.

As principais padronizações foram:

- coordenadas geográficas apenas na importação do TOPODATA e coordenadas locais
  em metros durante o planejamento;
- conversão única de metros para unidades da cena por `simulation.scale`;
- `speed_mps`, componentes do vento e raios de segurança sempre expressos em
  unidades reais;
- nomes estáveis para `/Drone`, `/AgriculturalTerrain` e obstáculos declarados
  no YAML;
- descoberta automática do target e do corpo dinâmico do quadricóptero;
- execução iniciada com a simulação parada, por script local Lua no benchmark
  ou por passos remotos no executor Python;
- resultados isolados em pastas novas de `output/`, preservando todas as
  tentativas, protocolos, telemetrias e parâmetros.

As melhorias funcionais incluem:

- criação automática e salvamento de uma cena reproduzível;
- relevo real recortado para a área do experimento e visualização por altitude;
- cobertura boustrophedon conectada por A* com custo de relevo e vento;
- eventos de vento em qualquer instante, inclusive sem evento em `t=0`;
- deriva lateral visual limitada antes do replanejamento;
- replanejamento a partir da posição efetiva do drone após cada mudança de
  vento;
- árvore central criada na cena e convertida na mesma máscara de ocupação usada
  pelo A*;
- preservação dos alvos já concluídos durante o replanejamento;
- telemetria, eventos, métricas, trajetória executada e revisões da rota;
- timeouts, verificação de altura mínima e detecção de colisão;
- testes automatizados de planejamento, vento, obstáculos, conversões e
  integração.

O vento físico e a deriva são aproximações controladas para demonstrar a
decisão do planejador. Eles não constituem um modelo aerodinâmico calibrado.

## Problemas comuns

### `ModuleNotFoundError: No module named 'src'`

Execute os comandos a partir da raiz do projeto e use:

```powershell
python -m pytest -v
```

### Cliente ZeroMQ ausente

```powershell
python -m pip install coppeliasim-zmqremoteapi-client==2.0.4
```

### Não foi possível conectar ao CoppeliaSim

- Confirme que o CoppeliaSim está aberto;
- Confirme que a cena terminou de carregar;
- Use a porta padrão `23000`;
- Verifique se o ZeroMQ Remote API add-on está ativo.

### Objeto `/target` não encontrado

- Use o modelo oficial `Quadcopter`;
- Mantenha o target original dentro do modelo antes da simulação;
- Não renomeie o target;
- Prefira `--object auto`; o programa localiza o target antes de o script do modelo
  desacoplá-lo ao iniciar.

### Drone dispara ou perde o target

- Restaure a cena;
- Use `--speed 2` (m/s reais);
- Use `--warmup-s 5`;
- Confirme que o modelo consegue flutuar sem o programa Python;
- Não altere o script original do quadricóptero.

### Drone colide com o terreno

- Gere novamente a cobertura com `--clearance-m 60` ou valor maior;
- Reduza a velocidade;
- Confirme que terreno e waypoints usam a mesma escala;
- Não reutilize um CSV antigo gerado com altura menor.

### Árvore não foi encontrada

- O alias deve começar exatamente com `Obstacle`;
- Selecione o objeto principal da árvore, não apenas uma folha ou textura;
- Pare a simulação antes da sincronização;
- Confira se o objeto está presente na árvore da cena.

## Limitações atuais

- Obstáculos são considerados estáticos;
- O vento é uniforme em cada intervalo e definido previamente no YAML;
- A força aplicada ao drone é uma perturbação visual, não um modelo aerodinâmico calibrado;
- O custo do planejador é auxiliar; os Wh vêm de um modelo teórico sem validação elétrica;
- O controlador do quadricóptero é o controlador demonstrativo do CoppeliaSim;
- A área cultivável é atualmente representada por um recorte quadrado;
- O planejador é 2,5D e não escolhe níveis verticais independentes.

## Próximas melhorias

- Gerar gráficos de altitude e erro ao longo do tempo;
- Permitir polígonos reais de propriedade rural;
- Realizar replanejamento diante de obstáculos móveis;
- Calibrar vento e consumo com parâmetros físicos ou telemetria real;
- Adicionar plantação sintética e visão para identificar falhas, pragas e áreas não pulverizadas;
- Comparar diferentes pesos de subida e configurações experimentais.

## Referências

- [TOPODATA — INPE](http://www.dsr.inpe.br/topodata/)
- [CoppeliaSim](https://www.coppeliarobotics.com/)
- [ZeroMQ Remote API](https://manual.coppeliarobotics.com/en/zmqRemoteApiOverview.htm)
- [sim.createHeightfieldShape](https://manual.coppeliarobotics.com/en/sim/simCreateHeightfieldShape.htm)
- [Survey indicado como base do projeto](https://pmc.ncbi.nlm.nih.gov/articles/PMC11314818/)

## Estado atual

O projeto integra dado geográfico, planejamento, execução com dinâmica no
CoppeliaSim, telemetria, cobertura geométrica, energia estimada e benchmark
pareado. A cena de apresentação reproduz as duas telemetrias lado a lado.
Os resultados devem ser interpretados junto com falhas, critérios de cobertura
e análise de sensibilidade. Medições elétricas e validação para um veículo e
carga definidos continuam necessárias para sustentar uma conclusão sobre
economia real de bateria.
