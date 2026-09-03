import argparse
from pathlib import Path

from src.astar import PathResult, astar
from src.terrain import create_example_terrain, load_topodata
from src.visualization import save_path_figure


def show_result(name: str, result: PathResult) -> None:
    print()
    print("=" * 60)
    print(name)
    print("=" * 60)
    if not result.success:
        print(f"Falha: {result.error}")
        return
    print(f"Rota: {result.path}")
    print(f"Custo calculado: {result.total_cost:.2f}")
    print(f"Nós expandidos: {result.expanded_nodes}")
    print(f"Quantidade de posições: {len(result.path)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Planejamento de trajetória sobre relevo artificial ou TOPODATA."
    )
    parser.add_argument(
        "--topodata", type=Path,
        help="Caminho para um arquivo GeoTIFF do TOPODATA.",
    )
    parser.add_argument(
        "--size", type=int, default=50,
        help="Quantidade de linhas e colunas do grid reduzido (padrão: 50).",
    )
    parser.add_argument(
        "--climb-weight", type=float, default=3.0,
        help="Peso aplicado ao ganho de altitude (padrão: 3).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.topodata:
        terrain_data = load_topodata(args.topodata, target_size=args.size)
        terrain = terrain_data.elevation
        output_prefix = "topodata"
        print("GeoTIFF TOPODATA carregado!")
        print(f"Arquivo: {terrain_data.source_path}")
        print(f"Dimensão original: {terrain_data.original_shape}")
        print(f"Dimensão utilizada: {terrain.shape}")
        print(f"CRS: {terrain_data.crs or 'não informado'}")
        print(f"Altitude mínima: {terrain.min():.2f} m")
        print(f"Altitude máxima: {terrain.max():.2f} m")
    else:
        terrain = create_example_terrain()
        output_prefix = "exemplo"
        print("Nenhum GeoTIFF informado; usando terreno artificial.")

    middle_row = terrain.shape[0] // 2
    start = (middle_row, 0)
    goal = (middle_row, terrain.shape[1] - 1)

    result_without_climb_penalty = astar(
        terrain=terrain, start=start, goal=goal, climb_weight=0.0
    )
    result_with_climb_penalty = astar(
        terrain=terrain, start=start, goal=goal,
        climb_weight=args.climb_weight,
    )

    show_result("CENÁRIO 1 - Menor distância", result_without_climb_penalty)
    show_result("CENÁRIO 2 - Subida penalizada", result_with_climb_penalty)

    if result_without_climb_penalty.success:
        save_path_figure(
            terrain=terrain,
            path=result_without_climb_penalty.path,
            start=start,
            goal=goal,
            output_path=f"output/{output_prefix}_menor_distancia.png",
            title="A* - Somente distância",
        )
    if result_with_climb_penalty.success:
        save_path_figure(
            terrain=terrain,
            path=result_with_climb_penalty.path,
            start=start,
            goal=goal,
            output_path=f"output/{output_prefix}_subida_penalizada.png",
            title="A* - Distância e penalização de subida",
        )

    print("\nImagens geradas:")
    print(f"- output/{output_prefix}_menor_distancia.png")
    print(f"- output/{output_prefix}_subida_penalizada.png")


if __name__ == "__main__":
    main()
