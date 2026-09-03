from dataclasses import asdict, dataclass
from math import atan2, degrees, hypot, sqrt
from pathlib import Path
import csv

import numpy as np

from src.astar import Position


@dataclass(frozen=True)
class PathMetrics:
    route_name: str
    horizontal_distance_m: float
    distance_3d_m: float
    elevation_gain_m: float
    elevation_loss_m: float
    maximum_slope_deg: float
    normalized_energy_cost: float
    planning_time_s: float
    expanded_nodes: int
    path_points: int


def calculate_path_metrics(
    route_name: str,
    terrain: np.ndarray,
    path: list[Position],
    cell_size_x_m: float,
    cell_size_y_m: float,
    climb_weight: float,
    planning_time_s: float,
    expanded_nodes: int,
) -> PathMetrics:
    """Calcula métricas físicas e um custo normalizado para uma rota."""
    if cell_size_x_m <= 0 or cell_size_y_m <= 0:
        raise ValueError("O tamanho da célula precisa ser positivo.")
    if climb_weight < 0:
        raise ValueError("O peso de subida não pode ser negativo.")
    if not path:
        raise ValueError("Não é possível medir uma rota vazia.")

    horizontal_distance = 0.0
    distance_3d = 0.0
    elevation_gain = 0.0
    elevation_loss = 0.0
    maximum_slope = 0.0

    for current, neighbor in zip(path, path[1:]):
        row_delta = neighbor[0] - current[0]
        column_delta = neighbor[1] - current[1]
        horizontal = hypot(
            column_delta * cell_size_x_m,
            row_delta * cell_size_y_m,
        )
        elevation_delta = float(terrain[neighbor] - terrain[current])

        horizontal_distance += horizontal
        distance_3d += sqrt(horizontal**2 + elevation_delta**2)
        elevation_gain += max(0.0, elevation_delta)
        elevation_loss += max(0.0, -elevation_delta)

        if horizontal > 0:
            maximum_slope = max(
                maximum_slope,
                abs(degrees(atan2(elevation_delta, horizontal))),
            )

    normalized_cost = distance_3d + climb_weight * elevation_gain

    return PathMetrics(
        route_name=route_name,
        horizontal_distance_m=horizontal_distance,
        distance_3d_m=distance_3d,
        elevation_gain_m=elevation_gain,
        elevation_loss_m=elevation_loss,
        maximum_slope_deg=maximum_slope,
        normalized_energy_cost=normalized_cost,
        planning_time_s=planning_time_s,
        expanded_nodes=expanded_nodes,
        path_points=len(path),
    )


def calculate_reduction_percent(
    baseline_cost: float,
    proposed_cost: float,
) -> float:
    if baseline_cost <= 0:
        return 0.0
    return 100.0 * (baseline_cost - proposed_cost) / baseline_cost


def export_metrics_csv(
    metrics: list[PathMetrics],
    output_path: str | Path,
) -> Path:
    if not metrics:
        raise ValueError("Nenhuma métrica foi fornecida para exportação.")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(item) for item in metrics]

    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return destination
