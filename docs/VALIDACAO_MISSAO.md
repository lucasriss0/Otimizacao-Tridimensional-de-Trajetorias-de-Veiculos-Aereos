# Cobertura executada e comparação de missões equivalentes

O comparador de voos agora verifica cobertura geométrica a partir das posições
medidas do drone. Os planos e as trajetórias executadas permanecem separados.
Essa implementação fornece ferramentas para a etapa D. A coleta no simulador
e os relatórios são registrados por execução; implementar o coletor não
confirma que o lote terminou ou que apresentou economia. Calibração elétrica
do drone real e generalização estatística exigem validação adicional.

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

No protocolo `2_overlap90`, a largura geométrica de aplicação continua sendo
120 m (`swath_m`) e o espaçamento de planejamento entre faixas é de 90 m
(`stripe_spacing_m`) para todos os métodos. Isso introduz 30 m de sobreposição
nominal, ou 25% da largura. Espaçamento e largura são parâmetros distintos.
O espaçamento anterior de 120 m deixou 98,86% de cobertura executada no piloto
da referência. A revisão para 90 m ocorreu antes de consultar a economia do
par e foi aplicada igualmente aos métodos, mantendo a exigência de 100%.
O piloto anterior e o lote revisado pertencem a versões diferentes do
protocolo; seus resultados não devem ser misturados como repetições iguais.

## Critério comum antes de calcular economia

Para um voo ser elegível na comparação energética, exigimos:

- conclusão segura registrada pelo executor;
- cobertura executada disponível e pelo menos 100% no modelo discreto;
- nenhuma lacuna de telemetria acima do limite declarado;
- estimativa energética disponível e nenhum intervalo fora do envelope do modelo.

O benchmark também exige monitoramento de colisão do conjunto de shapes do
drone contra o terreno e os obstáculos. Ausência desse monitoramento ou erro
de leitura invalida a conclusão segura.

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
e os dados centrais já foram usados no desenvolvimento e no piloto. O centro
é identificado como recorte de desenvolvimento. Norte e sul são avaliações
exploratórias adicionais, sem seleção por economia observada; não constituem
um conjunto independente suficiente para generalização. A proximidade
geográfica e a mesma fonte de relevo também limitam a diversidade do teste.

O padrão é de duas repetições por recorte e cinco métodos por repetição:
30 voos. Repetições de um simulador determinístico não são novas amostras de
terreno. A ordem é uma rotação cíclica determinística dos cinco métodos,
registrada em `method_order` de cada tentativa. Há seis blocos de
recorte/repetição: os cinco primeiros cobrem os cinco deslocamentos da ordem,
e o sexto repete o deslocamento inicial. Portanto essa rotação não é um
balanceamento completo de posições nem de efeitos de sequência; também não
é uma randomização. Não atribuir pequenas diferenças a efeitos temporais
resolvidos por esse desenho.

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

O relatório mantém os seis pares previstos entre referência e proposta no
denominador, além de registrar as demais variantes. Pares ausentes,
incompletos, inseguros ou com cobertura insuficiente não entram na média de
economia, mas permanecem nas tabelas e nos totais. Resultados negativos e
empates dos pares elegíveis entram na análise. As médias são descritivas;
duas repetições não permitem estimar precisão de generalização para novas
áreas. O primeiro par completo em ordem de coleta pode ilustrar o replay,
sem seleção por ganho; a conclusão numérica usa o conjunto elegível declarado.

`src.benchmark_report` gera os resumos pareados e `src.energy_sensitivity`
reestima as mesmas trajetórias em 18 hipóteses teóricas fixas. Consulte
[BENCHMARK_ENERGIA.md](BENCHMARK_ENERGIA.md) e
[SENSIBILIDADE_ENERGIA.md](SENSIBILIDADE_ENERGIA.md). Essas ferramentas não
substituem a conclusão da coleta, a avaliação de resolução numérica e da
amostragem, nem a calibração elétrica descrita no plano energético.
