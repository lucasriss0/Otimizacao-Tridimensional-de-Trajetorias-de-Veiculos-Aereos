from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
out=Path("output/pdf/guia_estudo_apresentacao.pdf")
c=canvas.Canvas(str(out),pagesize=(595,842))
c.setTitle("Guia de estudo | Código e apresentação do projeto")
y=0;n=0
def text(s,size=11,gap=9):
 global y
 p=Paragraph(escape(s),ParagraphStyle("p",fontName="Helvetica",fontSize=size,leading=size*1.4,textColor=HexColor("#243746")))
 _,h=p.wrap(499,760)
 if y-h<55:raise RuntimeError((n,s))
 p.drawOn(c,48,y-h);y-=h+gap
def page(t,sub):
 global y,n
 if n:c.showPage()
 n+=1
 c.setFillColor(HexColor("#163849"));c.rect(0,790,595,52,fill=1,stroke=0)
 c.setFillColor(white);c.setFont("Helvetica-Bold",9);c.drawString(48,812,"GUIA DE ESTUDO / TRAJETÓRIAS PARA DRONE AGRÍCOLA")
 c.setFillColor(HexColor("#56717F"));c.setFont("Helvetica",9)
 c.drawString(48,29,"18 NOV 2026 / CÓDIGO SIMPLIFICADO PARA APRESENTAÇÃO")
 c.drawRightString(547,29,str(n))
 y=760;text(t,24,12);text(sub,11,17)
def h(s):
 global y
 y-=2
 text(s,13,5)
def box(s):
 global y
 p=Paragraph(escape(s),ParagraphStyle("b",fontSize=11,leading=15,textColor=HexColor("#163849")))
 _,hh=p.wrap(473,700)
 c.setFillColor(HexColor("#E8F3EF"));c.roundRect(48,y-hh-22,499,hh+22,7,fill=1,stroke=0)
 p.drawOn(c,61,y-hh-11);y-=hh+35
def code(*ss):
 global y
 hh=17+len(ss)*15
 c.setFillColor(HexColor("#163849"));c.roundRect(48,y-hh,499,hh,6,fill=1,stroke=0)
 c.setFillColor(white);c.setFont("Courier",9)
 for i,s in enumerate(ss):c.drawString(60,y-18-15*i,s)
 y-=hh+14
def table(head,rows,widths):
 global y
 for i,row in enumerate([head]+rows):
  cells=[]
  for s,w in zip(row,widths):
   p=Paragraph(escape(s),ParagraphStyle("t",fontName="Helvetica-Bold" if i==0 else "Helvetica",fontSize=10,leading=14,textColor=white if i==0 else HexColor("#243746")))
   _,hh=p.wrap(w-16,700);cells.append((p,w,hh))
  hh=max(v[2] for v in cells)+14
  if y-hh<55:raise RuntimeError((n,row))
  c.setFillColor(HexColor("#09685E" if i==0 else "#EFF4F6" if i%2 else "#F9FBFC"))
  c.rect(48,y-hh,499,hh,fill=1,stroke=0)
  xx=48
  for p,w,ph in cells:p.drawOn(c,xx+8,y-ph-7);xx+=w
  y-=hh
 y-=14
page("Entenda o código e apresente o projeto","Material de estudo dos arquivos que permaneceram após a simplificação.")
text("O projeto transforma dados reais de elevação em uma missão de cobertura agrícola. Nosso método usa A* com distância tridimensional, penalização de subida e seleção da orientação das faixas. A referência usa faixas paralelas alternadas com conexões geométricas.")
box("Sequência para estudar: configuração → terreno → planejamento → waypoints → execução → métricas → apresentação.")
h("O que você deve conseguir explicar")
for s in ["Como o mapa de elevação vira uma grade e depois uma rota.","Como nosso A* e o método convencional escolhem caminhos.","Como o simulador executa a missão e registra a posição efetiva.","Como cobertura e energia são calculadas e o que o resultado mostrou."]:text("• "+s)
h("Resultado principal")
text("No par completo registrado no mapa principal, os dois métodos atingiram 100% de cobertura geométrica. A referência estimou 289,25 Wh e o A* estimou 293,48 Wh. O A* subiu menos, mas percorreu uma rota mais longa e teve 1,46% a mais de energia estimada.")
text("Este guia explica os módulos da versão simplificada e o papel das funções principais. Os resultados citados pertencem à coleta completa já registrada, identificada na página de resultados.",10)

