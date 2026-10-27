# Separação das contribuições do algoritmo

O modo `--ablation` do comparador de voos executa cinco variantes na mesma
cena, sem vento, com o mesmo controlador, origem, retorno e velocidade:

| Variante | Busca | Faixas |
| --- | --- | --- |
| referencia_2d | distância horizontal | horizontais fixas |
| distancia_3d | distância 3D | horizontais fixas |
| somente_subida | distância 3D + penalização de subida | horizontais fixas |
| somente_orientacao | distância 3D sem penalização de subida | escolha horizontal/vertical |
| proposta_completa | distância 3D + penalização de subida | escolha horizontal/vertical |

“Somente orientação” retira a penalização de subida da busca; o critério que
escolhe entre orientações continua sendo o mesmo custo normalizado declarado
para a proposta completa. Assim a comparação varia o custo da busca, mantendo
o seletor fixo. Não significa que o seletor ignora altitude. A energia é medida
pelo avaliador após escolher a rota, sem selecionar a alternativa de menor Wh.

```powershell
python -m src.coverage_comparison --ablation
```

As cinco rotas devem atender à cobertura planejada de 100%; cada plano é
exportado, e cada voo gera telemetria e estimativa energética própria. Missões
incompletas continuam nos registros e não devem ser anunciadas como economia.
Esse modo ainda não mede a cobertura efetivamente aplicada.

## Análise preliminar sem simulador

```powershell
python -m src.ablation --scenario configs/demo_coverage.yaml --output output/experiments/ablation_01
```

O comando compara os seis cenários sintéticos fixos e, opcionalmente, um
recorte real. Assume velocidade **3D constante**, sem pausas, estabilização,
curvas ou acelerações do controlador. Os valores são identificados como
`ideal_constant_3d_speed` e não representam voos executados. O modelo energético
é o mesmo em todas as variantes e permanece não calibrado.

`ablation.csv` preserva todas as variantes e métricas; `effects.csv` traz seis
contrastes pareados por terreno, incluindo empates e valores negativos:
relevo 3D, subida com faixas fixas, orientação sem subida na busca, orientação
com subida, subida com orientação e efeito total. A redução é calculada como
100 × (energia da referência − energia da variante) / energia da referência.
Falhas ou cobertura insuficiente deixam o contraste não comparável.
Intervalos fora do envelope energético ficam sinalizados, sem descarte.

Não somar reduções percentuais para concluir a contribuição total: os efeitos
podem interagir. Também não tratar os métodos ou terrenos sintéticos como
repetições independentes de propriedades rurais reais.

`protocol.json` guarda parâmetros, configuração energética, versão do código,
estado de alterações locais e especificação dos casos. Matrizes e máscaras
ficam em `terrain_*.npz`; os caminhos ficam em `route_*.csv`.

O ganho do custo normalizado pode divergir do ganho energético estimado:
um desvio reduz subida, mas aumenta duração e energia de sustentação. Isso
é um resultado relevante, não um motivo para mudar o avaliador após a análise.
A validação científica ainda exige calibração, cobertura executada e vários
recortes reais definidos antes de observar resultados.
