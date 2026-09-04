from dataclasses import asdict, dataclass
from pathlib import Path
import csv

import numpy as np

from src.astar import Position, is_traversable


@dataclass(frozen=True)
class Waypoint3D:
    sequence: int
    grid_row: int
    grid_column: int
    x_m: float
    y_m: float
    z_m: float
    terrain_z_m: float
    altitude_asl_m: float


def grid_path_to_waypoints_3d(
    terrain: np.ndarray,
    path: list[Position],
    cell_size_x_m: float,
    cell_size_y_m: float,
    clearance_m: float,
) -> list[Waypoint3D]:
    """Converte posições do grid para o referencial métrico local da simulação."""
    if terrain.ndim != 2:
        raise ValueError("O terreno precisa ser uma matriz bidimensional.")
    if not path:
        raise ValueError("Não é possível converter uma rota vazia.")
    if cell_size_x_m <= 0 or cell_size_y_m <= 0:
        raise ValueError("O tamanho da célula precisa ser positivo.")
    if clearance_m <= 0:
        raise ValueError("A altura de segurança precisa ser positiva.")

    rows, columns = terrain.shape
    minimum_elevation = float(np.min(terrain))
    center_row = (rows - 1) / 2
    center_column = (columns - 1) / 2
    waypoints = []

    for sequence, (row, column) in enumerate(path):
        if not (0 <= row < rows and 0 <= column < columns):
            raise ValueError(f"A posição {(row, column)} está fora do terreno.")
        elevation = float(terrain[row, column])
        if not np.isfinite(elevation):
            raise ValueError(f"A posição {(row, column)} não possui elevação válida.")

        terrain_z = elevation - minimum_elevation
        waypoints.append(
            Waypoint3D(
                sequence=sequence,
                grid_row=row,
                grid_column=column,
                x_m=(column - center_column) * cell_size_x_m,
                y_m=(center_row - row) * cell_size_y_m,
                z_m=terrain_z + clearance_m,
                terrain_z_m=terrain_z,
                altitude_asl_m=elevation + clearance_m,
            )
        )
    return waypoints


def export_waypoints_csv(
    waypoints: list[Waypoint3D], output_path: str | Path
) -> Path:
    if not waypoints:
        raise ValueError("Nenhum waypoint foi fornecido para exportação.")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(waypoint) for waypoint in waypoints]
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return destination


def local_xy_to_grid(
    x_m: float,
    y_m: float,
    terrain_shape: tuple[int, int],
    cell_size_x_m: float,
    cell_size_y_m: float,
) -> Position:
    """Converte coordenadas métricas locais para a célula mais próxima."""

    if cell_size_x_m <= 0 or cell_size_y_m <= 0:
        raise ValueError("O tamanho da célula precisa ser positivo.")
    rows, columns = terrain_shape
    if rows < 1 or columns < 1:
        raise ValueError("O terreno precisa conter células.")
    center_row = (rows - 1) / 2
    center_column = (columns - 1) / 2
    row = round(center_row - y_m / cell_size_y_m)
    column = round(center_column + x_m / cell_size_x_m)
    return (
        min(rows - 1, max(0, int(row))),
        min(columns - 1, max(0, int(column))),
    )


def nearest_traversable_grid_position(
    position: Position,
    terrain: np.ndarray,
    obstacle_mask: np.ndarray | None = None,
) -> Position:
    """Resolve arredondamentos sobre obstáculos escolhendo a célula livre mais próxima."""

    if is_traversable(position, terrain, obstacle_mask):
        return position
    rows, columns = terrain.shape
    for radius in range(1, max(rows, columns)):
        candidates = []
        for row in range(max(0, position[0] - radius), min(rows, position[0] + radius + 1)):
            for column in range(
                max(0, position[1] - radius), min(columns, position[1] + radius + 1)
            ):
                if max(abs(row - position[0]), abs(column - position[1])) != radius:
                    continue
                candidate = (row, column)
                if is_traversable(candidate, terrain, obstacle_mask):
                    candidates.append(candidate)
        if candidates:
            return min(
                candidates,
                key=lambda item: (
                    (item[0] - position[0]) ** 2 + (item[1] - position[1]) ** 2,
                    item,
                ),
            )
    raise ValueError("Não existe célula navegável no terreno.")
