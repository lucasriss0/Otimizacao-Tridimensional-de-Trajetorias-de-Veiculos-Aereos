import argparse
import csv
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import ceil, dist, pi, sin
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from src.astar import Position
from src.coverage import (
    generate_boustrophedon_targets,
    plan_boustrophedon_coverage,
    replan_remaining_targets,
)
from src.obstacles import create_obstacle_mask
from src.scenario import MissionScenario, load_scenario
from src.terrain import load_topodata
from src.waypoints import (
    grid_path_to_waypoints_3d,
    local_xy_to_grid,
    nearest_traversable_grid_position,
)
from src.wind import WindEvent, WindVector


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


@dataclass(frozen=True)
class TelemetrySample:
    simulation_time_s: float
    route_revision: int
    route_index: int
    completed_targets: int
    drone_x_m: float
    drone_y_m: float
    drone_z_m: float
    target_x_m: float
    target_y_m: float
    target_z_m: float
    tracking_error_m: float
    wind_event: str
    wind_east_mps: float
    wind_north_mps: float
    clearance_m: float
    clearance_violation: bool
    collision: bool


@dataclass(frozen=True)
class ReplanEvent:
    simulation_time_s: float
    wind_event: str
    route_revision: int
    start_row: int
    start_column: int
    remaining_targets: int
    path_points: int
    success: bool
    normalized_cost: float
    error: str | None = None


@dataclass
class SimulationLog:
    success: bool
    scenario_id: str
    waypoints_completed: int
    targets_completed: int
    simulation_steps: int
    route_revisions: int
    telemetry: list[TelemetrySample]
    replan_events: list[ReplanEvent]
    routes: list[list[Position]]
    collisions: int = 0
    clearance_violations: int = 0
    error: str | None = None
    output_directory: Path | None = None


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
        object_handle = (
            discover_target(sim, "auto")
            if object_path == "auto"
            else sim.getObject(object_path)
        )
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


def _all_scene_handles(sim: object) -> list[int]:
    return list(sim.getObjectsInTree(sim.handle_scene, sim.handle_all, 0))


def _object_path(sim: object, handle: int) -> str:
    try:
        return str(sim.getObjectAlias(handle, 1))
    except Exception:
        return str(sim.getObjectAlias(handle))


def discover_target(sim: object, configured_path: str = "auto") -> int:
    """Localiza o target antes de o script do quadricóptero reparentá-lo."""

    if configured_path != "auto":
        return int(sim.getObject(configured_path))
    candidates: list[tuple[int, str]] = []
    for handle in _all_scene_handles(sim):
        alias = str(sim.getObjectAlias(handle)).lstrip("/")
        if alias.lower() == "target":
            candidates.append((handle, _object_path(sim, handle)))
    if not candidates:
        for fallback in ("/target", "/Drone/target", "/Quadcopter/target", "/DroneTarget"):
            try:
                return int(sim.getObject(fallback))
            except Exception:
                pass
        raise RuntimeError("Target do drone não encontrado na cena.")
    candidates.sort(key=lambda item: ("/Drone/" not in item[1], len(item[1])))
    return int(candidates[0][0])


def discover_drone(sim: object, configured_path: str = "/Drone") -> int:
    try:
        return int(sim.getObject(configured_path))
    except Exception:
        for path in ("/Quadcopter", "/Drone"):
            try:
                return int(sim.getObject(path))
            except Exception:
                pass
    raise RuntimeError("Drone não encontrado na cena.")


