import csv
import json
from dataclasses import replace
from heapq import heappop, heappush

import numpy as np
import pytest

from src.astar import astar, get_neighbors, movement_cost
from src.coverage import CoverageWindow, generate_boustrophedon_targets
from src.planning_experiments import (
    PlanningCase, compare_planners, export_results, synthetic_cases,
)


def small_case():
    terrain = np.tile([0., 10., 0., 10., 0.], (5, 1))
    return PlanningCase("ridge", terrain, 10, 10, 20,
                        CoverageWindow(0, 0, 4, 4), np.zeros((5, 5), bool), (0, 0))


def test_horizontal_baseline_ignores_height_but_3d_route_avoids_peak():
    terrain = np.zeros((5, 5))
    terrain[2, 2] = 100
    flat = astar(terrain, (2, 0), (2, 4), 0, distance_mode="horizontal")
    spatial = astar(terrain, (2, 0), (2, 4), 0)
    assert flat.total_cost == 4
    assert (2, 2) in flat.path
    assert (2, 2) not in spatial.path


@pytest.mark.parametrize("mode,weight", [("horizontal", 0), ("3d", 0), ("3d", 10)])
def test_astar_matches_dijkstra_with_obstacles_and_rectangular_cells(mode, weight):
    terrain = np.random.default_rng(7).uniform(0, 30, (6, 8))
    blocked = np.zeros(terrain.shape, bool)
    blocked[2:5, 3] = True
    start, goal = (0, 0), (5, 7)
    queue, costs = [(0., start)], {start: 0.}
    while queue:
        cost, cell = heappop(queue)
        if cost > costs[cell]:
            continue
        if cell == goal:
            break
        for neighbor in get_neighbors(cell, terrain, blocked):
            candidate = cost + movement_cost(terrain, cell, neighbor, weight, 2, 3,
                                              distance_mode=mode)
            if candidate < costs.get(neighbor, float("inf")):
                costs[neighbor] = candidate
                heappush(queue, (candidate, neighbor))
    result = astar(terrain, start, goal, weight, 2, 3, blocked, distance_mode=mode)
    assert result.success
    assert result.total_cost == pytest.approx(costs[goal])


def test_vertical_targets_respect_non_square_window_and_visit_entire_stripes():
    targets = generate_boustrophedon_targets(
        np.zeros((6, 9)), 2, CoverageWindow(1, 2, 4, 6), "vertical"
    )
    assert targets == [(r, 2) for r in range(1, 5)] + [
        (r, 4) for r in range(4, 0, -1)
    ] + [(r, 6) for r in range(1, 5)]


def test_selection_preserves_common_endpoints_and_uses_common_evaluation():
    case = small_case()
    trials = compare_planners(case, (0, 10), evaluation_weight=7)
    for trial in trials:
        assert trial.eligible
        assert trial.coverage_percent == 100
        assert trial.path[0] == trial.path[-1] == case.launch
        assert trial.normalized_cost == pytest.approx(
            trial.distance_3d_m + 7 * trial.elevation_gain_m
        )
    for weight in (0, 10):
        candidates = [t for t in trials if t.method == "climb_candidate" and t.planning_climb_weight == weight]
        winner = next(t for t in trials if t.method == "climb_orientation" and t.planning_climb_weight == weight)
        assert winner.normalized_cost == min(t.normalized_cost for t in candidates)
        assert winner.expanded_nodes == sum(t.expanded_nodes for t in candidates)
        assert winner.planning_time_s == pytest.approx(sum(t.planning_time_s for t in candidates))
    assert next(t for t in trials if t.method == "climb_orientation").orientation == "vertical"


def test_failed_and_insufficient_coverage_trials_are_kept(monkeypatch):
    case = small_case()
    # Barreira completa deixa alvos inacessíveis.
    mask = case.obstacle_mask.copy()
    mask[2, :] = True
    trials = compare_planners(replace(case, obstacle_mask=mask), (10,))
    assert all(not t.success and not t.eligible and not t.selected for t in trials)
    # A decisão de viabilidade precisa respeitar a medição de cobertura.
    monkeypatch.setattr("src.planning_experiments.calculate_coverage_percent", lambda *args: 95.)
    trials = compare_planners(case, (10,))
    horizontal = next(t for t in trials if t.method == "horizontal_2d")
    assert horizontal.success
    assert not horizontal.eligible
    assert horizontal.coverage_percent < 100


def test_suite_is_fixed_and_export_preserves_inputs_failures_and_routes(tmp_path):
    assert len(synthetic_cases()) == 6
    case = small_case()
    trials = compare_planners(case, (10,))
    repeated = compare_planners(case, (10,))
    assert [t.path for t in trials] == [t.path for t in repeated]
    output = tmp_path / "run"
    export_results(trials, [case], output, {"evaluation_weight": 10})
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cases"][0]["launch"] == [0, 0]
    data = np.load(output / manifest["cases"][0]["data_file"])
    np.testing.assert_array_equal(data["terrain"], case.terrain)
    with (output / "comparison.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(trials)
    assert all((output / row["route_file"]).exists() for row in rows)
    with pytest.raises(FileExistsError):
        export_results(trials, [case], output, {})


@pytest.mark.parametrize("kwargs", [
    {"weights": ()}, {"weights": (-1,)}, {"evaluation_weight": float("nan")},
    {"minimum_coverage": 0},
])
def test_invalid_protocol_is_rejected(kwargs):
    with pytest.raises(ValueError):
        compare_planners(small_case(), **kwargs)
