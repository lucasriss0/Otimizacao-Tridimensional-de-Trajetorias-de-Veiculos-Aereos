import argparse
from pathlib import Path
from time import perf_counter

from src.astar import PathResult, astar
from src.coverage import plan_boustrophedon_coverage
from src.metrics import (
    PathMetrics,
    calculate_path_metrics,
    calculate_reduction_percent,
    export_metrics_csv,
)
from src.terrain import create_example_terrain, load_topodata
from src.visualization import save_coverage_figure, save_path_figure
from src.waypoints import export_waypoints_csv, grid_path_to_waypoints_3d


def resolve_endpoints(
    terrain_shape: tuple[int, int],
    start_row: int | None,
    start_col: int | None,
    goal_row: int | None,
    goal_col: int | None,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Valida pontos informados ou usa o centro das bordas como padrão."""
    values = (start_row, start_col, goal_row, goal_col)
    if not any(value is not None for value in values):
        middle_row = terrain_shape[0] // 2
        return (middle_row, 0), (middle_row, terrain_shape[1] - 1)

    if not all(value is not None for value in values):
        raise ValueError(
            "Informe juntos: --start-row, --start-col, --goal-row e --goal-col."
        )

    start = (start_row, start_col)
    goal = (goal_row, goal_col)
    rows, columns = terrain_shape

    for name, (row, column) in (("origem", start), ("destino", goal)):
        if not (0 <= row < rows and 0 <= column < columns):
            raise ValueError(
                f"A {name} {(row, column)} está fora do grid "
                f"{rows} x {columns}."
            )

    return start, goal


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
    parser.add_argument("--center-lat", type=float, help="Latitude central da fazenda.")
    parser.add_argument("--center-lon", type=float, help="Longitude central da fazenda.")
    parser.add_argument(
        "--area-m", type=float, default=None,
        help="Lado, em metros, da área quadrada recortada (ex.: 1500).",
    )
    parser.add_argument("--start-row", type=int, help="Linha da origem no grid.")
    parser.add_argument("--start-col", type=int, help="Coluna da origem no grid.")
    parser.add_argument("--goal-row", type=int, help="Linha do destino no grid.")
    parser.add_argument("--goal-col", type=int, help="Coluna do destino no grid.")
    parser.add_argument(
        "--coverage", action="store_true",
        help="Executa uma missão completa de cobertura boustrophedon.",
    )
    parser.add_argument(
        "--swath-m", type=float, default=120.0,
        help="Largura de aplicação do drone em metros (padrão: 120).",
    )
    parser.add_argument(
        "--clearance-m", type=float, default=20.0,
        help="Altura de segurança acima do terreno em metros (padrão: 20).",
    )
    return parser.parse_args()


def show_metrics(metrics: PathMetrics) -> None:
    print(f"\nMÉTRICAS - {metrics.route_name}")
    print(f"Distância horizontal: {metrics.horizontal_distance_m:.2f} m")
    print(f"Distância 3D: {metrics.distance_3d_m:.2f} m")
    print(f"Ganho de elevação: {metrics.elevation_gain_m:.2f} m")
    print(f"Perda de elevação: {metrics.elevation_loss_m:.2f} m")
    print(f"Inclinação máxima: {metrics.maximum_slope_deg:.2f}°")
    print(f"Custo energético normalizado: {metrics.normalized_energy_cost:.2f}")
    print(f"Tempo de planejamento: {metrics.planning_time_s:.6f} s")


def main() -> None:
    args = parse_args()

    if args.topodata:
        terrain_data = load_topodata(
            args.topodata,
            target_size=args.size,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            area_size_m=args.area_m,
        )
        terrain = terrain_data.elevation
        output_prefix = "topodata"
        print("GeoTIFF TOPODATA carregado!")
        print(f"Arquivo: {terrain_data.source_path}")
        print(f"Dimensão original: {terrain_data.original_shape}")
        print(f"Dimensão utilizada: {terrain.shape}")
        print(f"CRS: {terrain_data.crs or 'não informado'}")
        print(f"Limites utilizados: {terrain_data.bounds}")
        if terrain_data.area_size_m:
            print(
                f"Área recortada: {terrain_data.area_size_m:.0f} m × "
                f"{terrain_data.area_size_m:.0f} m"
            )
        print(f"Altitude mínima: {terrain.min():.2f} m")
        print(f"Altitude máxima: {terrain.max():.2f} m")
        if terrain_data.area_size_m:
            cell_size_x_m = terrain_data.area_size_m / terrain.shape[1]
            cell_size_y_m = terrain_data.area_size_m / terrain.shape[0]
        else:
            cell_size_x_m = 1.0
            cell_size_y_m = 1.0
    else:
        terrain = create_example_terrain()
        output_prefix = "exemplo"
        print("Nenhum GeoTIFF informado; usando terreno artificial.")
        cell_size_x_m = 1.0
        cell_size_y_m = 1.0

    start, goal = resolve_endpoints(
        terrain.shape,
        args.start_row,
        args.start_col,
        args.goal_row,
        args.goal_col,
    )
    print(f"Origem no grid: {start}")
    print(f"Destino no grid: {goal}")

    if args.coverage:
        started = perf_counter()
        coverage_result = plan_boustrophedon_coverage(
            terrain=terrain,
            swath_width_m=args.swath_m,
            climb_weight=args.climb_weight,
            cell_size_x_m=cell_size_x_m,
            cell_size_y_m=cell_size_y_m,
        )
        coverage_time = perf_counter() - started
        if not coverage_result.success:
            raise RuntimeError(coverage_result.error)

        print("\n" + "=" * 60)
        print("MISSÃO DE COBERTURA BOUSTROPHEDON")
        print("=" * 60)
        print(f"Largura de aplicação: {args.swath_m:.2f} m")
        print(f"Espaçamento: {coverage_result.stripe_spacing_cells} células")
        print(f"Waypoints: {len(coverage_result.waypoints)}")
        print(f"Pontos da rota: {len(coverage_result.path)}")
        print(f"Cobertura estimada: {coverage_result.coverage_percent:.2f}%")

        coverage_metrics = calculate_path_metrics(
            "cobertura_boustrophedon", terrain, coverage_result.path,
            cell_size_x_m, cell_size_y_m, args.climb_weight,
            coverage_time, coverage_result.expanded_nodes,
        )
        show_metrics(coverage_metrics)
        metrics_path = export_metrics_csv(
            [coverage_metrics], "output/metricas_cobertura.csv"
        )
        waypoints_3d = grid_path_to_waypoints_3d(
            terrain, coverage_result.path, cell_size_x_m, cell_size_y_m,
            args.clearance_m,
        )
        waypoints_path = export_waypoints_csv(
            waypoints_3d, "output/waypoints_coppeliasim.csv"
        )
        figure_path = f"output/{output_prefix}_cobertura_boustrophedon.png"
        save_coverage_figure(
            terrain, coverage_result.path, coverage_result.waypoints,
            figure_path,
            f"Cobertura boustrophedon ({coverage_result.coverage_percent:.1f}%)",
        )
        print(f"Métricas exportadas para: {metrics_path}")
        print(f"Waypoints 3D exportados para: {waypoints_path}")
        print(f"Altura de segurança: {args.clearance_m:.2f} m")
        print(f"Imagem gerada: {figure_path}")
        return

    started = perf_counter()
    result_without_climb_penalty = astar(
        terrain=terrain, start=start, goal=goal, climb_weight=0.0,
        cell_size_x_m=cell_size_x_m, cell_size_y_m=cell_size_y_m,
    )
    baseline_time = perf_counter() - started

    started = perf_counter()
    result_with_climb_penalty = astar(
        terrain=terrain, start=start, goal=goal,
        climb_weight=args.climb_weight,
        cell_size_x_m=cell_size_x_m,
        cell_size_y_m=cell_size_y_m,
    )
    proposed_time = perf_counter() - started

    show_result("CENÁRIO 1 - Menor distância", result_without_climb_penalty)
    show_result("CENÁRIO 2 - Subida penalizada", result_with_climb_penalty)

    all_metrics: list[PathMetrics] = []
    if result_without_climb_penalty.success:
        baseline_metrics = calculate_path_metrics(
            "baseline",
            terrain,
            result_without_climb_penalty.path,
            cell_size_x_m,
            cell_size_y_m,
            args.climb_weight,
            baseline_time,
            result_without_climb_penalty.expanded_nodes,
        )
        all_metrics.append(baseline_metrics)
        show_metrics(baseline_metrics)
    if result_with_climb_penalty.success:
        proposed_metrics = calculate_path_metrics(
            "astar_energia",
            terrain,
            result_with_climb_penalty.path,
            cell_size_x_m,
            cell_size_y_m,
            args.climb_weight,
            proposed_time,
            result_with_climb_penalty.expanded_nodes,
        )
        all_metrics.append(proposed_metrics)
        show_metrics(proposed_metrics)

    if len(all_metrics) == 2:
        reduction = calculate_reduction_percent(
            all_metrics[0].normalized_energy_cost,
            all_metrics[1].normalized_energy_cost,
        )
        print(f"\nRedução de custo em relação ao baseline: {reduction:.2f}%")

    if all_metrics:
        metrics_path = export_metrics_csv(all_metrics, "output/metricas_rotas.csv")
        print(f"Métricas exportadas para: {metrics_path}")

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
        waypoints_3d = grid_path_to_waypoints_3d(
            terrain, result_with_climb_penalty.path,
            cell_size_x_m, cell_size_y_m, args.clearance_m,
        )
        waypoints_path = export_waypoints_csv(
            waypoints_3d, "output/waypoints_coppeliasim.csv"
        )
        print(f"Waypoints 3D exportados para: {waypoints_path}")

    print("\nImagens geradas:")
    print(f"- output/{output_prefix}_menor_distancia.png")
    print(f"- output/{output_prefix}_subida_penalizada.png")


if __name__ == "__main__":
    main()