def discover_dynamic_body(sim: object, drone_handle: int, configured_path: str = "auto") -> int | None:
    if configured_path != "auto":
        return int(sim.getObject(configured_path))
    # No Quadcopter.ttm oficial, a shape raiz é o corpo central dinâmico. As
    # shapes chamadas "body" pertencem às hélices; aplicar força nelas produz
    # torque em vez de uma translação lateral limpa.
    try:
        if (
            sim.getObjectType(drone_handle) == sim.sceneobject_shape
            and bool(sim.isDynamicallyEnabled(drone_handle))
        ):
            return int(drone_handle)
    except Exception:
        pass
    candidates = []
    for handle in sim.getObjectsInTree(drone_handle, sim.handle_all, 0):
        try:
            if sim.getObjectType(handle) != sim.sceneobject_shape:
                continue
            if bool(sim.isDynamicallyEnabled(handle)):
                alias = str(sim.getObjectAlias(handle)).lower()
                priority = 0 if "respondable" in alias else 1
                candidates.append((priority, handle))
        except Exception:
            continue
    return int(min(candidates)[1]) if candidates else None


def _route_scene_positions(
    terrain: np.ndarray,
    path: list[Position],
    cell_size_x_m: float,
    cell_size_y_m: float,
    clearance_m: float,
    scale: float,
) -> list[Position3D]:
    return [
        (item.x_m * scale, item.y_m * scale, item.z_m * scale)
        for item in grid_path_to_waypoints_3d(
            terrain, path, cell_size_x_m, cell_size_y_m, clearance_m
        )
    ]


def _draw_route(
    sim: object, positions: list[Position3D], highlighted: bool
) -> int | None:
    if len(positions) < 2:
        return None
    try:
        color = [1.0, 0.25, 0.05] if highlighted else [0.45, 0.45, 0.45]
        drawing = sim.addDrawingObject(
            sim.drawing_lines, 3.0, 0.0, sim.handle_world, len(positions) * 2, color
        )
        for start, goal in zip(positions, positions[1:]):
            sim.addDrawingObjectItem(drawing, [*start, *goal])
        return int(drawing)
    except Exception:
        return None


def _draw_wind(
    sim: object,
    wind: WindVector,
    origin: Position3D,
    previous_handle: int | None,
) -> int | None:
    try:
        if wind.speed_mps <= 1e-12:
            if previous_handle is not None:
                sim.addDrawingObjectItem(previous_handle, None)
            return previous_handle
        # A mesma seta é atualizada no referencial global para acompanhar o
        # drone sem herdar sua rotação e sem acumular objetos de desenho.
        drawing = previous_handle
        if drawing is None:
            drawing = sim.addDrawingObject(
                sim.drawing_lines, 5.0, 0.0, sim.handle_world, 3, [0.0, 0.65, 1.0]
            )
        else:
            sim.addDrawingObjectItem(drawing, None)
        direction_x = wind.east_mps / wind.speed_mps
        direction_y = wind.north_mps / wind.speed_mps
        perpendicular_x = -direction_y
        perpendicular_y = direction_x
        # Mostra direção e intensidade sem deixar a seta dominar a cena.
        arrow_length = 0.35 + min(wind.speed_mps, 20.0) * 0.025
        arrow_head_length = 0.14
        arrow_head_width = 0.10
        base_z = origin[2] + 0.22
        start = [origin[0], origin[1], base_z]
        end = [
            start[0] + direction_x * arrow_length,
            start[1] + direction_y * arrow_length,
            base_z,
        ]
        left = [
            end[0] - direction_x * arrow_head_length + perpendicular_x * arrow_head_width,
            end[1] - direction_y * arrow_head_length + perpendicular_y * arrow_head_width,
            base_z,
        ]
        right = [
            end[0] - direction_x * arrow_head_length - perpendicular_x * arrow_head_width,
            end[1] - direction_y * arrow_head_length - perpendicular_y * arrow_head_width,
            base_z,
        ]
        sim.addDrawingObjectItem(drawing, [*start, *end])
        sim.addDrawingObjectItem(drawing, [*end, *left])
        sim.addDrawingObjectItem(drawing, [*end, *right])
        return int(drawing)
    except Exception:
        return previous_handle


