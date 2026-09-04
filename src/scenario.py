from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.coverage import CoverageWindow
from src.obstacles import StaticObstacle
from src.wind import WindCostParameters, WindEvent, WindScenario, WindVector


@dataclass(frozen=True)
class TerrainScenario:
    topodata: Path
    center_lat: float
    center_lon: float
    area_m: float = 1500.0
    size: int = 50


@dataclass(frozen=True)
class CoverageScenario:
    swath_m: float = 120.0
    clearance_m: float = 60.0
    climb_weight: float = 10.0
    window: CoverageWindow | None = None


@dataclass(frozen=True)
class SimulationScenario:
    scale: float = 0.01
    speed_mps: float = 2.0
    warmup_s: float = 5.0
    tolerance_m: float = 8.0
    minimum_clearance_m: float = 55.0
    waypoint_timeout_s: float = 90.0
    global_timeout_s: float = 1200.0
    target: str = "auto"
    drone: str = "/Drone"
    body: str = "auto"
    apply_visual_force: bool = True


@dataclass(frozen=True)
class MissionScenario:
    scenario_id: str
    terrain: TerrainScenario
    coverage: CoverageScenario
    simulation: SimulationScenario
    wind: WindScenario
    obstacles: tuple[StaticObstacle, ...] = ()
    output_root: Path = Path("output/runs")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"A seção '{name}' precisa ser um mapa YAML.")
    return value


def _resolve_project_path(value: str, scenario_path: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    project_candidate = scenario_path.parent.parent / candidate
    return project_candidate if project_candidate.exists() else candidate


def load_scenario(path: str | Path) -> MissionScenario:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Cenário não encontrado: {source}")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    root = _mapping(raw, "raiz")
    terrain_raw = _mapping(root.get("terrain"), "terrain")
    coverage_raw = _mapping(root.get("coverage", {}), "coverage")
    simulation_raw = _mapping(root.get("simulation", {}), "simulation")
    wind_raw = _mapping(root.get("wind"), "wind")
    obstacles_raw = root.get("obstacles", [])
    if not isinstance(obstacles_raw, list):
        raise ValueError("A seção 'obstacles' precisa ser uma lista.")
    obstacles = tuple(
        StaticObstacle(
            x_m=float(item["x_m"]),
            y_m=float(item["y_m"]),
            safety_radius_m=float(item["safety_radius_m"]),
            name=str(item["name"]),
        )
        for item in obstacles_raw
    )

    window_value = coverage_raw.get("window")
    window = None
    if window_value is not None:
        if not isinstance(window_value, list) or len(window_value) != 4:
            raise ValueError("coverage.window deve ser [linha_inicial, coluna_inicial, linha_final, coluna_final].")
        window = CoverageWindow(*(int(value) for value in window_value))

    events_raw = wind_raw.get("events")
    if not isinstance(events_raw, list) or not events_raw:
        raise ValueError("wind.events precisa conter ao menos um evento.")
    events = tuple(
        WindEvent(
            name=str(item["name"]),
            at_s=float(item["at_s"]),
            wind=WindVector(float(item.get("east_mps", 0)), float(item.get("north_mps", 0))),
        )
        for item in events_raw
    )
    cost_raw = _mapping(wind_raw.get("cost", {}), "wind.cost")
    visual_raw = _mapping(wind_raw.get("visual", {}), "wind.visual")

    scenario = MissionScenario(
        scenario_id=str(root.get("id", source.stem)),
        terrain=TerrainScenario(
            topodata=_resolve_project_path(str(terrain_raw["topodata"]), source),
            center_lat=float(terrain_raw["center_lat"]),
            center_lon=float(terrain_raw["center_lon"]),
            area_m=float(terrain_raw.get("area_m", 1500)),
            size=int(terrain_raw.get("size", 50)),
        ),
        coverage=CoverageScenario(
            swath_m=float(coverage_raw.get("swath_m", 120)),
            clearance_m=float(coverage_raw.get("clearance_m", 60)),
            climb_weight=float(coverage_raw.get("climb_weight", 10)),
            window=window,
        ),
        simulation=SimulationScenario(
            scale=float(simulation_raw.get("scale", 0.01)),
            speed_mps=float(simulation_raw.get("speed_mps", 2)),
            warmup_s=float(simulation_raw.get("warmup_s", 5)),
            tolerance_m=float(simulation_raw.get("tolerance_m", 8)),
            minimum_clearance_m=float(simulation_raw.get("minimum_clearance_m", 55)),
            waypoint_timeout_s=float(simulation_raw.get("waypoint_timeout_s", 90)),
            global_timeout_s=float(simulation_raw.get("global_timeout_s", 1200)),
            target=str(simulation_raw.get("target", "auto")),
            drone=str(simulation_raw.get("drone", "/Drone")),
            body=str(simulation_raw.get("body", "auto")),
            apply_visual_force=bool(simulation_raw.get("apply_visual_force", True)),
        ),
        wind=WindScenario(
            events=events,
            cost=WindCostParameters(
                weight=float(cost_raw.get("weight", 1)),
                crosswind_factor=float(cost_raw.get("crosswind_factor", 0.25)),
                reference_speed_mps=float(cost_raw.get("reference_speed_mps", 5)),
            ),
            visual_acceleration_gain=float(visual_raw.get("acceleration_gain", 0.05)),
            maximum_visual_acceleration=float(visual_raw.get("maximum_acceleration", 0.5)),
            replan_delay_s=float(visual_raw.get("replan_delay_s", 0)),
            maximum_drift_m=float(visual_raw.get("maximum_drift_m", 0)),
        ),
        obstacles=obstacles,
        output_root=Path(str(root.get("output_root", "output/runs"))),
    )
    if scenario.simulation.scale <= 0 or scenario.simulation.speed_mps <= 0:
        raise ValueError("Escala e velocidade da simulação precisam ser positivas.")
    if not 0 < scenario.simulation.minimum_clearance_m <= scenario.coverage.clearance_m:
        raise ValueError(
            "A margem mínima precisa ser positiva e não pode exceder a altura-alvo."
        )
    if scenario.coverage.swath_m <= 0 or scenario.coverage.clearance_m <= 0:
        raise ValueError("Faixa e margem de cobertura precisam ser positivas.")
    scenario.coverage.window and scenario.coverage.window.validate(
        (scenario.terrain.size, scenario.terrain.size)
    )
    return scenario
