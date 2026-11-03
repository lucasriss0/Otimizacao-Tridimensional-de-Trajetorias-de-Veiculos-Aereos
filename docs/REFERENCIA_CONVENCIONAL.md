# Referência convencional de cobertura, sem A*

A partir da revisão de 29/10/2026, `src.conventional.plan_conventional`
gera a referência operacional. O A* fica nos métodos da proposta.
Os lotes anteriores comparavam variantes de A*; seus percentuais não
demonstram superioridade sobre a operação convencional.

## Regra fixada antes da nova coleta

1. Definir faixas retas e paralelas ao maior lado do talhão. Em um quadrado,
   usar a direção horizontal. Essa escolha não consulta elevação ou energia.
2. Alternar o sentido das passadas, com o mesmo espaçamento e cobertura
   exigidos da proposta. Manter origem e retorno comuns.
3. Conectar os pontos por segmentos retos. Quando houver interseção com uma
   exclusão, construir um grafo de visibilidade dos vértices das áreas
   proibidas e usar Dijkstra por distância horizontal. Não há heurística A*,
   penalização de subida ou expansão de células do terreno nessa referência.
4. A exclusão usa as mesmas células de segurança dos obstáculos, tratadas
   como quadrados acrescidos de 0,01 célula. Isso impede cortar contatos
   entre obstáculos. Conexões impossíveis produzem falha explícita.
5. Amostrar os segmentos em posições contínuas, com espaçamento máximo igual
   ao menor lado da célula. A interpolação bilinear de altitude preserva
   linhas retas em XY, sem transformar uma diagonal em escada de células.

A chave `referencia_2d` dos CSVs foi conservada por compatibilidade. Nos
novos protocolos, `baseline_planner=parallel_geometric_v1` e
`method_plan_mapping` identificam o plano `convencional_geometrico`.
Não se deve misturar essa referência com `horizontal_2d` dos lotes antigos.
O relatório específico de relevo recusa regimes com referências diferentes.

## Relação com equipamentos comerciais

Os manuais DJI descrevem rotas A–B com passadas paralelas, espaçamento,
altura sobre a cultura, direção configurável, planejamento de obstáculos
e acompanhamento automático do terreno. Consulte o
[manual Agras T70P, seção A–B](https://dl.djicdn.com/downloads/t70_t100/20250612_multi/T70P_User_Manual_v1.0_en.pdf)
e as [funções de acompanhamento do terreno do T25](https://ag.dji.com/t25/faq).

Nossa referência reproduz regras geométricas declaradas desse tipo de
operação. O grafo de visibilidade/Dijkstra é a implementação escolhida
para os desvios; não há evidência de que esse seja o algoritmo interno
dos fabricantes. Não é uma reprodução certificada de DJI ou XAG.

## Condições comuns e limites

Referência e proposta usam o mesmo terreno, obstáculos, altura-alvo,
controlador, velocidade, passo temporal, energia e exigência de cobertura.
O acompanhamento da elevação não é exclusivo da proposta A*.

A revisão corrige o planejador da referência. O benchmark de relevo ainda
usa parâmetros demonstrativos de 100 m de altura e faixa geométrica de
120 m. A aplicação continua ativa nas conexões e retorno, conforme a
política comum registrada, sem bomba, dose ou deposição física. Curvas,
limites de aceleração, sensores e carga não foram calibrados para uma
operação real. Não anunciar esses testes como reprodução de pulverização
comercial nem como economia real de bateria comprovada.

## Verificação

Os testes bloqueiam chamadas de A* durante o planejamento convencional,
inclusive com obstáculo; conferem direção independente de relevo,
passadas retas, exclusões atravessadas por amostragem independente,
fechamento da missão, cobertura, barreiras e interpolação de altitude.
O novo lote repete os três recortes nos fatores 1×, 5× e 10×, com uma
repetição e ordem de métodos alternada, sem selecionar casos por ganho.
