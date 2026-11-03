# Plano do artigo: eficiência energética da missão agrícola

Este plano substitui a prioridade anterior de demonstração de vento.

## Pergunta principal

O planejador proposto reduz a energia necessária para concluir a mesma missão
agrícola, mantendo cobertura, carga útil, origem, destino e segurança?

O modelo atual é de um quadricóptero elétrico: a grandeza relevante é energia
de bateria. Não há modelo implementado de combustível líquido.

## Estado atual

O [benchmark corrigido de 29/10/2026](RESULTADOS_CONVENCIONAL_20261029.md)
substituiu a referência A* por faixas e conexões geométricas sem A*.
Foram 18 voos seguros, todos com cobertura de 100%, e nove pares elegíveis
nos fatores 1×/5×/10×. A proposta gastou mais energia estimada em todos,
com aumentos entre 2,46% e 10,46%. A suíte passou com 215 testes.
Não houve economia demonstrada contra essa referência operacional.
O próximo desenvolvimento deve melhorar conexões e custo energético da
proposta, preservando a referência competente e avaliando em outros dados.

O lote histórico de 28/10/2026 foi executado e está documentado em
`RESULTADOS_20261028.md`: 29 voos principais elegíveis em 30 tentativas,
cinco pares comparáveis, redução estimada no norte e empates no centro/sul.
O diagnóstico posterior com passo menor falhou nos seis voos, portanto a
robustez temporal e a economia física de bateria permanecem sem validação.

O [comparativo de relevo ampliado de 28–29/10/2026](RESULTADOS_RELEVO_20261029.md)
executou 16 voos principais e dois suplementares. Foram testados os mesmos
três recortes em 1×, 5× e 10×, com controle1× reexecutado no regime comum.
Houve redução estimada no norte, chegando a 2,68% em10×, piora no centro
e empate no sul. A falha do suporte físico do centro10× foi preservada;
o par suplementar com suporte corrigido piorou 3,92% e não substitui
as médias do lote principal. A amplificação é sintética e não representa
novas fazendas ou evidência de generalização.

| Componente | Uso no artigo | Pendência |
| --- | --- | --- |
| TOPODATA, grid e obstáculos | Ambiente comum às comparações | Centro de desenvolvimento e norte/sul exploratórios; duas repetições por recorte |
| Faixas geométricas sem A* | Referência convencional | Substitui a referência histórica A* |
| A* horizontal, 3D e com subida | Controles da proposta | Conectados às missões executadas |
| Seleção horizontal/vertical de faixas | Otimização da missão completa | Cinco variantes isolam as contribuições |
| Custo distância 3D + peso × subida | Indicador auxiliar | Não comprova economia de energia |
| Telemetria e segurança | Medição do voo executado | Energia estimada e cobertura observada integradas; colisão obrigatória |
| CoppeliaSim e apresentação | Validação e demonstração visual | Executor físico local e replay das duas telemetrias lado a lado |
| Benchmark e sensibilidade | Relatórios de trajetórias executadas | Ferramentas implementadas; completar coleta e avaliar os relatórios da execução |
| Vento/replanejamento | Experimento complementar futuro | Retirar da demonstração e experimento principais |

O resultado inicial de planejamento de aproximadamente 0,62% refere-se ao
custo normalizado em um recorte real e a uma versão anterior do protocolo.
Nesse recorte, a maior parte da melhoria aparece na seleção
da orientação: não atribuir todo o ganho ao A* nem à bateria.
Os dois voos com vento validaram execução e telemetria; não demonstraram
economia energética e não são o experimento central do artigo.

## Etapa A — comparação visual sem vento

Implementada em `src.coverage_comparison`, com cenário `configs/demo_coverage.yaml`
e iniciador `apresentar.cmd`. A coleta executa cada método na mesma cena
restaurada. `src.comparison_scene` monta depois duas cópias visuais do recorte
e reproduz as telemetrias no mesmo relógio original; o replay não executa uma
nova física no simulador nem gera outra medição. A validação sem conexão exporta os planos; a
coleta requer CoppeliaSim aberto e parado. O custo normalizado continua
sendo apenas um indicador auxiliar.