def _apply_visual_wind_force(
    sim: object,
    body_handle: int | None,
    wind: WindVector,
    scenario: MissionScenario,
    event_elapsed_s: float,
) -> None:
    if (
        body_handle is None
        or not scenario.simulation.apply_visual_force
        or wind.speed_mps <= 1e-12
    ):
        return
    try:
        mass = float(sim.getShapeMass(body_handle))
        base_acceleration = min(
            scenario.wind.maximum_visual_acceleration,
            scenario.wind.visual_acceleration_gain * wind.speed_mps,
        )
        # A pulsação de ±10% mantém o efeito visível. Ela já começa em 90% no
        # instante do evento; o limite configurado evita um tranco excessivo.
        pulse = 0.9 + 0.1 * sin(2 * pi * event_elapsed_s / 4.0)
        acceleration = base_acceleration * pulse
        force = [
            mass * acceleration * wind.east_mps / wind.speed_mps,
            mass * acceleration * wind.north_mps / wind.speed_mps,
            0.0,
        ]
        sim.addForceAndTorque(body_handle, force, None)
    except Exception:
        # A perturbação é visual e não deve invalidar o planejador/log principal.
        return


def _check_collision(sim: object, drone_handle: int, terrain_handle: int | None) -> bool:
    if terrain_handle is None:
        return False
    try:
        result = sim.checkCollision(drone_handle, terrain_handle)
        if isinstance(result, (tuple, list)):
            result = result[0] if result else 0
        return int(result) > 0
    except Exception:
        return False


