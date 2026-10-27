# Plano do artigo: eficiência energética da missão agrícola

Este plano substitui a prioridade anterior de demonstração de vento.

## Pergunta principal

O planejador proposto reduz a energia necessária para concluir a mesma missão
agrícola, mantendo cobertura, carga útil, origem, destino e segurança?

O modelo atual é de um quadricóptero elétrico: a grandeza relevante é energia
de bateria. Não há modelo implementado de combustível líquido.

## Estado atual

| Componente | Uso no artigo | Pendência |
| --- | --- | --- |
| TOPODATA, grid e obstáculos | Ambiente comum às comparações | Definir vários recortes antes de observar resultados |
| A* horizontal, 3D e com subida | Referências e proposta | Conectar os modos às missões executadas |
| Seleção horizontal/vertical de faixas | Otimização da missão completa | Isolar seu efeito do efeito do A* |
| Custo distância 3D + peso × subida | Indicador auxiliar | Não comprova economia de energia |
| Telemetria e segurança | Medição do voo executado | Acrescentar energia e cobertura executada |
| CoppeliaSim e apresentação | Validação e demonstração visual | Executar as rotas dos métodos comparados, sem vento |
| Vento/replanejamento | Experimento complementar futuro | Retirar da demonstração e experimento principais |

O resultado real inicial de aproximadamente 0,62% refere-se ao custo
normalizado. Nesse recorte, a maior parte da melhoria aparece na seleção
da orientação: não atribuir todo o ganho ao A* nem à bateria.
Os dois voos com vento validaram execução e telemetria; não demonstraram
economia energética e não são o experimento central do artigo.

## Etapa A — comparação visual sem vento

Implementada em `src.coverage_comparison`, com cenário `configs/demo_coverage.yaml`
e iniciador `apresentar.cmd`. A validação sem conexão exporta os planos; a
execução real requer CoppeliaSim aberto e parado. O custo normalizado continua
sendo apenas um indicador auxiliar.

1. Criar cenário principal sem vento nem deriva artificial.
2. Planejar e executar no mesmo terreno as rotas de cada método, usando o
   mesmo controlador, velocidade, margem, carga e condições iniciais.
3. Usar a mesma origem e retorno para todas as missões, como no comparador
   de planejamento. O executor atual de demonstração ainda não reproduz
   automaticamente as rotas do comparador: implementar essa ligação.
4. Salvar plano, trajetória medida e parâmetros de cada execução.

Entrega: demonstração de referência e proposta no CoppeliaSim, com condições
iguais. Não anunciar economia de bateria nesta etapa.

## Etapa B — avaliador energético independente

Protótipo implementado em `src.energy` e integrado ao comparador de voos.
Usa referência publicada para voo horizontal e extensão simplificada de subida,
com parâmetros em `configs/energy_reference.json`. Consulte `MODELO_ENERGIA.md`.
A calibração para veículo/carga real e validação elétrica continuam pendentes;
esta etapa ainda não está cientificamente concluída. As etapas C e D também
permanecem pendentes.

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
5. Exportar energia estimada em Wh, duração e parâmetros utilizados. Uma
   animação de bateria será derivada desse cálculo, nunca de um decremento
   arbitrário ou do custo normalizado renomeado.

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
científica. A calibração e a etapa D continuam pendentes.

Comparar no mínimo:

- referência: A* horizontal com faixas horizontais fixas;
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

## Apresentação

Mostrar a mesma fazenda com duas rotas e resultados lado a lado: cobertura,
tempo e energia estimada. Explicar a contribuição do algoritmo com as
comparações intermediárias. Vento fica como demonstração opcional posterior.

Se os dados não mostrarem economia, relatar o limite observado e investigar
as causas; não ajustar o avaliador após ver os resultados para fabricar ganho.
Consumo real de bateria requer validação adicional com dados elétricos.
