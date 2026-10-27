# Cobertura executada e comparação de missões equivalentes

O comparador de voos agora verifica cobertura geométrica a partir das posições
medidas do drone. Os planos e as trajetórias executadas permanecem separados.
Essa implementação fornece ferramentas para a etapa D; os experimentos físicos,
a calibração energética e a generalização estatística continuam pendentes.

## Modelo de aplicação e cobertura

`application_active` é registrado a cada passo da simulação. Durante a
estabilização inicial fica desligado; durante a missão fica ligado, inclusive
nas conexões entre faixas e no retorno. É um estado do modelo geométrico de
aplicação: **não aciona uma bomba nem mede produto depositado**.

O avaliador usa coordenadas locais reais, sem arredondar a posição do drone
para uma célula. Uma célula cultivável é coberta quando seu centro está a até
metade da largura de aplicação de um segmento ativo da trajetória, ou de uma
amostra ativa. Obstáculos e células fora da janela cultivável são excluídos.
O cálculo mantém posições fora do terreno sem prendê-las artificialmente à
borda. Uma passagem repetida não aumenta a área coberta.

Os segmentos são interpolados linearmente e só são contados quando as duas
amostras adjacentes registram aplicação ativa. Não ligamos segmentos através
de períodos de aplicação desligada, transições ou lacunas maiores que 1 s
(valor configurável e salvo no protocolo). Amostras isoladas marcam somente
sua faixa pontual; menos de duas amostras não comprova observação da missão.
Tempos repetidos, não crescentes, valores não finitos e indicadores inválidos
são rejeitados. Telemetria antiga sem `application_active` não recebe um estado
de aplicação presumido: a cobertura fica indisponível na comparação.

A área é o número de centros cobertos vezes a área nominal da célula. Isso
é uma aproximação discreta, não a integral exata da área contínua pulverizada.
A largura é constante: não varia com altitude, inclinação, vento ou vazão.
Violação de altura e colisão desqualificam o voo, mas não mudam retrospectivamente
a máscara geométrica. Não se infere dose, uniformidade nem qualidade agronômica.

## Critério comum antes de calcular economia

Para um voo ser elegível na comparação energética, exigimos:

- conclusão segura registrada pelo executor;
- cobertura executada disponível e pelo menos 100% no modelo discreto;
- nenhuma lacuna de telemetria acima do limite declarado;
- estimativa energética disponível e nenhum intervalo fora do envelope do modelo.

O limiar de cobertura pode ser definido antes do experimento com
`--minimum-executed-coverage`; o limite de lacunas usa `--maximum-telemetry-gap`.
Não diminuir os limites depois de observar resultados para obter economia.
Com limiar menor que 100%, cobertura acima do limiar não significa igualdade
exata de área atendida: reportar as áreas e diferenças entre os métodos.

`energy_contrasts.csv` só informa redução percentual quando referência e
variante são elegíveis. Caso contrário, o valor fica em branco e os motivos
aparecem no relatório. Empates, aumentos de consumo, falhas e voos inseguros
permanecem nos registros. O campo `estimated_energy_wh_per_covered_ha` é uma
medida auxiliar; sozinho não torna um voo incompleto comparável.

O uso da palavra “elegível” é operacional: o modelo de energia permanece não
calibrado e a cobertura não comprova deposição real. Mesmo um par elegível não
comprova economia real de bateria ou eficácia de pulverização.

## Arquivos e execução

Cada voo acrescenta uma pasta `coverage/` com a máscara `coverage_masks.npz`
e o resumo `coverage_summary.json`. `comparison.csv` registra área, porcentagem,
energia por hectare, elegibilidade e motivos de exclusão. `energy_contrasts.csv`
contém as diferenças em relação à referência. Tudo usa a configuração efetiva
registrada em `protocol.json`.

```powershell
python -m src.coverage_comparison --ablation
python -m src.executed_coverage output/runs/PASTA/telemetry.csv --scenario configs/demo_coverage.yaml --output output/experiments/coverage_analysis_01
```

## Lote pré-definido de terrenos e repetições

`configs/validation_suite.json` define três recortes: o centro original e
deslocamentos de 0,02 grau para norte e sul, com mesma longitude. Essa regra
foi definida antes de observar o resultado de energia dos voos desse lote.
São recortes geográficos exploratórios, não propriedades rurais cadastradas,
e os dados centrais já foram usados no desenvolvimento. Não constituem um
conjunto independente suficiente para generalização.

O padrão é de duas repetições por recorte e cinco métodos por repetição:
30 voos. Repetições de um simulador determinístico não são novas amostras de
terreno. A ordem dos métodos é fixa nesta versão; controlar ou alternar a
ordem é necessário antes de tirar conclusões sobre variação temporal.

```powershell
python -m src.validation_suite --dry-run --output output/experiments/suite_check_01
python -m src.validation_suite --output output/experiments/suite_flights_01
```

O primeiro comando valida e exporta planos sem conectar ao simulador; não
produz resultados de voo. O segundo requer CoppeliaSim aberto e parado e
recria a cena para cada tentativa, preservando a cena anterior. Cada par de
local/repetição tem sua própria pasta. `all_flights.csv` reúne as linhas de
voos registrados e `attempts.json` registra tentativas, inclusive falhas de
preparação. Uma falha não é substituída por outro terreno.

Essas ferramentas não substituem a coleta, análise de sensibilidade aos
parâmetros e amostragem, nem a calibração elétrica descrita no plano energético.
