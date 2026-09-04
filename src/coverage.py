from dataclasses import dataclass
from math import ceil

import numpy as np

from src.astar import PathResult, Position, astar


@dataclass(frozen=True)
class CoverageResult:
    success: bool
    waypoints: list[Position]
    path: list[Position]
    coverage_percent: float
    expanded_nodes: int
    total_cost: float
    stripe_spacing_cells: int
    error: str | None = None


def generate_boustrophedon_waypoints(
    terrain: np.ndarray,
    stripe_spacing_cells: int,
) -> list[Position]:
    """Cria extremidades de faixas horizontais em sentidos alternados."""
    if terrain.ndim != 2 or terrain.size == 0:
        raise ValueError("O terreno precisa ser uma matriz bidimensional não vazia.")
    if stripe_spacing_cells < 1:
        raise ValueError("O espaçamento entre faixas deve ser de ao menos uma célula.")

    rows, columns = terrain.shape
    stripe_rows = list(range(0, rows, stripe_spacing_cells))
    uncovered_bottom_distance = (rows - 1) - stripe_rows[-1]
    if uncovered_bottom_distance > stripe_spacing_cells / 2:
        stripe_rows.append(rows - 1)

    waypoints: list[Position] = []
    for index, row in enumerate(stripe_rows):
        endpoints = ((row, 0), (row, columns - 1))
        if index % 2:
            endpoints = tuple(reversed(endpoints))
        waypoints.extend(endpoints)
    return waypoints


def generate_boustrophedon_targets(
    terrain: np.ndarray,
    stripe_spacing_cells: int,
) -> list[Position]:
    """Gera todas as células centrais que precisam ser visitadas nas faixas."""
    endpoints = generate_boustrophedon_waypoints(terrain, stripe_spacing_cells)
    targets: list[Position] = []
    for start, goal in zip(endpoints[::2], endpoints[1::2]):
        step = 1 if goal[1] >= start[1] else -1
        targets.extend(
            (start[0], column)
            for column in range(start[1], goal[1] + step, step)
        )
    return targets


def calculate_coverage_percent(
    terrain_shape: tuple[int, int],
    path: list[Position],
    swath_width_m: float,
    cell_size_x_m: float,
    cell_size_y_m: float,
    obstacle_mask: np.ndarray | None = None,
) -> float:
    """Calcula a parcela do grid coberta pela faixa de aplicação do drone."""
    if not path:
        return 0.0
    if swath_width_m <= 0 or cell_size_x_m <= 0 or cell_size_y_m <= 0:
        raise ValueError("Largura de aplicação e tamanho das células devem ser positivos.")

    rows, columns = terrain_shape
    covered = np.zeros(terrain_shape, dtype=bool)
    radius_rows = int(ceil((swath_width_m / 2) / cell_size_y_m))
    radius_columns = int(ceil((swath_width_m / 2) / cell_size_x_m))

    for row, column in path:
        row_start, row_end = max(0, row - radius_rows), min(rows, row + radius_rows + 1)
        col_start, col_end = max(0, column - radius_columns), min(columns, column + radius_columns + 1)
        for candidate_row in range(row_start, row_end):
            for candidate_col in range(col_start, col_end):
                dy = (candidate_row - row) * cell_size_y_m
                dx = (candidate_col - column) * cell_size_x_m
                if dx * dx + dy * dy <= (swath_width_m / 2) ** 2:
                    covered[candidate_row, candidate_col] = True

    if obstacle_mask is None:
        cultivable = np.ones(terrain_shape, dtype=bool)
    else:
        if obstacle_mask.shape != terrain_shape:
            raise ValueError("A máscara de obstáculos deve ter o formato do terreno.")
        cultivable = ~obstacle_mask
    cultivable_count = int(cultivable.sum())
    if cultivable_count == 0:
        return 0.0
    return 100.0 * float((covered & cultivable).sum()) / cultivable_count


def plan_boustrophedon_coverage(
    terrain: np.ndarray,
    swath_width_m: float,
    climb_weight: float,
    cell_size_x_m: float,
    cell_size_y_m: float,
    obstacle_mask: np.ndarray | None = None,
) -> CoverageResult:
    """Gera as faixas e usa A* para ligar cada par consecutivo de waypoints."""
    if swath_width_m <= 0:
        return CoverageResult(False, [], [], 0.0, 0, 0.0, 0, "A largura de aplicação deve ser positiva.")

    spacing = max(1, int(round(swath_width_m / cell_size_y_m)))
    waypoints = generate_boustrophedon_waypoints(terrain, spacing)
    targets = generate_boustrophedon_targets(terrain, spacing)
    if obstacle_mask is not None:
        if obstacle_mask.shape != terrain.shape:
            return CoverageResult(False, [], [], 0.0, 0, 0.0, spacing, "Máscara de obstáculos incompatível.")
        targets = [target for target in targets if not obstacle_mask[target]]
    if len(targets) < 2:
        return CoverageResult(False, waypoints, [], 0.0, 0, 0.0, spacing, "Não há células livres suficientes para planejar a cobertura.")
    complete_path: list[Position] = []
    expanded_nodes = 0
    total_cost = 0.0

    for start, goal in zip(targets, targets[1:]):
        segment: PathResult = astar(
            terrain, start, goal, climb_weight, cell_size_x_m, cell_size_y_m,
            obstacle_mask,
        )
        expanded_nodes += segment.expanded_nodes
        if not segment.success:
            return CoverageResult(
                False, waypoints, complete_path, 0.0, expanded_nodes,
                total_cost, spacing,
                f"Falha ao conectar {start} a {goal}: {segment.error}",
            )
        total_cost += segment.total_cost
        complete_path.extend(segment.path if not complete_path else segment.path[1:])

    coverage = calculate_coverage_percent(
        terrain.shape, complete_path, swath_width_m,
        cell_size_x_m, cell_size_y_m, obstacle_mask,
    )
    return CoverageResult(
        True, waypoints, complete_path, coverage, expanded_nodes,
        total_cost, spacing,
    )
