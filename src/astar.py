from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import hypot, inf
from typing import Optional

import numpy as np


Position = tuple[int, int]


@dataclass
class PathResult:
    success: bool
    path: list[Position]
    total_cost: float
    expanded_nodes: int
    error: Optional[str] = None


def heuristic(
    current: Position,
    goal: Position,
    cell_size_x_m: float = 1.0,
    cell_size_y_m: float = 1.0,
) -> float:
    """Distância octil: admissível para movimentos retos e diagonais."""
    row_difference = abs(current[0] - goal[0])
    column_difference = abs(current[1] - goal[1])
    diagonal_steps = min(row_difference, column_difference)

    return (
        diagonal_steps * hypot(cell_size_x_m, cell_size_y_m)
        + (row_difference - diagonal_steps) * cell_size_y_m
        + (column_difference - diagonal_steps) * cell_size_x_m
    )


def is_traversable(
    position: Position,
    terrain: np.ndarray,
    obstacle_mask: np.ndarray | None = None,
) -> bool:
    blocked = obstacle_mask is not None and bool(obstacle_mask[position])
    return bool(np.isfinite(terrain[position])) and not blocked


def get_neighbors(
    position: Position,
    terrain: np.ndarray,
    obstacle_mask: np.ndarray | None = None,
) -> list[Position]:
    row, column = position
    movements = [
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1),
    ]
    neighbors = []

    for row_change, column_change in movements:
        candidate = (row + row_change, column + column_change)
        inside = (
            0 <= candidate[0] < terrain.shape[0]
            and 0 <= candidate[1] < terrain.shape[1]
        )
        if not inside or not is_traversable(candidate, terrain, obstacle_mask):
            continue

        # Uma diagonal não pode atravessar o canto de duas células bloqueadas.
        if row_change != 0 and column_change != 0:
            side_vertical = (row + row_change, column)
            side_horizontal = (row, column + column_change)
            if not (
                is_traversable(side_vertical, terrain, obstacle_mask)
                and is_traversable(side_horizontal, terrain, obstacle_mask)
            ):
                continue

        neighbors.append(candidate)

    return neighbors


def movement_cost(
    terrain: np.ndarray,
    current: Position,
    neighbor: Position,
    climb_weight: float,
    cell_size_x_m: float = 1.0,
    cell_size_y_m: float = 1.0,
) -> float:
    current_height = float(terrain[current])
    neighbor_height = float(terrain[neighbor])
    elevation_difference = neighbor_height - current_height
    elevation_gain = max(0.0, elevation_difference)
    row_delta = neighbor[0] - current[0]
    column_delta = neighbor[1] - current[1]
    horizontal_distance = hypot(
        column_delta * cell_size_x_m,
        row_delta * cell_size_y_m,
    )
    distance_3d = hypot(horizontal_distance, elevation_difference)
    return distance_3d + climb_weight * elevation_gain


def reconstruct_path(
    came_from: dict[Position, Optional[Position]], goal: Position
) -> list[Position]:
    path = []
    current: Optional[Position] = goal
    while current is not None:
        path.append(current)
        current = came_from[current]
    return list(reversed(path))


def astar(
    terrain: np.ndarray,
    start: Position,
    goal: Position,
    climb_weight: float = 3.0,
    cell_size_x_m: float = 1.0,
    cell_size_y_m: float = 1.0,
    obstacle_mask: np.ndarray | None = None,
) -> PathResult:
    if terrain.ndim != 2:
        return PathResult(False, [], inf, 0, "O terreno precisa ser uma matriz bidimensional.")

    if obstacle_mask is not None and obstacle_mask.shape != terrain.shape:
        return PathResult(False, [], inf, 0, "A máscara de obstáculos deve ter o mesmo formato do terreno.")

    rows, columns = terrain.shape
    for name, position in (("origem", start), ("destino", goal)):
        row, column = position
        if not (0 <= row < rows and 0 <= column < columns):
            return PathResult(False, [], inf, 0, f"A posição de {name} está fora do terreno.")
        if not is_traversable(position, terrain, obstacle_mask):
            return PathResult(False, [], inf, 0, f"A posição de {name} está bloqueada.")

    if climb_weight < 0:
        return PathResult(False, [], inf, 0, "O peso de subida não pode ser negativo.")
    if cell_size_x_m <= 0 or cell_size_y_m <= 0:
        return PathResult(False, [], inf, 0, "O tamanho da célula precisa ser positivo.")

    insertion_order = count()
    frontier = []
    start_priority = heuristic(start, goal, cell_size_x_m, cell_size_y_m)
    heappush(frontier, (start_priority, next(insertion_order), start))
    came_from: dict[Position, Optional[Position]] = {start: None}
    cost_so_far: dict[Position, float] = {start: 0.0}
    expanded_nodes = 0

    while frontier:
        queued_priority, _, current = heappop(frontier)
        current_priority = cost_so_far[current] + heuristic(
            current, goal, cell_size_x_m, cell_size_y_m
        )
        if queued_priority > current_priority + 1e-12:
            continue

        expanded_nodes += 1
        if current == goal:
            return PathResult(
                True,
                reconstruct_path(came_from, goal),
                cost_so_far[goal],
                expanded_nodes,
            )

        for neighbor in get_neighbors(current, terrain, obstacle_mask):
            new_cost = cost_so_far[current] + movement_cost(
                terrain,
                current,
                neighbor,
                climb_weight,
                cell_size_x_m,
                cell_size_y_m,
            )
            if neighbor not in cost_so_far or new_cost < cost_so_far[neighbor]:
                cost_so_far[neighbor] = new_cost
                came_from[neighbor] = current
                priority = new_cost + heuristic(
                    neighbor, goal, cell_size_x_m, cell_size_y_m
                )
                heappush(frontier, (priority, next(insertion_order), neighbor))

    return PathResult(False, [], inf, expanded_nodes, "Não foi possível encontrar um caminho.")