page("Os dois comandos","O atalho escolhe entre executar nosso método e abrir a comparação.")
h("Apresentação individual")
code(r".\apresentar.cmd --novo")
text("Prepara um terreno e executa somente nosso A*, com o voo visível. O caminho começa em coverage_comparison.py e usa o executor Lua de coppelia_benchmark.py. O programa inicia a simulação automaticamente.")
h("Comparação")
code(r".\apresentar.cmd")
text("benchmark.py procura uma comparação completa salva para o cenário. Quando encontra, abre a cena. Aperte Play para reproduzir os dois voos com o mesmo relógio. Se faltar um replay compatível, o programa coleta os dois voos em sequência antes de montar a comparação.")
h("O que faz apresentar.cmd")
text("Verifica a existência do Python no ambiente .venv, aceita apenas os argumentos previstos e seleciona o módulo de entrada. Com --novo, passa --proposed-only ao comparador. Sem argumento, solicita a comparação salva por --reuse-replay.")
box("Antes de executar, abra o CoppeliaSim e deixe a simulação parada com Stop. Durante uma coleta do par aparece um terreno por vez. O replay final mostra A* à esquerda e referência à direita.")
text("O parâmetro --novo tem o significado definido no atalho atual: apresentação individual do A*. Os documentos antigos podem descrever o significado anterior.")

page("1. Ler e organizar os dados","Os arquivos de entrada transformam a configuração e o relevo em estruturas que os planejadores entendem.")
table(["Arquivo","Responsabilidade"],[
("scenario.py","Lê o YAML, resolve caminhos, cria objetos de configuração e valida alturas, velocidade, janela e espaçamento."),
("terrain.py","Abre o GeoTIFF, recorta a região, reamostra as elevações e fornece a altura de uma posição por interpolação."),
("obstacles.py","Representa obstáculos por posição e raio de segurança. Cria uma máscara de células bloqueadas."),
("__init__.py","Identifica src como pacote Python, permitindo executar módulos com python -m src.nome.")],[135,364])
h("Mapa, grade e janela")
text("No cenário principal, o mapa mede 3 × 3 km e tem 100 × 100 células. Cada célula representa aproximadamente 30 × 30 m. A janela de missão é a região central de 20 × 20 células, correspondente a 600 × 600 m de área bruta.")
h("Como interpretar as coordenadas")
text("A origem XY fica no centro da grade. X cresce para leste e Y para norte. A matriz armazena uma elevação em cada célula. A posição do drone em metros precisa ser convertida para o mesmo referencial.")
box("Fala sugerida: Primeiro carregamos a missão e recortamos o relevo real. Depois representamos a região como uma grade e marcamos as áreas que o drone precisa evitar.")

page("2. Construir a cobertura","A cobertura determina as passadas e os pontos que precisam ser visitados.")
table(["Arquivo","Responsabilidade"],[
("coverage.py","Gera faixas em sentidos alternados, define a janela e conecta os alvos. CoverageWindow valida os limites. plan_targets concatena as conexões entre alvos."),
("planning_experiments.py","Organiza PlanningCase e PlanningTrial. case_from_scenario carrega o caso real. compare_planners avalia candidatos e escolhe a orientação elegível de menor custo."),
("waypoints.py","Converte células em pontos (x, y, z) em metros, adiciona altura de segurança e exporta os waypoints."),
("wind.py","Define vetores, eventos e parâmetros de vento compartilhados com o cenário e o custo. A apresentação usa vento zero.")],[155,344])
h("Boustrophedon")
text("É o padrão de passadas alternadas, semelhante a percorrer uma área linha por linha. Ao terminar uma faixa, a missão segue para a próxima no sentido oposto. O padrão organiza a cobertura; as conexões e os obstáculos determinam os desvios necessários.")
code("> > > > >","        |","< < < < <","|","> > > > >")
h("Do ponto da grade ao waypoint")
text("A célula fornece a posição horizontal e a elevação do terreno. waypoints.py transforma essa informação em metros e acrescenta a altura de segurança. A lista final é a referência para o executor.")

page("3. Entender o A*","astar.py implementa a busca entre a origem e o destino.")
table(["Função","O que faz"],[
("heuristic()","Estima a distância restante pelo movimento octil em XY."),
("is_traversable()","Verifica se a elevação é válida e se a célula está livre."),
("get_neighbors()","Gera até oito movimentos e rejeita diagonais que cortam cantos bloqueados."),
("movement_cost()","Soma distância, subida positiva e, quando configurado, penalidade de vento."),
("reconstruct_path()","Segue os predecessores e reconstrói o caminho."),
("astar()","Mantém a fila de prioridade, os custos e os predecessores até chegar ao destino ou esgotar as opções.")],[152,347])
h("Prioridade da busca")
box("f(n) = g(n) + h(n)\ng(n) acumula o custo já percorrido. h(n) estima o custo restante. O algoritmo dá prioridade aos candidatos com menor f(n).")
h("Custo do trecho sem vento")
text("custo = raiz(Δx² + Δy² + Δz²) + 0,304 × max(0, Δz)")
text("Em um trecho com 10 m horizontais e 5 m de subida, a distância 3D é 11,18 m. A penalidade é 0,304 × 5 = 1,52. O custo é aproximadamente 12,70. Na descida pelo mesmo trecho, a parcela adicional de subida é zero.")
text("A busca é 2,5D. Ela escolhe células horizontais e deriva a altitude do relevo mais uma margem. O drone percorre uma trajetória 3D, mas a busca ainda não escolhe livremente diferentes camadas de altitude.",10)