1. Criar cenário principal sem vento nem deriva artificial.
2. Planejar e executar no mesmo terreno as rotas de cada método, usando o
   mesmo controlador, velocidade, margem, carga e condições iniciais.
3. Usar a mesma origem e retorno para todas as missões, como no comparador
   de planejamento. Essa ligação está implementada: o executor recebe a rota
   comparada diretamente, inclusive todas as células intermediárias e retorno.
4. Salvar plano, trajetória medida e parâmetros de cada execução.

Entrega: demonstração de referência e proposta no CoppeliaSim, com condições
iguais. Não anunciar economia de bateria nesta etapa.

## Etapa B — avaliador energético independente

Protótipo implementado em `src.energy` e integrado ao comparador de voos.
O ajuste parcial e a validação em voos separados foram implementados em
`src.energy_calibration`; consulte `CALIBRACAO_ENERGIA.md`. Não existem
medições reais do veículo do projeto no repositório, portanto a ferramenta
está pronta, mas o modelo ainda não foi calibrado com dados físicos.
Usa referência publicada para voo horizontal e extensão simplificada de subida,
com parâmetros em `configs/energy_reference.json`. Consulte `MODELO_ENERGIA.md`.
A calibração para veículo/carga real e validação elétrica continuam pendentes;
esta etapa ainda não está cientificamente concluída para o veículo real.
As ferramentas das etapas C e D estão implementadas; sua avaliação depende
da coleta preservada, da elegibilidade dos voos e dos relatórios produzidos.
A validação física da bateria permanece uma pendência distinta.

1. Definir um drone de referência e a origem dos parâmetros de massa, carga,
   bateria e potência. Buscar um modelo publicado e dados de calibração.
2. Implementar energia acumulada a partir da potência e do tempo. Se houver
   tensão e corrente reais, usar potência elétrica V × I. Se houver apenas
   dados simulados, declarar explicitamente o modelo de potência e sua validade.
3. Considerar sustentação, deslocamento e subida; avaliar a necessidade de
   termos para curvas/acelerações conforme o modelo escolhido. Não assumir
   consumo zero ao pairar nem recuperação de energia em descidas.
4. Avaliar todos os métodos com o mesmo modelo, separado da função de custo
   que escolhe a rota. Calibrar em manobras independentes das rotas avaliadas.
5. Exportar energia estimada em Wh, duração e parâmetros utilizados. O replay
   exibe os Wh acumulados calculados das telemetrias; não usa um decremento
   arbitrário ou o custo normalizado renomeado.

O cenário usa escala geométrica 1:100 e um controlador demonstrativo. Forças,
massas e velocidades angulares dessa cena não representam automaticamente
grandezas físicas de um drone agrícola real. Não converter potência mecânica
do modelo em consumo elétrico real sem justificar escala, perdas e calibração.

Entrega: avaliação por um modelo explícito e verificável. Sem validação física,
a conclusão será sobre energia estimada no modelo, não autonomia real comprovada.

## Etapa C — algoritmo e isolamento das contribuições

Implementados os cinco métodos, a execução opcional dos cinco voos via
`src.coverage_comparison --ablation` e a análise preliminar de trajetórias
ideais via `src.ablation`. O protocolo está em `COMPARACAO_CONTRIBUICOES.md`.
Isso implementa a comparação; não conclui a coleta de voos nem a validação
científica. A coleta e os relatórios são acompanhados em cada execução do
benchmark. A etapa D fornece os critérios comuns, já implementados, e a
calibração física continua independente da implementação dessas ferramentas.

Comparar no mínimo:

- referência: faixas paralelas pela geometria do talhão, sem A*;
- controle: A* 3D com as mesmas faixas;
- subida: A* com penalização de subida e faixas fixas;
- orientação: seleção de orientação sem penalização de subida;
- proposta completa: penalização de subida e seleção de orientação.

O peso de planejamento e o critério de seleção devem ser definidos usando
cenários de desenvolvimento. Congelar esses parâmetros antes da avaliação.
O avaliador energético permanece comum a todos. Manter os alvos obrigatórios
de cobertura; uma rota menor por deixar lavoura descoberta não é melhor.

Entrega: identificar quanto cada alteração contribui e seu custo computacional.
Empates e pioras são resultados e devem permanecer nas tabelas.

## Etapa D — missão equivalente e protocolo final

