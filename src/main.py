import argparse
from pathlib import Path
from time import perf_counter

from src.astar import PathResult, astar
from src.metrics import (
    PathMetrics,
    calculate_path_metrics,
    calculate_reduction_percent,
    export_metrics_csv,
)
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
    parser.add_argument("--center-lat", type=float, help="Latitude central da fazenda.")
    parser.add_argument("--center-lon", type=float, help="Longitude central da fazenda.")
    parser.add_argument(
        "--area-m", type=float, default=None,
        help="Lado, em metros, da área quadrada recortada (ex.: 1500).",
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

    middle_row = terrain.shape[0] // 2
    start = (middle_row, 0)
    goal = (middle_row, terrain.shape[1] - 1)

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

    print("\nImagens geradas:")
    print(f"- output/{output_prefix}_menor_distancia.png")
    print(f"- output/{output_prefix}_subida_penalizada.png")


if __name__ == "__main__":
    main()