page("4. Entender a referência","conventional.py implementa as faixas paralelas e as conexões geométricas.")
text("plan_conventional() escolhe a direção das passadas pelo maior lado da área. Em empate, usa a horizontal. As faixas seguem em sentidos alternados e a missão retorna ao ponto de partida.")
h("Conexão entre os pontos")
text("GeometricConnections tenta ligar dois pontos por uma reta livre. Se uma exclusão bloquear o trecho, monta alternativas em um grafo de visibilidade, formado pelos cantos das regiões proibidas, e usa Dijkstra para escolher a conexão de menor distância horizontal.")
table(["Decisão","Referência","Nosso A*"],[
("Orientação","Maior lado da área; horizontal no empate.","Avalia horizontal e vertical pelo custo."),
("Conexões","Retas e desvios geométricos.","Busca discreta em oito direções."),
("Custo de seleção","Distância XY nas conexões.","Distância 3D e subida positiva."),
("Altitude executada","Acompanha o relevo mais a margem.","Acompanha o relevo mais a margem.")],[112,193,194])
box("Fala sugerida: A referência usa passadas paralelas e conexões geométricas. Nosso método busca conexões numa grade, penaliza subida e escolhe a orientação pelo custo. Os dois recebem o mesmo terreno e as mesmas condições de voo.")
text("A implementação é uma referência explícita do padrão de cobertura. O código não reproduz um algoritmo proprietário específico de um fabricante.",10)

page("5. Preparar e executar a cena","O planejamento fornece os pontos. O controlador do simulador faz o drone acompanhá-los.")
table(["Arquivo","Responsabilidade"],[
("coppelia_terrain.py","Converte a matriz em um heightfield, a superfície de elevação usada pelo simulador, e aplica a escala."),
("coppelia_scene.py","Cria o terreno, carrega o quadricóptero, insere os obstáculos fixos e ajusta a câmera."),
("coppelia_benchmark.py","Executa a missão com Lua dentro do CoppeliaSim, recebe lotes de telemetria e trata limites de tempo e encerramento. É o executor usado pelo atalho."),
("coppeliasim.py","Contém estruturas de telemetria e funções compartilhadas de integração, descoberta de objetos, segurança e salvamento. Também mantém um executor Python alternativo.")],[164,335])
h("O que é o target")
text("É o objeto de referência que o controlador do quadricóptero tenta acompanhar. O projeto move o target ao longo da rota, e o controlador movimenta o corpo do drone. Curvas e estabilização fazem a posição executada diferir um pouco da trajetória planejada.")
h("Quem coordena tudo")
text("coverage_comparison.py carrega o cenário, gera os planos, verifica origem, retorno e cobertura, prepara a cena, executa os métodos selecionados e salva métricas e protocolo. proposed_only=True seleciona somente nosso A*.")
box("Fala sugerida: O planejador fornece os pontos da missão. O controlador acompanha esses pontos, e registramos a posição efetiva do drone para avaliar o voo.")

page("6. Avaliar o voo","Cada arquivo responde a uma pergunta sobre a rota ou a trajetória registrada.")
table(["Arquivo","Pergunta respondida"],[
("metrics.py","Quanto mede a rota planejada? Soma distância horizontal e 3D, subida, descida, inclinação e custo normalizado."),
("telemetry_metrics.py","O que o drone efetivamente executou? Resume distância, subida, erro de rastreamento e segurança observada."),
("executed_coverage.py","Quanto da área foi alcançado pela faixa ao longo da trajetória medida? Também determina a elegibilidade para comparação."),
("energy.py","Quantos Wh o modelo estima para a trajetória? Calcula velocidades e integra potência por intervalo.")],[159,340])
h("Energia calculada por intervalos")
text("O tempo e a diferença de posições entre amostras fornecem as velocidades. O modelo soma potência básica de voo, potência adicional de subida e auxiliares. Multiplica a potência por cada intervalo de tempo e divide o total de joules por 3.600.")
box("Energia em Wh = soma de (potência em W × intervalo em s) ÷ 3.600.")
text("O custo do A* orienta a escolha da rota. Os Wh estimados avaliam o percurso executado. O peso 0,304 foi aproximado para 4 m/s; a apresentação usa 8 m/s. A mesma conversão do modelo nessa velocidade produz cerca de 0,680. Nos recortes avaliados, esses pesos produziram a mesma rota selecionada.")
text("A cobertura é geométrica e a energia depende de um modelo teórico. Medições elétricas do veículo e avaliações de dose e deposição continuam necessárias para validar uma operação agrícola real.",10)

