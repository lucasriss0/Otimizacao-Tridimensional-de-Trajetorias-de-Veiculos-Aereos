# Comparação com relevo mais acidentado

A coleta foi concluída. Consulte o [relatório de resultados](RESULTADOS_RELEVO_20261029.md)
para os nove casos previstos, o par suplementar e os limites da conclusão.

O protocolo `configs/relief_suite.json` mantém os três recortes já estudados
e testa fatores verticais de 1×, 5× e 10×. A transformação é
`z_novo = min(z) + fator * (z - min(z))`, mantendo a geometria XY e o datum
mínimo do recorte completo. Apenas 1× representa as altitudes originais.
Os demais níveis são terrenos sintéticos derivados do TOPODATA.

Na área da missão, os desníveis passam de aproximadamente 19,1 para 190,9 m
no centro, 10,3 para 102,5 m no norte e 24,9 para 248,7 m no sul.
Não é uma seleção de novos recortes por ganho energético.

## Condições comuns

Referência e proposta usam os mesmos parâmetros em todos os níveis:

- velocidade de 4 m/s e altura-alvo de 100 m;
- margem mínima de 55 m e passo temporal padrão de 0,05 s;
- largura de aplicação de 120 m e espaçamento de faixas de 90 m;
- mesma origem, retorno, obstáculos, área e controlador físico;
- vento zero e modelo teórico de energia com a mesma identidade;
- cobertura geométrica executada de 100% para aceitar a comparação.

O regime conservador foi fixado antes dos resultados da nova coleta. O
controle 1× é executado novamente nesse regime: não comparar diretamente
os Wh com o experimento anterior a 8 m/s e altura-alvo de 60 m.

O terreno físico inclui quatro células de entorno para executar os desvios
planejados. Isso não aumenta a lavoura exigida na avaliação de cobertura.
Rotas fora desse terreno são recusadas antes de conectar ao simulador.
A regressão geométrica testa os nove casos do manifesto sem iniciar voos.
O lote de 28–29/10 começou com três células: o centro10× foi bloqueado
antes da execução e refeito em um par suplementar, preservando a falha
original e suas médias. A mudança para quatro células corrige o suporte
geométrico para futuras coletas completas; não altera rotas ou energia.
A preparação parte de uma cena limpa, após preservar a cena aberta, para
evitar scripts e condições de tempo herdados da apresentação.

## Executar e gerar o relatório

```powershell
python -m src.benchmark --manifest configs/relief_suite.json --disable-rendering --output output/experiments/relief_study_01
python -m src.relief_report output/experiments/relief_study_01 --output output/experiments/relief_report_01
```

O lote tem nove pares e 18 voos. Uma repetição é usada porque a coleta
anterior era determinística; essas variações não são fazendas independentes.
`src.relief_report` exporta relatório HTML e Markdown, CSV, JSON, curvas de
energia por fator, desníveis em escala vertical comum e tendência por origem.
Pioras, empates, falhas e pares inelegíveis permanecem visíveis.

O painel do replay identifica o fator vertical e o desnível da missão. A
energia é calculada das telemetrias, não do custo do A* ou de uma animação
de bateria. Um relevo maior pode aumentar uma vantagem, causar piora ou
violar condições de segurança; o ganho depende dos resultados registrados.
A limitação anterior do controlador com outro passo temporal permanece
sem solução e impede afirmar validação física geral do consumo.

## Coleta isolada e apresentação

Uma instância iniciada com `coppeliaSim.exe -h -GzmqRemoteApi.rpcPort=23010`
usa o mesmo simulador sem abrir a interface. Informe `--port 23010 --no-scene`
ao coletor nessa configuração. A coleta não consulta parâmetros de exibição
indisponíveis nesse modo. A apresentação é montada depois na instância com
janela, usando `src.comparison_scene` e os logs já registrados.

Preparação e missões compartilham a conexão. A espera por respostas é limitada;
falhas de comunicação não viram voos concluídos. Os lotes interrompidos ficam
em pastas próprias, distintos da coleta final e sem substituição por um
terreno mais favorável.
