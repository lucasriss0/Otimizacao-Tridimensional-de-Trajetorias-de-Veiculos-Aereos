import argparse
import csv
from dataclasses import dataclass
from math import ceil, dist
from pathlib import Path
from typing import Callable, Protocol


Position3D = tuple[float, float, float]


class SimAPI(Protocol):
    handle_world: int
    def getObject(self, path: str) -> int: ...
    def getObjectPosition(self, handle: int, relative_to: int) -> list[float]: ...
    def setObjectPosition(self, handle: int, position: list[float], relative_to: int) -> None: ...
    def getSimulationTimeStep(self) -> float: ...
    def setStepping(self, enabled: bool) -> None: ...
    def startSimulation(self) -> None: ...
    def stopSimulation(self) -> None: ...
    def step(self) -> None: ...


@dataclass(frozen=True)
class SimulationResult:
    success: bool
    waypoints_completed: int
    simulation_steps: int
    simulated_distance: float
    error: str | None = None


def load_waypoint_positions(
    csv_path: str | Path, scale: float = 0.01
) -> list[Position3D]:
    """Lê o CSV em metros e aplica a escala visual usada na cena."""
    if scale <= 0:
        raise ValueError("A escala da simulação precisa ser positiva.")
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de waypoints não encontrado: {path}")

    positions = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"x_m", "y_m", "z_m"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("O CSV precisa conter as colunas x_m, y_m e z_m.")
        for row_number, row in enumerate(reader, start=2):
            try:
                position = tuple(float(row[name]) * scale for name in ("x_m", "y_m", "z_m"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Coordenada inválida na linha {row_number}.") from exc
            positions.append(position)
    if not positions:
        raise ValueError("O CSV não contém waypoints.")
    return positions


def interpolate_segment(
    start: Position3D,
    goal: Position3D,
    maximum_step_distance: float,
) -> list[Position3D]:
    """Cria posições intermediárias para movimento contínuo e determinístico."""
    if maximum_step_distance <= 0:
        raise ValueError("A distância máxima por passo precisa ser positiva.")
    segment_distance = dist(start, goal)
    if segment_distance <= 1e-12:
        return []
    steps = ceil(segment_distance / maximum_step_distance)
    return [
        tuple(start[axis] + (goal[axis] - start[axis]) * index / steps for axis in range(3))
        for index in range(1, steps + 1)
    ]


def run_simulation(
    positions: list[Position3D],
    object_path: str = "/DroneTarget",
    speed: float = 2.0,
    host: str = "localhost",
    port: int = 23000,
    warmup_seconds: float = 2.0,
    client_factory: Callable[..., object] | None = None,
) -> SimulationResult:
    """Move um alvo da cena em modo sincronizado através dos waypoints."""
    if not positions:
        return SimulationResult(False, 0, 0, 0.0, "Nenhum waypoint recebido.")
    if speed <= 0:
        return SimulationResult(False, 0, 0, 0.0, "A velocidade precisa ser positiva.")
    if warmup_seconds < 0:
        return SimulationResult(False, 0, 0, 0.0, "O tempo de estabilização não pode ser negativo.")

    try:
        if client_factory is None:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
            client_factory = RemoteAPIClient
        client = client_factory(host=host, port=port)
        sim: SimAPI = client.require("sim")
        object_handle = sim.getObject(object_path)
        world = sim.handle_world
        sim.setStepping(True)
        sim.startSimulation()

        simulation_steps = 0
        completed = 0
        traveled = 0.0
        try:
            time_step = float(sim.getSimulationTimeStep())
            if time_step <= 0:
                raise RuntimeError("O passo de tempo do simulador é inválido.")

            # Permite que sysCall_init desacople o target e que o drone estabilize.
            warmup_steps = ceil(warmup_seconds / time_step)
            for _ in range(warmup_steps):
                sim.step()
                simulation_steps += 1

            current_values = sim.getObjectPosition(object_handle, world)
            current: Position3D = tuple(float(value) for value in current_values)
            maximum_step_distance = speed * time_step
            # Inclui o primeiro waypoint: o alvo chega até ele progressivamente.
            for goal in positions:
                traveled += dist(current, goal)
                for interpolated in interpolate_segment(current, goal, maximum_step_distance):
                    sim.setObjectPosition(object_handle, list(interpolated), world)
                    sim.step()
                    simulation_steps += 1
                current = goal
                completed += 1
        finally:
            sim.stopSimulation()

        return SimulationResult(True, completed, simulation_steps, traveled)
    except ImportError:
        return SimulationResult(
            False, 0, 0, 0.0,
            "Cliente ZeroMQ ausente. Instale com: python -m pip install coppeliasim-zmqremoteapi-client",
        )
    except Exception as exc:
        return SimulationResult(
            False, 0, 0, 0.0,
            f"Falha na integração com o CoppeliaSim: {exc}",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa waypoints 3D no CoppeliaSim.")
    parser.add_argument("--csv", type=Path, default=Path("output/waypoints_coppeliasim.csv"))
    parser.add_argument("--object", default="/DroneTarget", help="Caminho do alvo na cena.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--scale", type=float, default=0.01, help="Escala metros/cena.")
    parser.add_argument("--speed", type=float, default=2.0, help="Velocidade em unidades da cena/s.")
    parser.add_argument(
        "--warmup-s", type=float, default=2.0,
        help="Tempo inicial para estabilização do drone (padrão: 2 s).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Valida sem conectar ao simulador.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    positions = load_waypoint_positions(args.csv, args.scale)
    print(f"Waypoints carregados: {len(positions)}")
    print(f"Primeiro waypoint: {positions[0]}")
    print(f"Último waypoint: {positions[-1]}")
    if args.dry_run:
        print("Validação concluída; nenhuma conexão foi realizada (--dry-run).")
        return

    result = run_simulation(
        positions, args.object, args.speed, args.host, args.port, args.warmup_s
    )
    if not result.success:
        raise RuntimeError(result.error)
    print("Simulação concluída!")
    print(f"Waypoints concluídos: {result.waypoints_completed}")
    print(f"Passos de simulação: {result.simulation_steps}")
    print(f"Distância na cena: {result.simulated_distance:.2f}")


if __name__ == "__main__":
    main()
