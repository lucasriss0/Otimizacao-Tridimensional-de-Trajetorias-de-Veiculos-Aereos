from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.conventional import plan_conventional
from src.coverage import CoverageWindow
from src.planning_experiments import PlanningCase
from src.waypoints import grid_path_to_waypoints_3d


def field(rows=11,cols=15):
    return PlanningCase('field',np.zeros((rows,cols)),10,10,30,
        CoverageWindow(0,0,rows-1,cols-1),np.zeros((rows,cols),bool),(0,0),20)


def test_conventional_never_calls_astar_and_keeps_parallel_passes(monkeypatch):
    import src.astar
    import src.coverage
    def forbidden(*args,**kwargs):
        pytest.fail('A referência convencional não pode chamar A*.')
    monkeypatch.setattr(src.astar,'astar',forbidden)
    monkeypatch.setattr(src.coverage,'astar',forbidden)
    case = field()
    plan = plan_conventional(case)
    assert plan.eligible and plan.coverage_percent == 100
    assert plan.path[0] == plan.path[-1] == case.launch
    # Sem obstáculos, as passadas e cabeceiras são retas; não há diagonais.
    assert all(a[0] == b[0] or a[1] == b[1] for a,b in zip(plan.path,plan.path[1:]))
    case.obstacle_mask[3:7,6:9] = True
    assert plan_conventional(case).eligible


def test_conventional_orientation_depends_on_field_geometry_not_elevation():
    case = field(15,11)
    plan = plan_conventional(case)
    other = plan_conventional(replace(case,terrain=np.arange(165).reshape(15,11)*20.))
    assert plan.orientation == other.orientation == 'vertical'
    assert plan.path == other.path
    assert plan_conventional(field(11,11)).orientation == 'horizontal'


def test_geometric_obstacle_bypass_is_safe_continuous_and_deterministic():
    case = field()
    case.obstacle_mask[3:7,6:9] = True
    plan = plan_conventional(case)
    assert plan.eligible and plan.coverage_percent == 100
    assert plan.path == plan_conventional(case).path
    assert any(not float(row).is_integer() or not float(col).is_integer() for row,col in plan.path)
    # Verificação independente do teste de visibilidade: amostra a rota densa
    # e exige que nenhuma célula de exclusão seja atravessada.
    for a,b in zip(plan.path,plan.path[1:]):
        for t in np.linspace(0,1,101):
            point = (1-t)*np.asarray(a)+t*np.asarray(b)
            row,col = np.floor(point+.5).astype(int)
            assert not case.obstacle_mask[row,col]
    points = grid_path_to_waypoints_3d(case.terrain,plan.path,10,10,20)
    assert len(points) == len(plan.path)


def test_barrier_cannot_be_crossed_or_reported_as_completed():
    case = field()
    case.obstacle_mask[5,:] = True
    plan = plan_conventional(case)
    assert not plan.eligible and not plan.success
    assert plan.error


def test_bilinear_waypoints_preserve_straight_xy_and_plane_height():
    terrain = np.array([[100.,110.],[120.,130.]])
    points = grid_path_to_waypoints_3d(terrain,[(0,0),(.25,.5),(.5,1)],10,20,5)
    assert [p.altitude_asl_m for p in points] == pytest.approx([105,115,125])
    assert [p.x_m for p in points] == pytest.approx([-5,0,5])
    assert [p.y_m for p in points] == pytest.approx([10,5,0])


def test_new_pair_protocol_identifies_conventional_reference(tmp_path):
    import json
    from src.coverage_comparison import compare_coverage_flights
    output = compare_coverage_flights(Path('configs/demo_relief.yaml'),tmp_path/'pair',dry_run=True)
    protocol = json.loads((output/'protocol.json').read_text(encoding='utf-8'))
    assert protocol['baseline_planner'] == 'parallel_geometric_v1'
    assert protocol['method_plan_mapping']['referencia_2d'] == 'convencional_geometrico'
    assert protocol['plans'][0]['method'] == 'convencional_geometrico'
    assert protocol['plans'][1]['method'] == 'climb_orientation'
