import json
from pathlib import Path

import numpy as np
import pytest

from src.conventional import GeometricConnections
from src.coverage import CoverageWindow
from src.energy import EnergyModel
from src.energy_planning import _mission, refine_connections, select_energy_plan
from src.planning_experiments import PlanningCase, compare_planners


def field(blocked=True):
    rows, cols = np.indices((11, 11))
    mask = np.zeros((11, 11), bool)
    if blocked:
        mask[4:7, 4:7] = True
    return PlanningCase("development", (cols*3.).astype(float), 10., 10., 30.,
                        CoverageWindow(0, 0, 10, 10), mask, (0, 0), 20.)


def test_refinement_keeps_mandatory_targets_and_cannot_cut_through_obstacle():
    case = field()
    plan = next(t for t in compare_planners(case, (10.,)) if t.method == "climb_orientation")
    route = refine_connections(case, plan, EnergyModel(), 4.,
        GeometricConnections(case.obstacle_mask, 10., 10.), geometric=True)
    assert route[0] == route[-1] == case.launch
    cursor = 0
    for point in _mission(case, plan.orientation):
        cursor = route.index(point, cursor)
    # Checagem independente por amostragem densa da célula ocupada.
    for a, b in zip(route, route[1:]):
        for t in np.linspace(0, 1, 101):
            point = (1-t)*np.array(a)+t*np.array(b)
            row, col = np.floor(point+.5).astype(int)
            assert not case.obstacle_mask[row, col]


def test_selection_minimizes_wh_preserves_baseline_and_reports_attribution():
    case = field()
    result = select_energy_plan(case, EnergyModel(), 4.)
    rows = result.candidates
    selected = next(row for row in rows if row["candidate"] == result.selected_candidate)
    reference = next(row for row in rows if row["candidate"] == "convencional")
    assert selected["eligible"] and selected["planned_coverage_percent"] == 100
    assert selected["estimated_energy_wh"] == min(r["estimated_energy_wh"] for r in rows if r["eligible"])
    assert selected["estimated_energy_wh"] <= reference["estimated_energy_wh"]
    assert result.plan.path[0] == result.plan.path[-1] == case.launch
    assert result.manifest()["fallback_selected"] == (result.selected_candidate == "convencional")
    assert {r["family"] for r in rows} == {"convencional", "astar", "astar_atalhos", "astar_geometria"}


def test_no_safe_energy_candidate_is_an_explicit_failure():
    case = field()
    with pytest.raises(ValueError, match="Nenhum candidato"):
        select_energy_plan(case, EnergyModel(maximum_horizontal_speed_mps=1.), 4.)


def test_dry_run_exports_three_routes_and_selection_without_simulator(tmp_path):
    from src.coverage_comparison import compare_coverage_flights
    folder = compare_coverage_flights(Path("configs/development_energy.yaml"), tmp_path/"plans",
        dry_run=True, energy_planning=True,
        client_factory=lambda **kwargs: pytest.fail("Não conectar"))
    protocol = json.loads((folder/"protocol.json").read_text(encoding="utf-8"))
    assert protocol["method_order"] == ["referencia_2d", "proposta_subida_orientacao", "proposta_energia"]
    assert protocol["method_plan_mapping"]["proposta_energia"] == "energy_selected"
    assert protocol["energy_planning"]["version"] == "energy_candidates_v1"
    assert len(protocol["energy_planning"]["candidates"]) == 13
    assert len(protocol["plans"]) == 3
    assert (folder/"planned_energy_selected.csv").is_file()


def test_new_planner_cannot_silently_replace_historical_ablation(tmp_path):
    from src.coverage_comparison import compare_coverage_flights
    with pytest.raises(ValueError, match="experimentos separados"):
        compare_coverage_flights(Path("configs/demo_relief.yaml"), tmp_path/"invalid",
                                 dry_run=True, energy_planning=True, ablation=True)