Implementados `src.executed_coverage`, a elegibilidade e os contrastes de
energia no comparador, além do executor de lote `src.validation_suite`.
Consulte `VALIDACAO_MISSAO.md`. O lote de 30 voos e a análise estão
integrados em `src.benchmark`. São 30 voos em seis blocos de
recorte/repetição, com cinco métodos por bloco. O estado de cada coleta fica em `attempts.json`,
com falhas e dados parciais preservados. Não confundir implementação com resultado.
Calibração, deposição física e análise estatística não estão concluídas.

O protocolo atual `2_overlap90` fixa largura geométrica de aplicação de
120 m e espaçamento entre faixas de 90 m, iguais para todos os métodos,
mantendo 100% de cobertura executada como critério. A alteração de
espaçamento foi motivada por lacuna de cobertura no piloto, antes de
consultar a economia do par. O piloto e o lote revisado não são repetições
do mesmo protocolo. A ordem usa rotação cíclica determinística dos cinco
métodos; seis blocos não fornecem balanceamento completo nem randomização.
O centro pertence ao desenvolvimento; norte e sul são recortes exploratórios.

1. Medir cobertura pela trajetória executada, incluindo segmentos entre
   amostras e definindo quando a aplicação está ativa.
2. Exigir o mesmo limiar de cobertura, conclusão e segurança nas comparações.
3. Escolher recortes reais por regra geográfica declarada, incluindo áreas
   planas e acidentadas, sem selecionar apenas as que favorecem a proposta.
4. Usar terrenos sintéticos para verificar comportamento, sem apresentá-los
   como amostras independentes de propriedades reais.
5. Repetir voos para avaliar variabilidade da execução; não tratar repetições
   determinísticas como terrenos independentes.
6. Reportar Wh estimados, energia por área efetivamente tratada, duração,
   distância, subida, cobertura, violações e tempo de planejamento. Apresentar
   diferenças pareadas e sensibilidade aos parâmetros do modelo energético.

`src.benchmark_report` conserva no denominador todos os pares previstos,
mostrando falhas e ausências mesmo quando esses pares não podem entrar na
média de energia. `src.energy_sensitivity` usa as mesmas trajetórias em uma
grade fixa de 18 hipóteses teóricas, com pesos iguais por recorte. Os relatórios
devem ser lidos após a coleta e sua auditoria; a existência dos arquivos ou
um ganho percentual positivo não encerra a validação física. Consulte
`BENCHMARK_ENERGIA.md` e `SENSIBILIDADE_ENERGIA.md`.

Ganhos muito pequenos precisam ser comparados à variação entre repetições,
à resolução temporal e espacial e à incerteza do modelo. Não transformar
repetições determinísticas do mesmo recorte em amostras independentes para
obter significância. Sem estudo dessas fontes de erro e medições elétricas
independentes, a conclusão permanece descritiva da energia estimada nas
trajetórias e hipóteses avaliadas.

## Apresentação

Mostrar o mesmo recorte de terreno com duas rotas e resultados lado a lado: cobertura,
tempo e energia estimada. Explicar a contribuição do algoritmo com as
comparações intermediárias. Vento fica como demonstração opcional posterior.

Se os dados não mostrarem economia, relatar o limite observado e investigar
as causas; não ajustar o avaliador após ver os resultados para fabricar ganho.
Consumo real de bateria requer validação adicional com dados elétricos.

## Prioridades após o comparativo de relevo

1. Desenvolver uma função de seleção de trajetórias coerente com energia,
   duração, voo horizontal e subida. A função atual pode reduzir subida
   e aumentar distância e tempo, piorando os Wh estimados. Usar recortes
   de desenvolvimento, congelar a nova regra e avaliar em recortes novos.
2. Corrigir e validar o controlador para mais de um passo temporal e
   velocidade, sem afrouxar os critérios de cobertura e segurança.
3. Calibrar em manobras independentes e validar por tensão/corrente
   medidas no veículo e carga escolhidos, com terrenos e repetições
   adequados. Só então avaliar a alegação de economia real de bateria.

A etapa de relevo e o relatório estão concluídos. Essas prioridades são
experimentos posteriores; os resultados atuais não permitem antecipar
uma vantagem do futuro algoritmo.
