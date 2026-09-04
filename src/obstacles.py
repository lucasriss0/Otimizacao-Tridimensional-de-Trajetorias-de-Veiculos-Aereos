from dataclasses import dataclass
from math import hypot
from pathlib import Path
import json

import numpy as np


@dataclass(frozen=True)
class StaticObstacle:
    x_m: float
    y_m: float
    safety_radius_m: float
    name: str = "obstaculo"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("O obstáculo precisa ter um nome.")
        if self.safety_radius_m <= 0:
            raise ValueError("O raio de segurança precisa ser positivo.")


def parse_obstacle_spec(specification: str) -> StaticObstacle:
    """Interpreta NAME,X_M,Y_M,RAIO_M informado pela linha de comando."""
    parts = [part.strip() for part in specification.split(",")]
    if len(parts) != 4:
        raise ValueError(
            "Obstáculo deve usar o formato NOME,X_M,Y_M,RAIO_M."
        )
    name = parts[0]
    try:
        x_m, y_m, radius_m = map(float, parts[1:])
    except ValueError as exc:
        raise ValueError("As coordenadas e o raio do obstáculo devem ser números.") from exc
    if not name:
        raise ValueError("O obstáculo precisa ter um nome.")
    if radius_m <= 0:
        raise ValueError("O raio de segurança precisa ser positivo.")
    return StaticObstacle(x_m, y_m, radius_m, name)


def create_obstacle_mask(
    terrain_shape: tuple[int, int],
    obstacles: list[StaticObstacle],
    cell_size_x_m: float,
    cell_size_y_m: float,
) -> np.ndarray:
    """Marca células cujo centro está dentro do raio de cada obstáculo."""
    if cell_size_x_m <= 0 or cell_size_y_m <= 0:
        raise ValueError("O tamanho das células precisa ser positivo.")
    rows, columns = terrain_shape
    mask = np.zeros(terrain_shape, dtype=bool)
    center_row = (rows - 1) / 2
    center_column = (columns - 1) / 2

    for row in range(rows):
        y_m = (center_row - row) * cell_size_y_m
        for column in range(columns):
            x_m = (column - center_column) * cell_size_x_m
            mask[row, column] = any(
                hypot(x_m - item.x_m, y_m - item.y_m)
                <= item.safety_radius_m
                for item in obstacles
            )
    return mask


def save_obstacles_json(
    obstacles: list[StaticObstacle], output_path: str | Path
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "name": item.name,
            "x_m": item.x_m,
            "y_m": item.y_m,
            "safety_radius_m": item.safety_radius_m,
        }
        for item in obstacles
    ]
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destination


def load_obstacles_json(input_path: str | Path) -> list[StaticObstacle]:
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de obstáculos não encontrado: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            StaticObstacle(
                float(item["x_m"]),
                float(item["y_m"]),
                float(item["safety_radius_m"]),
                str(item["name"]),
            )
            for item in payload
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Arquivo de obstáculos inválido.") from exc
