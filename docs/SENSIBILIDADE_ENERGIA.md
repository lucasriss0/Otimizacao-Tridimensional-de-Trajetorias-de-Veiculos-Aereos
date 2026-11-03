# Sensibilidade das hipóteses energéticas

Esta análise reestima a energia das mesmas telemetrias usadas pelo benchmark.
Ela verifica se o sinal e a magnitude da redução estimada dependem de algumas
hipóteses teóricas. Os planos e os voos registrados permanecem fixos; não há
novo voo, seleção de rota, ajuste aos resultados nem medição elétrica.

## Executar após a coleta

```powershell
python -m src.energy_sensitivity output/experiments/benchmark_01 --output output/experiments/sensitivity_01
```

A entrada pode ser a pasta do relatório ou seu `benchmark.json`. A saída deve
ser nova. Somente pares marcados como comparáveis no relatório são analisados.
Pares inelegíveis ficam identificados como excluídos, sem redução inventada.
Telemetria ausente, inválida, com menos de duas amostras, ou com velocidades
fora dos limites horizontais de 60 m/s e verticais de 5 m/s, exclui todo o par.
O programa também exige conclusão segura e cobertura suficiente registradas
no relatório. A análise não refaz a avaliação agronômica nem a simulação.

## Grade fixa de 18 hipóteses

A grade é definida em `src/energy_sensitivity.py` antes de ler qualquer
resultado. A referência é o `EnergyModel()` teórico do projeto, com peso de
100 N, eficiência elétrica de 0,8 e potência auxiliar de 0 W.

| Parâmetro | Valores usados |
| --- | --- |
| Peso | 80, 100 e 120 N: fatores 0,8, 1 e 1,2 |
| Eficiência elétrica | 0,64, 0,80 e 0,96: fatores 0,8, 1 e 1,2 |
| Potência auxiliar | 0 e 100 W |
| Eficiência de subida | 0,8 em toda a grade |

O produto cartesiano tem 18 configurações. Os demais parâmetros e os limites
de velocidade são os mesmos da referência teórica. Cada configuração é
aplicada igualmente à referência e à proposta. A grade não aumenta limites
para aceitar trajetórias que excederam o envelope. As eficiências permanecem
em `(0, 1]`.

Um modelo ajustado anteriormente no benchmark fica registrado como origem,
mas seus parâmetros e sua calibração não são propagados para a grade. O
varrimento é explicitamente teórico e não representa 18 drones calibrados.
Alterar o peso na fórmula sobre um voo fixo não simula a mudança de controle,
dinâmica ou trajetória que outra massa poderia produzir em um drone real.

## Resumos e sinais

Para cada configuração e par, calcula-se
`100 * (Wh_referencia - Wh_proposta) / Wh_referencia`.
Valores positivos favorecem a proposta; valores negativos indicam aumento.
Primeiro calcula-se a média das repetições elegíveis de cada recorte. Depois
atribui-se o mesmo peso a cada recorte. Repetições não se tornam novos
terrenos independentes. Não há teste de significância ou intervalo de
confiança de generalização.

O resumo informa quantas configurações produziram redução, aumento, empate
ou ausência de resultado, além dos valores mínimo e máximo da média por
recorte. O total original de pares, o total comparável, os efetivamente
analisados e os excluídos permanecem visíveis. Não se transformam exclusões
em economia nula nem se removem configurações desfavoráveis.

## Arquivos

- `sensitivity_configuration.json`: os 18 modelos explícitos, grade fixa,
  modelo original do benchmark, política de calibração e hash da implementação.
- `sensitivity_summary.json`: resumo, configurações, exclusões, caminhos e
  SHA-256 das telemetrias lidas e do benchmark de entrada.
- `pair_sensitivity.csv`: energias e reduções de cada par e configuração.
- `case_sensitivity.csv`: médias das repetições por recorte.
- `configuration_sensitivity.csv`: resumo com pesos iguais por recorte.
- `energy_sensitivity.png` e `.svg`: figura exportável das 18 configurações.

`real_battery_saving_proven` e `energy_calibrated` permanecem `false`.
Um sinal positivo em toda a grade demonstra estabilidade apenas dentro
destas hipóteses e nestas trajetórias. Comprovar economia física de bateria
exige dados elétricos e validação independentes do drone estudado, conforme
[CALIBRACAO_ENERGIA.md](CALIBRACAO_ENERGIA.md).
