# Ajuste parcial e validação elétrica do estimador

A ferramenta `src.energy_calibration` ajusta os dois fatores de eficiência e
a potência auxiliar, mantendo a aerodinâmica, geometria e peso definidos no
modelo-base. Ainda não existem medições reais de um drone deste projeto no
repositório. Testes com valores sintéticos verificam a implementação, não a
física. Esta entrega não conclui a calibração científica do artigo.

## Dados necessários

Use `configs/electrical_measurements_template.csv`, que contém somente o
cabeçalho. Cada linha deve representar um intervalo observado de manobra
estável, com velocidade e medições elétricas sincronizadas:

| Coluna | Significado |
| --- | --- |
| flight_id | Identificador do voo de coleta |
| split | `train` para ajuste ou `validation` para avaliação separada |
| duration_s | Duração positiva do intervalo em segundos |
| horizontal_speed_mps | Velocidade horizontal em m/s, não negativa |
| vertical_speed_mps | Velocidade vertical em m/s, positiva na subida |
| voltage_v | Tensão elétrica no intervalo, em volts |
| current_a | Corrente de descarga positiva, em ampères |

A potência observada é V × I e a energia observada é a soma de V × I × duração.
Para sinais variáveis, use intervalos pequenos com leituras sincronizadas:
produto de tensão média e corrente média não equivale em geral à média de V × I.
Não sobreponha intervalos, não repita registros e não use consumo fabricado a
partir do próprio estimador como se fosse medição de bateria.

O modelo-base precisa corresponder ao peso total e à configuração do veículo
identificado (carga, rotores e condições da coleta). Não usar os parâmetros
teóricos de 100 N para declarar calibração de outro drone. Se não houver
veículo, carga e dados reais conhecidos, declarar o exercício como sintético.

## Protocolo antes de observar resultados

1. Definir veículo, carga e parâmetros do modelo-base.
2. Selecionar manobras independentes das missões agrícolas de avaliação:
   pairado, voo horizontal em diferentes velocidades e subidas.
3. Separar voos inteiros de ajuste e validação. Um `flight_id` não pode
   aparecer nos dois conjuntos. A ferramenta verifica os identificadores,
   mas não consegue detectar o mesmo voo renomeado ou dados sem origem.
4. Fixar antecipadamente o limite aceitável de erro de potência. O padrão
   exploratório é MAPE de 10%; não é um padrão de certificação ou precisão
   comprovadamente adequada para o artigo.
5. Não retocar o modelo ou limiar após consultar a validação e continuar
   chamando esse mesmo conjunto de validação independente. Se necessário,
   ajustar no desenvolvimento e coletar novos voos reservados.

## Ajuste e limites

O modelo ajustado é P = a × P_horizontal + b × peso × max(vz, 0) + c,
com a,b >= 1 e c >= 0. As eficiências são 1/a e 1/b. O ajuste minimiza o
erro quadrático de potência ponderado pela duração de cada intervalo.
Ele enumera as faces do problema de três coeficientes e não precisa de SciPy.

São necessários pelo menos três registros independentes de treino, mas isso
é apenas o mínimo algébrico, não evidência estatística suficiente. Matrizes
sem posto completo ou fortemente mal condicionadas são rejeitadas. Pairado
sozinho não identifica separadamente todas as parcelas.

Descidas não são aceitas no ajuste de subida. O candidato só passa no critério
automático se a validação permanecer dentro da faixa horizontal e vertical
do treino e atender ao MAPE global e ao MAPE de cada voo reservado. Isso não
valida manobras fora do conjunto, como curvas, acelerações e descidas. Se a
missão posterior sair dessas faixas, o avaliador sinaliza os intervalos e o
comparador de missões não apresenta redução percentual como comparável.

## Execução

```powershell
python -m src.energy_calibration caminho/medicoes.csv --base-model configs/energy_reference.json --vehicle-id IDENTIFICADOR_DO_DRONE --data-kind measured --maximum-validation-mape 10 --output output/experiments/calibration_01
```

Para um exercício ou teste gerado por equações, use obrigatoriamente
`--data-kind synthetic`. O exemplo de comando não fornece medições reais.

A saída deve ser uma pasta nova e contém:

- `candidate_model.json`: parâmetros ajustados, origem dos dados, veículo,
  voos reservados, faixas observadas e resultado do critério de validação;
- `validation_report.json`: MAE, RMSE e MAPE ponderados por duração, energia
  observada e estimada; inclui o modelo-base na mesma validação;
- `flight_validation.csv`: métricas separadas por voo;
- `predictions.csv`: potência prevista e erro em cada intervalo;
- cópias exatas dos arquivos de entrada e hashes para rastreabilidade.

O candidato reprovado é preservado para inspeção, mas `load_energy_model`
recusa seu uso na comparação. O candidato aprovado pode ser escolhido com:

```powershell
python -m src.coverage_comparison --energy-model output/experiments/calibration_01/candidate_model.json
```

A procedência do ajuste é preservada no protocolo e nos arquivos de energia.
`energy_parameter_fit_available` indica apenas que existem parâmetros ajustados;
`energy_calibrated` permanece `False`, mesmo quando o critério automático passa.
Um ajuste parcial não comprova calibração física completa ou economia de bateria.
A descrição `measured` é uma declaração da origem pelo responsável pela coleta,
não uma verificação independente de que os valores vieram de um sensor real.

## O que falta para concluir

Coletar dados reais sincronizados e documentar veículo/carga, verificar erros
de instrumentação, analisar a sensibilidade aos parâmetros e ao período de
amostragem, ampliar o modelo se a validação de manobras exigir e validar em
missões independentes. A demonstração em escala 1:100 do CoppeliaSim não fornece
automaticamente medições elétricas equivalentes a um drone agrícola real.
