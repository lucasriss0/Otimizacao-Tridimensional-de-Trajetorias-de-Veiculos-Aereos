# Etapa 1: avaliação do planejamento sobre relevo

## Pergunta e hipóteses

Em quais cenários considerar subida e escolher a orientação das faixas reduz
o custo normalizado de uma missão de cobertura, mantendo a cobertura exigida?

- H1: penalizar subida pode reduzir ganho de altitude e custo, com possível
  aumento de distância e esforço computacional.
- H2: escolher entre faixas horizontais e verticais pode melhorar o resultado
  em relação à orientação horizontal fixa.
- Controle: terreno plano e cenários sem vantagem devem preservar empates;
  falhas, cobertura insuficiente e pioras também devem aparecer nos resultados.

São hipóteses para estes experimentos, não resultados presumidos. O custo
normalizado não mede bateria, potência ou energia em joules.

## Comparações

| Método no CSV | Custo de planejamento | Orientação |
| --- | --- | --- |
| `horizontal_2d` | distância horizontal | horizontal fixa |
| `distance_3d` | distância 3D | horizontal fixa |
| `climb_fixed` | distância 3D + peso de planejamento × subida | horizontal fixa |
| `climb_candidate` | distância 3D + peso de planejamento × subida | cada candidato horizontal/vertical |
| `climb_orientation` | escolha do candidato viável de menor custo de avaliação | horizontal ou vertical |

Todos os métodos usam o mesmo grid, máscara, origem, retorno à origem e largura
de aplicação por cenário. A referência 2D mantém a máscara de obstáculos e a
validade do terreno; somente ignora altura no custo. A API existente continua
usando distância 3D por padrão.

Cada faixa conserva todos os seus alvos intermediários livres. A orientação
vertical transpõe a geração dos alvos, preservando as coordenadas originais
para A*, obstáculos e avaliação. O espaçamento usa a dimensão perpendicular
à faixa e arredonda para baixo a razão largura/célula, com mínimo de uma célula.

As rotas podem sair da janela cultivável para conectar alvos, permanecendo
dentro do terreno e respeitando a máscara. A aplicação é considerada ativa
ao longo de toda a rota, inclusive conexões e retorno. A altura de segurança
constante não muda as diferenças de altitude, portanto não entra neste custo.

## Avaliação comum e escolha

Todas as rotas são avaliadas por `distância 3D + evaluation_weight × subida`,
inclusive a referência 2D. O peso de avaliação padrão é 10; os pesos de
planejamento padrão são 0, 3, 10 e 20. Não se compara uma rota avaliada com
peso 0 a outra avaliada com peso 10.

A cobertura mínima padrão é 100% das células cultiváveis livres, usando a
métrica discreta existente de raio de aplicação ao redor das células da rota.
Ela não representa uma medição contínua de pulverização física. Uma rota que
conecta alvos mas não atende à cobertura recebe `eligible=False` e não pode
ser escolhida. `success` indica a conexão dos alvos, não segurança em voo.

O seletor testa somente duas orientações (0° e 90°), por peso de planejamento.
Empates favorecem horizontal. Não há garantia de orientação globalmente ótima.
Tempo e nós expandidos da linha `climb_orientation` incluem os dois candidatos;
os candidatos também ficam no CSV para auditoria, não são repetições independentes.

A seleção minimiza o próprio critério comum declarado. Sua vantagem nesse
critério, sobre candidatos elegíveis, é consequência da seleção; a magnitude,
o ganho de altitude, a distância e o custo computacional precisam ser analisados.
Isso não demonstra generalização para propriedades ou modelos energéticos novos.

## Conjunto e reprodução

A suíte fixa contém terreno plano, morro gaussiano e crista, cada um com e sem
um obstáculo central: seis grids 25 × 25 com células de 10 m e faixa de 40 m.
O plano e o morro incluem controles para empates e simetria; a crista explora
a relação entre orientação e relevo. Nenhum caso é descartado pelo resultado.

`--scenario` acrescenta um recorte TOPODATA com os parâmetros reais do YAML,
mas sem aplicar o vento nem executar o simulador. A origem é a primeira célula
livre da janela em ordem de linha/coluna. Um único recorte real não sustenta
uma conclusão geral sobre terrenos agrícolas.

```powershell
python -m src.planning_experiments --output output/experiments/synthetic_01
python -m src.planning_experiments --scenario configs/demo_wind.yaml --weights 0 3 10 20 --evaluation-weight 10 --minimum-coverage 100 --output output/experiments/real_01
```

Cada execução produz:

- `comparison.csv`: todas as alternativas, viabilidade, métricas e custo de busca;
- `summary.csv`: reduções percentuais pareadas contra 2D, 3D e orientação fixa;
  resultados não comparáveis ficam identificados e sem redução preenchida;
- `route_*.csv`: caminhos completos, incluindo caminhos parciais de falhas;
- `case_*.npz`: matrizes de elevação e máscaras efetivamente utilizadas;
- `manifest.json`: parâmetros, janela, unidades, origem, hashes dos dados,
  versão do código, indicação de alterações locais e versões das dependências;
- três gráficos: custo, ganho de altitude e distância 3D versus peso de planejamento.

Escolha uma pasta nova por execução. Para uma evidência reproduzível do artigo,
execute a partir de um commit sem alterações locais e preserve a pasta inteira.
Rotas e métricas determinísticas devem se repetir; tempos de execução variam.
Repetições de um cenário determinístico não são amostras independentes de terreno.

## Critérios para avançar

1. Verificar os caminhos em casos controlados e a equivalência do custo do A*
   ao de Dijkstra para os modos comparados.
2. Conferir cobertura, falhas e reduções por cenário, sem omitir empates ou pioras.
3. Antes de generalizar, ampliar os recortes reais por uma regra geográfica
   definida antes de observar os resultados e separar desenvolvimento de avaliação.
4. Na etapa seguinte, medir trajetórias executadas e comparar vento variável
   com replanejamento ligado/desligado sob condições iguais.

Esta etapa não altera o controlador, a cena, o modelo de vento nem o critério
de sucesso da execução no CoppeliaSim.