page("7. Relatório e comparação","Os registros de voo são usados para gerar o material visual.")
table(["Arquivo","Responsabilidade"],[
("benchmark.py","Procura uma comparação salva ou coordena uma nova coleta, o relatório e a cena. find_saved_replay() localiza um par completo. run_benchmark() organiza a execução."),
("benchmark_report.py","Lê os resultados, monta os pares, registra exclusões e gera tabelas, gráficos e relatório HTML."),
("comparison_scene.py","Cria duas cópias visuais do terreno e reproduz as trajetórias registradas, interpolando posição e energia no mesmo relógio.")],[164,335])
h("O que acontece no replay")
text("Os dois marcadores começam juntos. Quando um voo termina, seu marcador permanece na posição final e sua energia fica congelada, enquanto o outro continua até seu próprio término. Os tempos originais são preservados.")
box("A coleta executa os voos em sequência. A apresentação reproduz os dois registros simultaneamente.")
h("Arquivos de saída")
text("protocol.json guarda o cenário e os planos. comparison.csv guarda os resultados por método. telemetry.csv registra posição e tempo. report/index.html apresenta os resultados. A cena comparacao_lado_a_lado.ttt contém o replay. Cada execução cria sua própria pasta em output/experiments.")

page("8. Explicar o resultado","Par completo registrado no mapa principal, com peso de subida 0,304.")
table(["Métrica","Referência","Nosso A*"],[
("Energia estimada","289,25 Wh","293,48 Wh"),
("Distância executada","5.432,05 m","5.537,63 m"),
("Duração","692,85 s","705,10 s"),
("Cobertura geométrica","100%","100%")],[215,142,142])
text("Nosso A* subiu 18,87 m a menos, percorreu 105,58 m a mais e levou 12,25 s a mais. O modelo estimou energia total 1,46% maior para o A*.")
box("Fala sugerida: Nosso método reduziu a subida acumulada nesse cenário. Porém, o aumento da distância e da duração superou a economia. Isso mostra a necessidade de equilibrar o custo total da missão, incluindo o tempo de voo.")
h("Como tratar a conclusão")
text("O resultado descreve esse cenário e esse modelo de energia. Para generalizar, o estudo precisa de mais terrenos, comparação com alvos e orientação controlados e calibração com dados de um veículo definido.")
h("Fonte dos números")
text("output/experiments/custo_vs_convencional_nova_coleta/flights/comparison.csv. Os valores se referem à coleta completa anterior à simplificação. Resultados de execuções novas devem ser conferidos nos respectivos arquivos.",10)

page("9. Roteiro para estudar e apresentar","Use os módulos como etapas de uma história que começa no mapa e termina na evidência.")
table(["Ordem","O que estudar"],[
("1","apresentar.cmd e coverage_comparison.py: entenda o fluxo completo."),
("2","astar.py, coverage.py e conventional.py: explique a diferença entre os métodos."),
("3","scenario.py, terrain.py, obstacles.py e waypoints.py: acompanhe os dados."),
("4","coppelia_scene.py, coppelia_terrain.py, coppelia_benchmark.py e coppeliasim.py: entenda a execução."),
("5","metrics.py, telemetry_metrics.py, executed_coverage.py e energy.py: interprete as medições."),
("6","benchmark.py, benchmark_report.py e comparison_scene.py: explique a comparação.")],[55,444])
h("Perguntas para praticar")
for s in ["Qual problema o projeto tenta resolver?","Como uma célula do mapa vira um waypoint?","Como o peso de subida afeta o custo?","Como o método convencional desvia de um obstáculo?","Por que menos subida pode resultar em mais energia?","Qual a diferença entre o voo executado e o replay?","Que conclusão os dados permitem tirar neste cenário?"]:text("• "+s,10.5,5)
text("Resumo para abrir a apresentação: Desenvolvemos um fluxo que usa relevo real para planejar e avaliar cobertura agrícola. Comparamos A* com faixas convencionais sob as mesmas condições e usamos a telemetria do simulador para analisar cobertura, segurança e energia estimada.",10)
c.save()
print(out.resolve(),n)
