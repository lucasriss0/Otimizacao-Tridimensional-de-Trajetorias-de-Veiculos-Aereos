# Cena de comparação lado a lado

A comparação visual usa **telemetrias de missões já executadas no CoppeliaSim**.
Dois recortes iguais do terreno aparecem na mesma cena, com a proposta à
esquerda e a referência à direita. A referência usa faixas paralelas
alternadas (lawnmower), um padrão comum na pulverização agrícola.
Os drones desta cena são ícones geométricos sem dinâmica.
[Estudo de cobertura com drone agrícola](https://link.springer.com/article/10.1007/s11119-023-09999-3)
O replay ilustra os dados do benchmark e não realiza uma segunda medição.

Os iniciadores `apresentar.cmd` e `benchmark.cmd` montam essa cena ao concluir
a coleta e o relatório. O benchmark usa o primeiro par em ordem de coleta
com ambas as missões completas, sem consultar a economia. `session.json`
registra `presentation_source` e `presentation_selection_rule`. As falhas
anteriores permanecem no relatório, e conclusão da missão por si só não
garante elegibilidade energética.

Para apresentar na interface do CoppeliaSim:

1. Abra `presentation/comparacao_lado_a_lado.ttt` pelo menu **File**, caso a
   cena preparada já não esteja aberta.
2. Clique em **Play** na barra do simulador. O painel mostra o tempo do
   replay e os Wh estimados dos dois voos. Os ícones geométricos seguem as
   telemetrias armazenadas; o controlador de voo não é executado de novo.
3. Aguarde a pausa automática no quadro final. Compare a cobertura e os
   indicadores de elegibilidade antes de interpretar o percentual exibido.
4. Para repetir desde o início, use **Stop** e depois **Play**. O processo
   Python da coleta pode permanecer encerrado durante essa apresentação.

Abra também `report/index.html` para mostrar o conjunto de resultados. Uma
única cena é uma ilustração do par selecionado e não resume o lote inteiro.

Execute primeiro `src.coverage_comparison` ou um par do lote
`src.validation_suite`. Com o CoppeliaSim aberto e a simulação parada:

```powershell
.venv/Scripts/python.exe -m src.comparison_scene output/experiments/SEU_PAR --output output/experiments/SEU_REPLAY --replay --rate 4 --realtime
```

Em um par com as cinco variantes, use o caminho registrado em
`session.json.presentation_source` e selecione o nome correspondente da proposta:

```powershell
.venv/Scripts/python.exe -m src.comparison_scene PASTA_DO_PAR_ESCOLHIDO --output output/experiments/SEU_REPLAY --proposed proposta_completa --replay
```

`--rate` altera somente a velocidade de apresentação; `--realtime` usa tempo de
parede para acompanhá-la. `--loop` repete a reprodução. Sem `--replay`, o comando
prepara e salva a cena. O script Lua fica embutido no arquivo
`comparacao_lado_a_lado.ttt`: depois basta abrir essa cena e apertar **Play**, sem
Python externo. A reprodução sem loop pausa no quadro final para apresentação.

As figuras exportáveis do benchmark usam Matplotlib, sem renderização adicional
no simulador. A exportação experimental por sensor de visão foi retirada após
encerrar o CoppeliaSim no computador de teste. A reprodução nativa foi
reaberta e verificada pela evolução das posições dos dois drones na API.

As rotas planejadas são azul (referência) e laranja (proposta). A trilha branca
mostra as posições executadas até o instante reproduzido. O painel apresenta o
tempo original, a energia acumulada estimada em Wh, a cobertura geométrica final
e a elegibilidade de cada missão. A redução percentual final só aparece quando
as duas missões são elegíveis; valores negativos continuam visíveis.
O replay aplica a mesma reauditoria do relatório para segurança, cobertura,
lacunas, envelope energético e compatibilidade do par. Uma flag positiva isolada
no CSV não confirma elegibilidade; os motivos de exclusão ficam no manifesto.

Os relógios começam na primeira amostra de cada voo e avançam juntos em segundos
originais. As durações não são normalizadas. Quando um drone termina antes, sua
posição e sua energia ficam congeladas enquanto o outro conclui a missão. Não se
acrescenta consumo de espera ao drone que já encerrou seu voo registrado.

A montagem preserva a cena aberta em `scene_before.ttt`, recusa sobrescrever a
pasta de saída e não modifica os CSVs. `replay_manifest.json` registra métodos,
durações, energia final, translações visuais e hashes das telemetrias e do
protocolo. As translações laterais pertencem somente ao desenho; a análise mantém
o referencial métrico original. Obstáculos são marcadores visuais simplificados,
sem substituir as verificações de colisão efetuadas durante os voos de origem.

**Escopo científico:** o indicador é energia calculada a partir das trajetórias
executadas e do modelo de referência. Não há medição elétrica nesta cena. A
referência atual é geométrica, sem A*, identificada por
`baseline_planner=parallel_geometric_v1`. As cenas dos lotes antigos conservam
sua referência A* e são históricas. O painel identifica o método a partir do
protocolo. Uma economia mostrada no replay precisa ser interpretada junto com
o protocolo, a elegibilidade e os resultados completos do benchmark.
