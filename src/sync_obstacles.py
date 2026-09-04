import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.obstacles import StaticObstacle, save_obstacles_json


@dataclass(frozen=True)
class ObstacleSyncResult:
    success: bool
    obstacles: list[StaticObstacle]
    error: str | None = None


def read_obstacles_from_coppeliasim(
    alias_prefix: str = "Obstacle",
    scale: float = 0.01,
    safety_margin_m: float = 30.0,
    default_radius_m: float = 15.0,
    host: str = "localhost",
    port: int = 23000,
    client_factory: Callable[..., object] | None = None,
) -> ObstacleSyncResult:
    """Busca objetos por prefixo e converte posição/tamanho da cena para metros."""
    if not alias_prefix:
        return ObstacleSyncResult(False, [], "O prefixo não pode ser vazio.")
    if scale <= 0 or safety_margin_m < 0 or default_radius_m <= 0:
        return ObstacleSyncResult(False, [], "Escala e raios informados são inválidos.")
    try:
        if client_factory is None:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
            client_factory = RemoteAPIClient
        client = client_factory(host=host, port=port)
        sim = client.require("sim")
        handles = sim.getObjectsInTree(sim.handle_scene, sim.handle_all, 0)
        obstacles = []
        for handle in handles:
            alias = str(sim.getObjectAlias(handle, -1))
            if not alias.lower().startswith(alias_prefix.lower()):
                continue
            position = sim.getObjectPosition(handle, sim.handle_world)
            physical_radius_m = default_radius_m
            try:
                size, _ = sim.getShapeBB(handle)
                physical_radius_m = max(float(size[0]), float(size[1])) / (2 * scale)
            except Exception:
                pass
            obstacles.append(
                StaticObstacle(
                    x_m=float(position[0]) / scale,
                    y_m=float(position[1]) / scale,
                    safety_radius_m=physical_radius_m + safety_margin_m,
                    name=alias,
                )
            )
        if not obstacles:
            return ObstacleSyncResult(
                False, [], f"Nenhum objeto com prefixo '{alias_prefix}' foi encontrado."
            )
        return ObstacleSyncResult(True, obstacles)
    except ImportError:
        return ObstacleSyncResult(False, [], "Cliente ZeroMQ não está instalado.")
    except Exception as exc:
        return ObstacleSyncResult(
            False, [], f"Falha ao ler obstáculos do CoppeliaSim: {exc}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sincroniza obstáculos do CoppeliaSim.")
    parser.add_argument("--prefix", default="Obstacle")
    parser.add_argument("--scale", type=float, default=0.01)
    parser.add_argument("--margin-m", type=float, default=30.0)
    parser.add_argument("--default-radius-m", type=float, default=15.0)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--output", type=Path, default=Path("output/obstacles_coppelia.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = read_obstacles_from_coppeliasim(
        args.prefix, args.scale, args.margin_m, args.default_radius_m,
        args.host, args.port,
    )
    if not result.success:
        raise RuntimeError(result.error)
    destination = save_obstacles_json(result.obstacles, args.output)
    print(f"Obstáculos encontrados: {len(result.obstacles)}")
    for item in result.obstacles:
        print(
            f"- {item.name}: x={item.x_m:.2f} m, y={item.y_m:.2f} m, "
            f"raio seguro={item.safety_radius_m:.2f} m"
        )
    print(f"Arquivo salvo em: {destination}")


if __name__ == "__main__":
    main()
