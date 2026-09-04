from dataclasses import dataclass
from math import ceil

import numpy as np

from src.astar import PathResult, Position, astar
from src.wind import WindCostParameters, WindVector


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


@dataclass(frozen=True)
class CoverageWindow:
    """Limites inclusivos de uma área retangular dentro do grid completo."""

    row_start: int
    col_start: int
    row_end: int
    col_end: int

    def validate(self, shape: tuple[int, int]) -> None:
        rows, columns = shape
        if not (
            0 <= self.row_start <= self.row_end < rows
            and 0 <= self.col_start <= self.col_end < columns
        ):
            raise ValueError(f"Janela de cobertura fora do grid {rows} x {columns}.")


def generate_boustrophedon_waypoints(
    terrain: np.ndarray,
    stripe_spacing_cells: int,
    window: CoverageWindow | None = None,
) -> list[Position]:
    """Cria extremidades de faixas horizontais em sentidos alternados."""
    if terrain.ndim != 2 or terrain.size == 0:
        raise ValueError("O terreno precisa ser uma matriz bidimensional não vazia.")
    if stripe_spacing_cells < 1:
        raise ValueError("O espaçamento entre faixas deve ser de ao menos uma célula.")

    rows, columns = terrain.shape
    selected = window or CoverageWindow(0, 0, rows - 1, columns - 1)
    selected.validate(terrain.shape)
    stripe_rows = list(
        range(selected.row_start, selected.row_end + 1, stripe_spacing_cells)
    )
    uncovered_bottom_distance = selected.row_end - stripe_rows[-1]
    if uncovered_bottom_distance > stripe_spacing_cells / 2:
        stripe_rows.append(selected.row_end)

    waypoints: list[Position] = []
    for index, row in enumerate(stripe_rows):
        endpoints = ((row, selected.col_start), (row, selected.col_end))
        if index % 2:
            endpoints = tuple(reversed(endpoints))
        waypoints.extend(endpoints)
    return waypoints


def generate_boustrophedon_targets(
    terrain: np.ndarray,
    stripe_spacing_cells: int,
    window: CoverageWindow | None = None,
) -> list[Position]:
    """Gera todas as células centrais que precisam ser visitadas nas faixas."""
    endpoints = generate_boustrophedon_waypoints(
        terrain, stripe_spacing_cells, window
    )
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
    window: CoverageWindow | None = None,
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

    cultivable = np.ones(terrain_shape, dtype=bool)
    if window is not None:
        window.validate(terrain_shape)
        cultivable[:] = False
        cultivable[
            window.row_start : window.row_end + 1,
            window.col_start : window.col_end + 1,
        ] = True
    if obstacle_mask is not None:
        if obstacle_mask.shape != terrain_shape:
            raise ValueError("A máscara de obstáculos deve ter o formato do terreno.")
        cultivable &= ~obstacle_mask
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
    window: CoverageWindow | None = None,
    wind: WindVector | None = None,
    wind_cost: WindCostParameters | None = None,
) -> CoverageResult:
    """Gera as faixas e usa A* para ligar cada par consecutivo de waypoints."""
    if swath_width_m <= 0:
        return CoverageResult(False, [], [], 0.0, 0, 0.0, 0, "A largura de aplicação deve ser positiva.")

    spacing = max(1, int(round(swath_width_m / cell_size_y_m)))
    try:
        waypoints = generate_boustrophedon_waypoints(terrain, spacing, window)
        targets = generate_boustrophedon_targets(terrain, spacing, window)
    except ValueError as exc:
        return CoverageResult(False, [], [], 0.0, 0, 0.0, spacing, str(exc))
    if obstacle_mask is not None:
        if obstacle_mask.shape != terrain.shape:
            return CoverageResult(False, [], [], 0.0, 0, 0.0, spacing, "Máscara de obstáculos incompatível.")
        targets = [target for target in targets if not obstacle_mask[target]]
    if len(targets) < 2:
        return CoverageResult(False, waypoints, [], 0.0, 0, 0.0, spacing, "Não há células livres suficientes para planejar a cobertura.")
    planned = plan_targets(
        terrain,
        targets,
        climb_weight,
        cell_size_x_m,
        cell_size_y_m,
        obstacle_mask,
        wind,
        wind_cost,
    )
    if not planned.success:
        return CoverageResult(
            False, waypoints, planned.path, 0.0, planned.expanded_nodes,
            planned.total_cost, spacing, planned.error,
        )
    complete_path = planned.path

    coverage = calculate_coverage_percent(
        terrain.shape, complete_path, swath_width_m,
        cell_size_x_m, cell_size_y_m, obstacle_mask, window,
    )
    return CoverageResult(
        True, waypoints, complete_path, coverage, planned.expanded_nodes,
        planned.total_cost, spacing,
    )


def plan_targets(
    terrain: np.ndarray,
    targets: list[Position],
    climb_weight: float,
    cell_size_x_m: float,
    cell_size_y_m: float,
    obstacle_mask: np.ndarray | None = None,
    wind: WindVector | None = None,
    wind_cost: WindCostParameters | None = None,
) -> PathResult:
    """Conecta uma sequência fixa de alvos; útil no plano inicial e no replanejamento."""

    if not targets:
        return PathResult(False, [], float("inf"), 0, "Nenhum alvo recebido.")
    if len(targets) == 1:
        return PathResult(True, targets.copy(), 0.0, 0)

    complete_path: list[Position] = []
    expanded_nodes = 0
    total_cost = 0.0
    for start, goal in zip(targets, targets[1:]):
        segment = astar(
            terrain,
            start,
            goal,
            climb_weight,
            cell_size_x_m,
            cell_size_y_m,
            obstacle_mask,
            wind,
            wind_cost,
        )
        expanded_nodes += segment.expanded_nodes
        if not segment.success:
            return PathResult(
                False,
                complete_path,
                total_cost,
                expanded_nodes,
                f"Falha ao conectar {start} a {goal}: {segment.error}",
            )
        total_cost += segment.total_cost
        complete_path.extend(segment.path if not complete_path else segment.path[1:])
    return PathResult(True, complete_path, total_cost, expanded_nodes)


def replan_remaining_targets(
    terrain: np.ndarray,
    current: Position,
    remaining_targets: list[Position],
    climb_weight: float,
    cell_size_x_m: float,
    cell_size_y_m: float,
    obstacle_mask: np.ndarray | None = None,
    wind: WindVector | None = None,
    wind_cost: WindCostParameters | None = None,
) -> PathResult:
    targets = [current]
    targets.extend(target for target in remaining_targets if target != current)
    return plan_targets(
        terrain,
        targets,
        climb_weight,
        cell_size_x_m,
        cell_size_y_m,
        obstacle_mask,
        wind,
        wind_cost,
    )
