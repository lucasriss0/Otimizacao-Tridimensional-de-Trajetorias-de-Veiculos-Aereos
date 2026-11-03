# Diagnóstico de resolução temporal

Uma economia pequena pode mudar com a resolução numérica do controle.
`src.time_step_check` repete referência e proposta com passo de 0,025 s,
mantendo os planos geométricos, o modelo energético, o controlador e todos os
critérios. A coleta principal usa 0,05 s. Esse diagnóstico é posterior ao
benchmark e não constitui um novo conjunto independente de validação.

```powershell
python -m src.time_step_check output/experiments/benchmark_01 --output output/experiments/resolution_01
python -m src.time_step_check output/experiments/resolution_01 --analyze-only --output output/experiments/resolution_analysis_01
python -m src.benchmark_report output/experiments/benchmark_01/flights --time-step-check output/experiments/resolution_analysis_01 --output output/experiments/report_with_resolution_01
```

O programa inclui todos os recortes na ordem do manifesto e usa a primeira
repetição com ambas as missões completas por recorte, sem consultar ganhos.
Uma repetição interrompida fica registrada no protocolo; não se substitui o
terreno por outro. O arquivo `time_step_comparison.csv` contém a economia
nos dois passos e sua mudança em pontos percentuais. Rotas que não coincidem
com as originais, cobertura insuficiente ou dados fora do envelope energético
impedem a comparação. Os voos adicionais têm seus próprios logs e não entram
nas médias do benchmark original.

Dois passos permitem verificar sensibilidade; não bastam para estimar uma
ordem formal de convergência ou um intervalo de incerteza. Mesmo resultados
com sinal estável continuam sendo estimativas de trajetórias do simulador.
Calibração elétrica e validação no drone real permanecem necessárias para
afirmações sobre autonomia física.