def _save_simulation_log(
    log: SimulationLog,
    scenario: MissionScenario,
    scenario_path: Path,
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = scenario.output_root / f"{scenario.scenario_id}_{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(scenario_path, destination / "scenario.yaml")

    if log.telemetry:
        with (destination / "telemetry.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(asdict(log.telemetry[0]).keys()))
            writer.writeheader()
            writer.writerows(asdict(item) for item in log.telemetry)
        with (destination / "actual_trajectory.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(["simulation_time_s", "x_m", "y_m", "z_m"])
            writer.writerows(
                (
                    item.simulation_time_s,
                    item.drone_x_m,
                    item.drone_y_m,
                    item.drone_z_m,
                )
                for item in log.telemetry
            )
    (destination / "events.json").write_text(
        json.dumps([asdict(item) for item in log.replan_events], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics = {
        "scenario_id": log.scenario_id,
        "success": log.success,
        "waypoints_completed": log.waypoints_completed,
        "targets_completed": log.targets_completed,
        "simulation_steps": log.simulation_steps,
        "route_revisions": log.route_revisions,
        "collisions": log.collisions,
        "clearance_violations": log.clearance_violations,
        "maximum_tracking_error_m": max(
            (item.tracking_error_m for item in log.telemetry), default=0.0
        ),
        "mean_tracking_error_m": (
            sum(item.tracking_error_m for item in log.telemetry) / len(log.telemetry)
            if log.telemetry
            else 0.0
        ),
        "error": log.error or "",
    }
    with (destination / "metrics.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics))
        writer.writeheader()
        writer.writerow(metrics)
    for revision, route in enumerate(log.routes):
        with (destination / f"route_{revision:02d}.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(["sequence", "grid_row", "grid_column"])
            writer.writerows((index, *position) for index, position in enumerate(route))
    log.output_directory = destination
    return destination


def run_wind_mission(
    scenario: MissionScenario,
    terrain: np.ndarray,
    targets: list[Position],
    initial_path: list[Position],
    scenario_path: Path,
    host: str = "localhost",
    port: int = 23000,
    client_factory: Callable[..., object] | None = None,
) -> SimulationLog:
    """Executa, mede e replaneja uma missão determinística em stepping mode."""

    telemetry: list[TelemetrySample] = []
    replan_events: list[ReplanEvent] = []
    routes = [initial_path.copy()]
    log = SimulationLog(
        False, scenario.scenario_id, 0, 0, 0, 0, telemetry, replan_events, routes
    )
    cell_x = scenario.terrain.area_m / terrain.shape[1]
    cell_y = scenario.terrain.area_m / terrain.shape[0]
    scale = scenario.simulation.scale
    obstacle_mask = create_obstacle_mask(
        terrain.shape, list(scenario.obstacles), cell_x, cell_y
    )
    try:
        if client_factory is None:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient

            client_factory = RemoteAPIClient
        client = client_factory(host=host, port=port)
        sim = client.require("sim")
        if sim.getSimulationState() != sim.simulation_stopped:
            raise RuntimeError("A simulação precisa estar parada antes da missão.")
        target_handle = discover_target(sim, scenario.simulation.target)
        drone_handle = discover_drone(sim, scenario.simulation.drone)
        body_handle = discover_dynamic_body(sim, drone_handle, scenario.simulation.body)
        try:
            terrain_handle = int(sim.getObject("/AgriculturalTerrain"))
        except Exception:
            terrain_handle = None
        collision_handles = [terrain_handle] if terrain_handle is not None else []
        for obstacle in scenario.obstacles:
            try:
                model_handle = int(sim.getObject(f"/{obstacle.name}"))
            except Exception as exc:
                raise RuntimeError(
                    f"Obstáculo /{obstacle.name} não existe na cena. "
                    "Reconstrua a cena com src.coppelia_scene."
                ) from exc
            try:
                shapes = [
                    int(handle)
                    for handle in sim.getObjectsInTree(
                        model_handle, sim.sceneobject_shape, 0
                    )
                ]
            except Exception:
                shapes = []
            collision_handles.extend(shapes or [model_handle])

        route = initial_path.copy()
        route_positions = _route_scene_positions(
            terrain, route, cell_x, cell_y, scenario.coverage.clearance_m, scale
        )
        if not route_positions:
            raise RuntimeError("A rota inicial não contém posições executáveis.")

        # Não dependemos do reset implícito do Coppelia: uma missão sempre
        # começa no primeiro waypoint, mesmo depois de uma execução abortada.
        start_position = list(route_positions[0])
        sim.setObjectPosition(drone_handle, start_position, sim.handle_world)
        sim.setObjectPosition(target_handle, start_position, sim.handle_world)
        try:
            sim.setObjectOrientation(
                drone_handle, [0.0, 0.0, 0.0], sim.handle_world
            )
        except Exception:
            pass

        sim.setStepping(True)
        sim.startSimulation()
        time_step = float(sim.getSimulationTimeStep())
        if time_step <= 0:
            raise RuntimeError("O passo de tempo do simulador é inválido.")
        active_event = scenario.wind.active_event(0.0)
        next_event_index = scenario.wind.next_event_index(0.0)
        try:
            sim.removeDrawingObject(sim.handle_all)
        except Exception:
            pass
        active_route_drawing = _draw_route(sim, route_positions, True)
        initial_drone_scene = tuple(
            float(value)
            for value in sim.getObjectPosition(drone_handle, sim.handle_world)
        )
        wind_drawing = _draw_wind(
            sim, active_event.wind, initial_drone_scene, None
        )
        print(
            f"[VENTO t=0,0s] {active_event.name}: "
            f"leste={active_event.wind.east_mps:.1f} m/s, "
            f"norte={active_event.wind.north_mps:.1f} m/s",
            flush=True,
        )
        route_index = 0
        completed_targets = 0
        revision = 0
        simulation_start = float(sim.getSimulationTime())
        collision_samples = 0
        clearance_samples = 0
        replan_requested = False
        pending_replan_at_s: float | None = None
        wind_started_at_s: float | None = None

        def step_once(target_position: Position3D) -> None:
            nonlocal active_event, next_event_index, revision, route, route_positions
            nonlocal route_index, replan_requested, collision_samples, clearance_samples
            nonlocal active_route_drawing, wind_drawing
            nonlocal pending_replan_at_s
            nonlocal wind_started_at_s
            commanded_target = list(target_position)
            if (
                pending_replan_at_s is not None
                and wind_started_at_s is not None
                and active_event.wind.speed_mps > 1e-12
                and scenario.wind.maximum_drift_m > 0
            ):
                drift_progress = min(
                    1.0,
                    max(0.0, float(sim.getSimulationTime()) - wind_started_at_s)
                    / max(scenario.wind.replan_delay_s, 1e-9),
                )
                drift_scene = (
                    scenario.wind.maximum_drift_m * scale * drift_progress
                )
                commanded_target[0] += (
                    drift_scene * active_event.wind.east_mps
                    / active_event.wind.speed_mps
                )
                commanded_target[1] += (
                    drift_scene * active_event.wind.north_mps
                    / active_event.wind.speed_mps
                )
            sim.setObjectPosition(target_handle, commanded_target, sim.handle_world)
            event_elapsed = float(sim.getSimulationTime()) - active_event.at_s
            _apply_visual_wind_force(
                sim,
                body_handle,
                active_event.wind,
                scenario,
                event_elapsed,
            )
            sim.step()
            log.simulation_steps += 1
            now = float(sim.getSimulationTime())
            drone_scene = tuple(
                float(value) for value in sim.getObjectPosition(drone_handle, sim.handle_world)
            )
            if log.simulation_steps % 4 == 0:
                wind_drawing = _draw_wind(
                    sim, active_event.wind, drone_scene, wind_drawing
                )
            target_scene = tuple(
                float(value) for value in sim.getObjectPosition(target_handle, sim.handle_world)
            )
            drone_m = tuple(value / scale for value in drone_scene)
            target_m = tuple(value / scale for value in target_scene)
            tracking_error = dist(drone_m, target_m)
            grid = local_xy_to_grid(drone_m[0], drone_m[1], terrain.shape, cell_x, cell_y)
            ground_m = float(terrain[grid] - np.min(terrain))
            clearance = drone_m[2] - ground_m
            clearance_violation = clearance < scenario.simulation.minimum_clearance_m
            collision = any(
                _check_collision(sim, drone_handle, handle)
                for handle in collision_handles
            )
            collision_samples += int(collision)
            clearance_samples += int(clearance_violation)
            telemetry.append(
                TelemetrySample(
                    now,
                    revision,
                    route_index,
                    completed_targets,
                    *drone_m,
                    *target_m,
                    tracking_error,
                    active_event.name,
                    active_event.wind.east_mps,
                    active_event.wind.north_mps,
                    clearance,
                    clearance_violation,
                    collision,
                )
            )
            if now - simulation_start > scenario.simulation.global_timeout_s:
                raise TimeoutError("Tempo limite global da missão excedido.")

            if (
                next_event_index < len(scenario.wind.events)
                and now >= scenario.wind.events[next_event_index].at_s
            ):
                active_event = scenario.wind.events[next_event_index]
                next_event_index += 1
                print(
                    f"[VENTO t={now:.1f}s] {active_event.name}: "
                    f"leste={active_event.wind.east_mps:.1f} m/s, "
                    f"norte={active_event.wind.north_mps:.1f} m/s; "
                    f"replanejamento em {scenario.wind.replan_delay_s:.1f}s...",
                    flush=True,
                )
                pending_replan_at_s = now + scenario.wind.replan_delay_s
                wind_started_at_s = now
                wind_drawing = _draw_wind(
                    sim, active_event.wind, drone_scene, wind_drawing
                )

            if pending_replan_at_s is not None and now >= pending_replan_at_s:
                current = nearest_traversable_grid_position(
                    grid, terrain, obstacle_mask
                )
                remaining = targets[completed_targets:]
                planned = replan_remaining_targets(
                    terrain,
                    current,
                    remaining,
                    scenario.coverage.climb_weight,
                    cell_x,
                    cell_y,
                    obstacle_mask,
                    active_event.wind,
                    scenario.wind.cost,
                )
                revision += 1
                pending_replan_at_s = None
                wind_started_at_s = None
                replan_events.append(
                    ReplanEvent(
                        now,
                        active_event.name,
                        revision,
                        current[0],
                        current[1],
                        len(remaining),
                        len(planned.path),
                        planned.success,
                        planned.total_cost,
                        planned.error,
                    )
                )
                if not planned.success:
                    raise RuntimeError(f"Replanejamento falhou: {planned.error}")
                if active_route_drawing is not None:
                    try:
                        sim.removeDrawingObject(active_route_drawing)
                    except Exception:
                        pass
                _draw_route(sim, route_positions, False)
                route = planned.path
                routes.append(route.copy())
                route_positions = _route_scene_positions(
                    terrain,
                    route,
                    cell_x,
                    cell_y,
                    scenario.coverage.clearance_m,
                    scale,
                )
                active_route_drawing = _draw_route(sim, route_positions, True)
                wind_drawing = _draw_wind(
                    sim, active_event.wind, drone_scene, wind_drawing
                )
                route_index = 0
                replan_requested = True
                print(
                    f"[ROTA revisão={revision}] {len(planned.path)} células, "
                    f"{len(remaining)} alvos restantes",
                    flush=True,
                )

        try:
            current_target = tuple(
                float(value) for value in sim.getObjectPosition(target_handle, sim.handle_world)
            )
            for _ in range(ceil(scenario.simulation.warmup_s / time_step)):
                step_once(current_target)

            maximum_step = scenario.simulation.speed_mps * scale * time_step
            while route_index < len(route_positions):
                replan_requested = False
                goal = route_positions[route_index]
                current_target = tuple(
                    float(value)
                    for value in sim.getObjectPosition(target_handle, sim.handle_world)
                )
                waypoint_started = float(sim.getSimulationTime())
                for interpolated in interpolate_segment(current_target, goal, maximum_step):
                    step_once(interpolated)
                    if replan_requested:
                        break
                if replan_requested:
                    continue

                while True:
                    step_once(goal)
                    if replan_requested:
                        break
                    drone_position = tuple(
                        float(value)
                        for value in sim.getObjectPosition(drone_handle, sim.handle_world)
                    )
                    if dist(drone_position, goal) <= scenario.simulation.tolerance_m * scale:
                        break
                    if float(sim.getSimulationTime()) - waypoint_started > scenario.simulation.waypoint_timeout_s:
                        raise TimeoutError(
                            f"Timeout aguardando o drone no waypoint {route_index}."
                        )
                if replan_requested:
                    continue

                reached_cell = route[route_index]
                if completed_targets < len(targets) and reached_cell == targets[completed_targets]:
                    completed_targets += 1
                route_index += 1
                log.waypoints_completed += 1

            log.success = completed_targets >= len(targets)
            if not log.success:
                log.error = "A rota terminou antes de todos os alvos de cobertura."
        finally:
            log.targets_completed = completed_targets
            log.route_revisions = revision
            log.collisions = collision_samples
            log.clearance_violations = clearance_samples
            try:
                if sim.getSimulationState() != sim.simulation_stopped:
                    sim.stopSimulation()
            except Exception as stop_error:
                if log.error is None:
                    log.error = f"Falha ao confirmar parada da simulação: {stop_error}"
            try:
                sim.removeDrawingObject(sim.handle_all)
            except Exception:
                pass
    except Exception as exc:
        log.error = str(exc)
    finally:
        _save_simulation_log(log, scenario, scenario_path)
    return log


def prepare_scenario_route(scenario: MissionScenario) -> tuple[np.ndarray, list[Position], list[Position]]:
    terrain_data = load_topodata(
        scenario.terrain.topodata,
        scenario.terrain.size,
        scenario.terrain.center_lat,
        scenario.terrain.center_lon,
        scenario.terrain.area_m,
    )
    terrain = terrain_data.elevation
    cell_x = scenario.terrain.area_m / terrain.shape[1]
    cell_y = scenario.terrain.area_m / terrain.shape[0]
    spacing = max(1, round(scenario.coverage.swath_m / cell_y))
    obstacle_mask = create_obstacle_mask(
        terrain.shape, list(scenario.obstacles), cell_x, cell_y
    )
    targets = generate_boustrophedon_targets(
        terrain, spacing, scenario.coverage.window
    )
    targets = [target for target in targets if not obstacle_mask[target]]
    initial_wind = scenario.wind.active_event(0.0).wind
    coverage = plan_boustrophedon_coverage(
        terrain,
        scenario.coverage.swath_m,
        scenario.coverage.climb_weight,
        cell_x,
        cell_y,
        obstacle_mask,
        scenario.coverage.window,
        initial_wind,
        scenario.wind.cost,
    )
    if not coverage.success:
        raise RuntimeError(coverage.error)
    return terrain, targets, coverage.path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa waypoints 3D no CoppeliaSim.")
    parser.add_argument("--scenario", type=Path, help="Cenário YAML com missão e vento.")
    parser.add_argument("--csv", type=Path, default=Path("output/waypoints_coppeliasim.csv"))
    parser.add_argument("--object", default="auto", help="Caminho do alvo ou 'auto'.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--scale", type=float, help="Escala uniforme metros→cena.")
    parser.add_argument("--speed", type=float, help="Velocidade real em m/s.")
    parser.add_argument(
        "--warmup-s", type=float,
        help="Tempo inicial para estabilização do drone.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Valida sem conectar ao simulador.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.scenario:
        from dataclasses import replace

        scenario = load_scenario(args.scenario)
        simulation = scenario.simulation
        if args.scale is not None:
            simulation = replace(simulation, scale=args.scale)
        if args.speed is not None:
            simulation = replace(simulation, speed_mps=args.speed)
        if args.warmup_s is not None:
            simulation = replace(simulation, warmup_s=args.warmup_s)
        if args.object != "auto":
            simulation = replace(simulation, target=args.object)
        scenario = replace(scenario, simulation=simulation)
        terrain, targets, initial_path = prepare_scenario_route(scenario)
        print(f"Cenário: {scenario.scenario_id}")
        print(f"Alvos de cobertura: {len(targets)}")
        print(f"Pontos da rota inicial: {len(initial_path)}")
        print(f"Velocidade real: {scenario.simulation.speed_mps:.2f} m/s")
        if args.dry_run:
            print("Cenário validado; nenhuma conexão foi realizada (--dry-run).")
            return
        result = run_wind_mission(
            scenario, terrain, targets, initial_path, args.scenario, args.host, args.port
        )
        if not result.success:
            raise RuntimeError(
                f"Missão falhou: {result.error}. Logs: {result.output_directory}"
            )
        print("Missão com vento concluída!")
        print(f"Alvos concluídos: {result.targets_completed}/{len(targets)}")
        print(f"Replanejamentos: {result.route_revisions}")
        print(f"Logs: {result.output_directory}")
        return

    scale = 0.01 if args.scale is None else args.scale
    speed_mps = 2.0 if args.speed is None else args.speed
    warmup_s = 2.0 if args.warmup_s is None else args.warmup_s
    positions = load_waypoint_positions(args.csv, scale)
    print(f"Waypoints carregados: {len(positions)}")
    print(f"Primeiro waypoint: {positions[0]}")
    print(f"Último waypoint: {positions[-1]}")
    if args.dry_run:
        print("Validação concluída; nenhuma conexão foi realizada (--dry-run).")
        return

    result = run_simulation(
        positions,
        args.object,
        speed_mps * scale,
        args.host,
        args.port,
        warmup_s,
    )
    if not result.success:
        raise RuntimeError(result.error)
    print("Simulação concluída!")
    print(f"Waypoints concluídos: {result.waypoints_completed}")
    print(f"Passos de simulação: {result.simulation_steps}")
    print(f"Distância na cena: {result.simulated_distance:.2f}")


if __name__ == "__main__":
    main()
