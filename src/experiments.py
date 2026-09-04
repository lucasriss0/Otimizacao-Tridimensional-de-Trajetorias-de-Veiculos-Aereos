from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from math import hypot
from pathlib import Path

import numpy as np

from src.astar import Position, movement_cost
from src.coverage import (
    calculate_coverage_percent,
    generate_boustrophedon_targets,
    plan_targets,
    replan_remaining_targets,
)
from src.metrics import calculate_path_metrics
from src.obstacles import create_obstacle_mask
from src.scenario import MissionScenario, load_scenario
from src.terrain import load_topodata
from src.wind import WindVector


@dataclass(frozen=True)
class ExperimentResult:
    case: str
    path: list[Position]
    distance_3d_m: float
    elevation_gain_m: float
    normalized_base_cost: float
    wind_adjusted_cost: float
    coverage_percent: float
    expanded_nodes: int
    replans: int


def _route_cost(
    terrain: np.ndarray,
    path: list[Position],
    scenario: MissionScenario,
    wind: WindVector,
) -> float:
    cell_x = scenario.terrain.area_m / terrain.shape[1]
    cell_y = scenario.terrain.area_m / terrain.shape[0]
    return sum(
        movement_cost(
            terrain,
            current,
            neighbor,
            scenario.coverage.climb_weight,
            cell_x,
            cell_y,
            wind,
            scenario.wind.cost,
        )
        for current, neighbor in zip(path, path[1:])
    )


def _distance_3d(
    terrain: np.ndarray,
    current: Position,
    neighbor: Position,
    cell_x: float,
    cell_y: float,
) -> float:
    horizontal = hypot(
        (neighbor[1] - current[1]) * cell_x,
        (neighbor[0] - current[0]) * cell_y,
    )
    return hypot(horizontal, float(terrain[neighbor] - terrain[current]))


def _build_result(
    case: str,
    terrain: np.ndarray,
    path: list[Position],
    scenario: MissionScenario,
    wind_adjusted_cost: float,
    expanded_nodes: int,
    replans: int,
) -> ExperimentResult:
    cell_x = scenario.terrain.area_m / terrain.shape[1]
    cell_y = scenario.terrain.area_m / terrain.shape[0]
    obstacle_mask = create_obstacle_mask(
        terrain.shape, list(scenario.obstacles), cell_x, cell_y
    )
    metrics = calculate_path_metrics(
        case,
        terrain,
        path,
        cell_x,
        cell_y,
        scenario.coverage.climb_weight,
        0.0,
        expanded_nodes,
    )
    coverage = calculate_coverage_percent(
        terrain.shape,
        path,
        scenario.coverage.swath_m,
        cell_x,
        cell_y,
        obstacle_mask,
        scenario.coverage.window,
    )
    return ExperimentResult(
        case,
        path,
        metrics.distance_3d_m,
        metrics.elevation_gain_m,
        metrics.normalized_energy_cost,
        wind_adjusted_cost,
        coverage,
        expanded_nodes,
        replans,
    )


