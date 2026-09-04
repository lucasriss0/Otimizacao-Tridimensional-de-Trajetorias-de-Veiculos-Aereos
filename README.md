# Planejamento inteligente de trajetórias para drone agrícola em relevo 3D

Projeto prático da disciplina de Inteligência Artificial I. O sistema planeja uma missão de cobertura agrícola sobre um terreno real, considera relevo e obstáculos estáticos e envia a trajetória calculada para um drone simulado no CoppeliaSim.

## Visão geral

O projeto utiliza dados de elevação TOPODATA/INPE para representar uma fazenda como um grid. Uma cobertura boustrophedon gera faixas de aplicação alternadas, e o algoritmo A* conecta os pontos da missão considerando distância tridimensional, ganho de altitude e regiões bloqueadas. A rota resultante é convertida em waypoints `(x, y, z)` e executada no CoppeliaSim pela ZeroMQ Remote API.

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
- Exportação de métricas, waypoints e visualizações;
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
│   ├── coppelia_terrain.py
│   ├── coppeliasim.py
│   ├── coverage.py
│   ├── main.py
│   ├── metrics.py
│   ├── obstacles.py
│   ├── sync_obstacles.py
│   ├── terrain.py
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
cd C:\Users\lucas.risso\repositorios\IA\Projeto
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

```powershell
python -m pytest -v
```

O projeto possui atualmente 47 testes automatizados. Avisos `PendingDeprecationWarning` emitidos pelo Rasterio não representam falha.

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
  --climb-weight 10 `
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
  --climb-weight 10 `
  --coverage `
  --swath-m 120 `
  --clearance-m 60
```

Parâmetros importantes:

- `--area-m`: lado da área quadrada recortada;
- `--size`: quantidade de linhas e colunas do grid;
- `--climb-weight`: peso aplicado ao ganho de altitude;
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
  --climb-weight 10 `
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
  --climb-weight 10 `
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
  --speed 0.02 `
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

Comece com `--speed 0.02`. Se o drone acompanhar com estabilidade, experimente `0.03` e depois `0.05`. Não use `2` com o controlador demonstrativo do quadricóptero.

## Fluxo completo recomendado

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
  --area-m 1500 --size 50 --climb-weight 10 `
  --coverage --swath-m 120 --clearance-m 60 `
  --obstacles-file "output\obstacles_coppelia.json"

# 4. Validar o arquivo gerado
python -m src.coppeliasim --dry-run

# 5. Executar o voo
python -m src.coppeliasim `
  --object /target --scale 0.01 --speed 0.02 --warmup-s 5
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
- Custo energético normalizado;
- Tempo de planejamento;
- Nós expandidos;
- Quantidade de pontos da rota;
- Porcentagem de cobertura.

O custo energético é uma estimativa normalizada:

```text
custo = distância 3D + peso de subida × ganho de elevação
```

Ele não representa uma medição física em joules ou quilojoules.

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
- Execute o voo com `--object /target`, pois o script o desacopla ao iniciar.

### Drone dispara ou perde o target

- Restaure a cena;
- Use `--speed 0.02`;
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
- Não há replanejamento durante o voo;
- Vento não é simulado no planejador;
- O custo energético é normalizado;
- O controlador do quadricóptero é o controlador demonstrativo do CoppeliaSim;
- A área cultivável é atualmente representada por um recorte quadrado;
- Ainda não existe telemetria completa da trajetória real do drone.

## Próximas melhorias

- Registrar posição planejada e posição real durante o voo;
- Medir erro médio e máximo de acompanhamento;
- Detectar colisões e violações de altura mínima;
- Interromper a missão em situações inseguras;
- Gerar gráficos de altitude e erro ao longo do tempo;
- Permitir polígonos reais de propriedade rural;
- Realizar replanejamento diante de obstáculos móveis;
- Comparar diferentes pesos de subida e configurações experimentais.

## Referências

- [TOPODATA — INPE](http://www.dsr.inpe.br/topodata/)
- [CoppeliaSim](https://www.coppeliarobotics.com/)
- [ZeroMQ Remote API](https://manual.coppeliarobotics.com/en/zmqRemoteApiOverview.htm)
- [sim.createHeightfieldShape](https://manual.coppeliarobotics.com/en/sim/simCreateHeightfieldShape.htm)
- [Survey indicado como base do projeto](https://pmc.ncbi.nlm.nih.gov/articles/PMC11314818/)

## Estado atual

O protótipo funcional já realiza o fluxo principal desde o dado geográfico até a simulação. O próximo passo recomendado é implementar telemetria do drone para comparar a trajetória planejada com a trajetória efetivamente executada.
