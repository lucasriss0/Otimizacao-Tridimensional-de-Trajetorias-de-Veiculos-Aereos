# Energia estimada: modelo de referência v1

Esta implementação avança a etapa B, mas **a calibração para um drone agrícola
e a validação elétrica permanecem pendentes**. Não é medição de bateria.

## Fonte e partes implementadas

O componente de voo horizontal segue as equações (6) e (61) de Yong Zeng,
Jie Xu e Rui Zhang, *Energy Minimization for Wireless Communication with
Rotary-Wing UAV*, [arXiv:1804.02238](https://arxiv.org/abs/1804.02238).
O modelo representa potência de perfil das pás, potência induzida e arrasto
parasita para voo horizontal. A sustentação consome potência mesmo parado.

Os parâmetros aerodinâmicos de `configs/energy_reference.json` usam os valores
da Tabela I: peso de 100 N, raio de rotor de 0,5 m, velocidade de ponta de
200 m/s, densidade de 1,225 kg/m³, solidez 0,05, razão de arrasto 0,3,
coeficiente de perfil 0,012 e correção induzida 0,1. A área do disco e a
velocidade induzida de pairado são calculadas, sem arredondamento da tabela.
Esse é um veículo de referência teórico, não um drone agrícola identificado.
O peso inclui toda a carga e permanece constante; mudar peso não equivale a
modelar esvaziamento de tanque durante pulverização.

As hipóteses adicionais abaixo são **do projeto**, não resultados de validação
do artigo citado:

- potência elétrica horizontal estimada = potência mecânica / eficiência;
- potência adicional de subida = peso × velocidade vertical positiva /
  eficiência de subida;
- potência auxiliar constante configurável;
- nenhuma recuperação de energia na descida. Durante a descida, a parcela
  horizontal/pairado permanece ativa, mas o modelo não descreve aerodinâmica
  axial, vórtices ou potência específica de descida;
- eficiências iniciais de 0,8 e potência auxiliar inicial zero são suposições,
  não valores medidos. O zero não afirma ausência de consumo de aviônicos
  ou de bomba de pulverização: essas cargas ainda precisam de parâmetros.

Essa superposição é uma aproximação exploratória para pequenos deslocamentos
verticais. Não é um modelo aerodinâmico 3D completo, de curvas ou aceleração.

## Integração e unidades

Para cada intervalo entre amostras, o avaliador calcula velocidades a partir
da diferença de posição em metros reais e do tempo simulado em segundos.
A energia é a soma de potência × duração, dividida por 3600 para obter Wh.
As amostras devem ter tempos estritamente crescentes e valores finitos.
Os intervalos são tratados como movimentos de velocidade constante.

O cálculo inclui o período de estabilização se ele constar na telemetria.
Não extrapola antes da primeira amostra ou depois da última. Menos de duas
amostras produz estimativa indisponível, e não consumo zero.
Oscilações e ruído na posição aumentam o ganho de altura observado; não há
filtragem automática. A análise de sensibilidade à amostragem permanece necessária.

Os limites de 60 m/s horizontal e 5 m/s vertical sinalizam intervalos fora do
envelope de referência. O limite horizontal acompanha o máximo do experimento
numérico do artigo; o vertical é um critério exploratório do projeto. Estar
dentro desses limites não comprova validade física. Intervalos fora dos limites
continuam exportados e não devem ser ocultados ao interpretar o resultado.

O estimador não usa forças ou massas do objeto reduzido do CoppeliaSim para
inferir energia do veículo real. A cena 1:100 fornece uma trajetória interpretada
em metros; a resposta dinâmica do modelo reduzido não é uma calibração física.

## Uso

Novas execuções de `python -m src.coverage_comparison` avaliam referência e
proposta com o mesmo modelo e incluem os campos `estimated_energy_wh` e
`energy_calibrated=False` no `comparison.csv`. O planejador continua usando
seu custo de distância/subida: não escolhe rotas com o avaliador energético.

Para analisar um registro existente, sem abrir o simulador:

```powershell
python -m src.energy output/runs/PASTA/telemetry.csv --model configs/energy_reference.json --output output/experiments/energy_01
```

Cada pasta `energy/` contém:

- `energy_model.json`: fonte, parâmetros, hipóteses e indicação de não calibração;
- `energy_summary.json`: energia total e parcelas horizontal, subida e auxiliar;
- `energy_timeseries.csv`: potência, energia acumulada e indicadores de envelope
  por intervalo, quando há dados suficientes.

As pastas precisam ser novas e a telemetria original não é modificada.
O comando `--energy-model` permite definir outro conjunto de parâmetros antes
de iniciar os dois voos. A configuração efetiva também fica no protocolo.

## Evidência necessária para o artigo

Não declarar economia por comparar voos incompletos, com segurança ou cobertura
diferentes. A cobertura executada ainda será implementada. Um voo mais curto
por abandonar alvos não constitui vantagem energética.

Próximos passos: escolher o drone/carga de referência, obter potência elétrica
em pairado, voo horizontal e subida, calibrar os parâmetros em manobras distintas
das missões de teste e avaliar sensibilidade. Com dados de tensão/corrente,
comparar a integral de V × I com a estimativa. Até lá, qualquer redução reportada
é restrita a este modelo exploratório e não comprova economia de bateria real.