def compare_wind_cases(scenario: MissionScenario) -> list[ExperimentResult]:
    terrain = load_topodata(
        scenario.terrain.topodata,
        scenario.terrain.size,
        scenario.terrain.center_lat,
        scenario.terrain.center_lon,
        scenario.terrain.area_m,
    ).elevation
    cell_x = scenario.terrain.area_m / terrain.shape[1]
    cell_y = scenario.terrain.area_m / terrain.shape[0]
    spacing = max(1, round(scenario.coverage.swath_m / cell_y))
    obstacle_mask = create_obstacle_mask(
        terrain.shape, list(scenario.obstacles), cell_x, cell_y
    )
    targets = generate_boustrophedon_targets(terrain, spacing, scenario.coverage.window)
    targets = [target for target in targets if not obstacle_mask[target]]

    calm = WindVector()
    calm_plan = plan_targets(
        terrain, targets, scenario.coverage.climb_weight, cell_x, cell_y, wind=calm,
        obstacle_mask=obstacle_mask, wind_cost=scenario.wind.cost,
    )
    if not calm_plan.success:
        raise RuntimeError(calm_plan.error)
    results = [
        _build_result(
            "sem_vento",
            terrain,
            calm_plan.path,
            scenario,
            _route_cost(terrain, calm_plan.path, scenario, calm),
            calm_plan.expanded_nodes,
            0,
        )
    ]

    fixed_wind = next(
        (event.wind for event in scenario.wind.events if event.wind.speed_mps > 0), calm
    )
    fixed_plan = plan_targets(
        terrain,
        targets,
        scenario.coverage.climb_weight,
        cell_x,
        cell_y,
        obstacle_mask=obstacle_mask,
        wind=fixed_wind,
        wind_cost=scenario.wind.cost,
    )
    if not fixed_plan.success:
        raise RuntimeError(fixed_plan.error)
    results.append(
        _build_result(
            "vento_fixo",
            terrain,
            fixed_plan.path,
            scenario,
            _route_cost(terrain, fixed_plan.path, scenario, fixed_wind),
            fixed_plan.expanded_nodes,
            0,
        )
    )

    active = scenario.wind.active_event(0.0)
    route = calm_plan.path
    combined: list[Position] = []
    completed_targets = 1
    expanded = calm_plan.expanded_nodes
    adjusted_cost = 0.0
    previous_time = 0.0
    replans = 0
    for event in scenario.wind.events[scenario.wind.next_event_index(0.0) :]:
        distance_budget = (event.at_s - previous_time) * scenario.simulation.speed_mps
        cutoff = 0
        traveled = 0.0
        for index, (current, neighbor) in enumerate(zip(route, route[1:]), start=1):
            segment_distance = _distance_3d(terrain, current, neighbor, cell_x, cell_y)
            if traveled + segment_distance > distance_budget:
                break
            traveled += segment_distance
            cutoff = index
        prefix = route[: cutoff + 1]
        if not prefix:
            prefix = [route[0]]
        combined.extend(prefix if not combined else prefix[1:])
        adjusted_cost += _route_cost(terrain, prefix, scenario, active.wind)
        for cell in prefix:
            if completed_targets < len(targets) and cell == targets[completed_targets]:
                completed_targets += 1
        active = event
        remaining = targets[completed_targets:]
        if not remaining:
            route = [prefix[-1]]
            break
        replanned = replan_remaining_targets(
            terrain,
            prefix[-1],
            remaining,
            scenario.coverage.climb_weight,
            cell_x,
            cell_y,
            obstacle_mask=obstacle_mask,
            wind=active.wind,
            wind_cost=scenario.wind.cost,
        )
        if not replanned.success:
            raise RuntimeError(replanned.error)
        route = replanned.path
        expanded += replanned.expanded_nodes
        previous_time = event.at_s
        replans += 1
    combined.extend(route if not combined else route[1:])
    adjusted_cost += _route_cost(terrain, route, scenario, active.wind)
    results.append(
        _build_result(
            "vento_variavel_replanejado",
            terrain,
            combined,
            scenario,
            adjusted_cost,
            expanded,
            replans,
        )
    )
    return results


def export_comparison(results: list[ExperimentResult], output: str | Path) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case", "distance_3d_m", "elevation_gain_m", "normalized_base_cost",
        "wind_adjusted_cost", "coverage_percent", "expanded_nodes", "replans",
        "path_points",
    ]
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "case": result.case,
                    "distance_3d_m": result.distance_3d_m,
                    "elevation_gain_m": result.elevation_gain_m,
                    "normalized_base_cost": result.normalized_base_cost,
                    "wind_adjusted_cost": result.wind_adjusted_cost,
                    "coverage_percent": result.coverage_percent,
                    "expanded_nodes": result.expanded_nodes,
                    "replans": result.replans,
                    "path_points": len(result.path),
                }
            )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara cenários determinísticos de vento.")
    parser.add_argument("--scenario", type=Path, default=Path("configs/demo_wind.yaml"))
    parser.add_argument(
        "--output", type=Path, default=Path("output/experiments/wind_comparison.csv")
    )
    args = parser.parse_args()
    results = compare_wind_cases(load_scenario(args.scenario))
    destination = export_comparison(results, args.output)
    for result in results:
        print(
            f"{result.case}: custo_vento={result.wind_adjusted_cost:.2f}, "
            f"distância={result.distance_3d_m:.2f} m, cobertura={result.coverage_percent:.2f}%"
        )
    print(f"Comparação salva em: {destination}")


if __name__ == "__main__":
    main()
