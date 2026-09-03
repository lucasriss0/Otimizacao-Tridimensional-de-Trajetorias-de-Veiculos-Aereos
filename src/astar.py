from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import inf, hypot, sqrt
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
    """
    Distância de Manhattan.
    Como inicialmente permitimos apenas movimentos horizontais
    e verticais, essa heurística não superestima a distância.
    """
    row_difference = abs(current[0] - goal[0])
    column_difference = abs(current[1] - goal[1])

    return (
        row_difference * cell_size_y_m
        + column_difference * cell_size_x_m
    )


def get_neighbors(position: Position, terrain: np.ndarray) -> list[Position]:
    row, column = position

    possible_movements = [
        (-1, 0),  # cima
        (1, 0),   # baixo
        (0, -1),  # esquerda
        (0, 1),   # direita
    ]

    neighbors = []

    for row_change, column_change in possible_movements:
        new_row = row + row_change
        new_column = column + column_change

        inside_rows = 0 <= new_row < terrain.shape[0]
        inside_columns = 0 <= new_column < terrain.shape[1]

        if inside_rows and inside_columns:
            neighbors.append((new_row, new_column))

    return neighbors


def movement_cost(
    terrain: np.ndarray,
    current: Position,
    neighbor: Position,
    climb_weight: float,
    cell_size_x_m: float = 1.0,
    cell_size_y_m: float = 1.0,
) -> float:
    """
    Calcula o custo de um movimento.

    Todo movimento custa 1.
    Subidas recebem uma penalização adicional.
    Descidas não produzem custo negativo.
    """
    current_height = terrain[current]
    neighbor_height = terrain[neighbor]

    elevation_gain = max(0.0, neighbor_height - current_height)

    row_delta = neighbor[0] - current[0]
    column_delta = neighbor[1] - current[1]
    horizontal_distance = hypot(
        column_delta * cell_size_x_m,
        row_delta * cell_size_y_m,
    )
    distance_cost = sqrt(horizontal_distance**2 + (neighbor_height - current_height)**2)
    climb_cost = climb_weight * elevation_gain

    return distance_cost + climb_cost


def reconstruct_path(
    came_from: dict[Position, Optional[Position]],
    goal: Position,
) -> list[Position]:
    path = []
    current: Optional[Position] = goal

    while current is not None:
        path.append(current)
        current = came_from[current]

    path.reverse()

    return path


def astar(
    terrain: np.ndarray,
    start: Position,
    goal: Position,
    climb_weight: float = 3.0,
    cell_size_x_m: float = 1.0,
    cell_size_y_m: float = 1.0,
) -> PathResult:
    if terrain.ndim != 2:
        return PathResult(
            success=False,
            path=[],
            total_cost=inf,
            expanded_nodes=0,
            error="O terreno precisa ser uma matriz bidimensional.",
        )

    rows, columns = terrain.shape

    for name, position in [("origem", start), ("destino", goal)]:
        row, column = position

        if not (0 <= row < rows and 0 <= column < columns):
            return PathResult(
                success=False,
                path=[],
                total_cost=inf,
                expanded_nodes=0,
                error=f"A posição de {name} está fora do terreno.",
            )

    if climb_weight < 0:
        return PathResult(
            success=False,
            path=[],
            total_cost=inf,
            expanded_nodes=0,
            error="O peso de subida não pode ser negativo.",
        )
    if cell_size_x_m <= 0 or cell_size_y_m <= 0:
        return PathResult(
            success=False,
            path=[],
            total_cost=inf,
            expanded_nodes=0,
            error="O tamanho da célula precisa ser positivo.",
        )

    insertion_order = count()

    frontier = []
    heappush(
        frontier,
        (
            heuristic(start, goal, cell_size_x_m, cell_size_y_m),
            next(insertion_order),
            start,
        ),
    )

    came_from: dict[Position, Optional[Position]] = {
        start: None,
    }

    cost_so_far: dict[Position, float] = {
        start: 0.0,
    }

    expanded_nodes = 0

    while frontier:
        _, _, current = heappop(frontier)
        expanded_nodes += 1

        if current == goal:
            path = reconstruct_path(came_from, goal)

            return PathResult(
                success=True,
                path=path,
                total_cost=cost_so_far[goal],
                expanded_nodes=expanded_nodes,
            )

        for neighbor in get_neighbors(current, terrain):
            new_cost = (
                cost_so_far[current]
                + movement_cost(
                    terrain,
                    current,
                    neighbor,
                    climb_weight,
                    cell_size_x_m,
                    cell_size_y_m,
                )
            )

            if (
                neighbor not in cost_so_far
                or new_cost < cost_so_far[neighbor]
            ):
                cost_so_far[neighbor] = new_cost
                came_from[neighbor] = current

                estimated_total_cost = (
                    new_cost
                    + heuristic(
                        neighbor, goal, cell_size_x_m, cell_size_y_m
                    )
                )

                heappush(
                    frontier,
                    (
                        estimated_total_cost,
                        next(insertion_order),
                        neighbor,
                    ),
                )

    return PathResult(
        success=False,
        path=[],
        total_cost=inf,
        expanded_nodes=expanded_nodes,
        error="Não foi possível encontrar um caminho.",
    )
