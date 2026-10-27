import csv
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import src.coverage_comparison as comparison
from src.planning_experiments import PlanningCase
from src.coverage import CoverageWindow


def test_dry_run_exports_comparable_closed_routes_without_connecting(tmp_path):
    output = comparison.compare_coverage_flights(
        Path("configs/demo_wind.yaml"), tmp_path / "plans", dry_run=True,
        client_factory=lambda **kwargs: pytest.fail("Não deve conectar"),
    )
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    scenario = protocol["effective_scenario"]
    assert scenario["simulation"]["apply_visual_force"] is False
    assert scenario["wind"]["maximum_drift_m"] == 0
    assert len(scenario["wind"]["events"]) == 1
    assert scenario["wind"]["events"][0]["wind"] == {"east_mps": 0., "north_mps": 0.}
    for plan in protocol["plans"]:
        assert plan["path"][0] == plan["path"][-1] == protocol["launch"]
        assert plan["coverage_percent"] == 100
        with (output / f"planned_{plan['method']}.csv").open(encoding="utf-8-sig") as stream:
            waypoints = list(csv.DictReader(stream))
        assert len(waypoints) == len(plan["path"])
        assert float(waypoints[0]["z_m"]) == float(waypoints[-1]["z_m"])
    assert not (output / "comparison.csv").exists()
    with pytest.raises(FileExistsError):
        comparison.compare_coverage_flights(Path("configs/demo_coverage.yaml"), output, dry_run=True)


def test_live_pair_executes_exact_plans_and_keeps_controller_equal(tmp_path, monkeypatch):
    scene = tmp_path / "scene.ttt"
    scene.touch()
    loaded, saved, calls = [], [], []
    sim = SimpleNamespace(
        simulation_stopped=0, boolparam_infotext_visible=17,
        getSimulationState=lambda: 0, loadScene=loaded.append,
        saveScene=saved.append, adjustView=lambda *args: None,
        getObject=lambda name: 0, setObjectSelection=lambda *args: None,
        setBoolParam=lambda *args: None,
    )
    client = SimpleNamespace(require=lambda name: sim)

    def run(scenario, terrain, targets, route, source, host, port, **kwargs):
        calls.append((scenario, targets.copy(), route.copy(), kwargs))
        # Mesmo voo incompleto deve ficar na comparação.
        folder = scenario.output_root / scenario.scenario_id
        folder.mkdir(parents=True)
        (folder / "metrics.csv").write_text(
            "mission_completed,mission_completed_safely\nFalse,False\n", encoding="utf-8"
        )
        (folder / "telemetry.csv").write_text(
            "simulation_time_s,drone_x_m,drone_y_m,drone_z_m,application_active\n0,0,0,60,True\n1,0,0,60,True\n",
            encoding="utf-8",
        )
        return SimpleNamespace(success=False, output_directory=folder)

    monkeypatch.setattr(comparison, "run_wind_mission", run)
    output = comparison.compare_coverage_flights(
        Path("configs/demo_coverage.yaml"), tmp_path / "pair", scene,
        client_factory=lambda **kw: client,
    )
    assert loaded == [scene.as_posix()] * 2
    assert len(saved) == 1
    assert Path(saved[0]).name == "scene_before.ttt"
    first, second = calls[0][0], calls[1][0]
    assert replace(first, scenario_id=second.scenario_id) == second
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    for call, plan in zip(calls, protocol["plans"]):
        assert call[1] == call[2] == [tuple(cell) for cell in plan["path"]]
        assert call[3]["replanning_enabled"] is False
    assert calls[0][2][0] == calls[1][2][0] == calls[0][2][-1] == calls[1][2][-1]
    with (output / "comparison.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(row["mission_completed_safely"] == "False" for row in rows)
    assert all(float(row["estimated_energy_wh"]) > 0 for row in rows)
    assert rows[0]["estimated_energy_wh"] == rows[1]["estimated_energy_wh"]
    assert all(row["energy_calibrated"] == "False" for row in rows)
    assert all(row["energy_comparison_eligible"] == "False" for row in rows)
    with (output / "energy_contrasts.csv").open(encoding="utf-8-sig") as stream:
        contrast = next(csv.DictReader(stream))
    assert contrast["estimated_energy_reduction_percent"] == ""


def test_refuses_routes_that_cannot_cover_same_area(tmp_path, monkeypatch):
    terrain = np.zeros((5, 5))
    mask = np.zeros((5, 5), bool)
    mask[2, :] = True
    case = PlanningCase("blocked", terrain, 10, 10, 20,
                        CoverageWindow(0, 0, 4, 4), mask, (0, 0))
    monkeypatch.setattr(comparison, "case_from_scenario", lambda path: case)
    with pytest.raises(RuntimeError, match="100%"):
        comparison.compare_coverage_flights(Path("configs/demo_coverage.yaml"),
                                            tmp_path / "invalid", dry_run=True)
    assert not (tmp_path / "invalid").exists()


def test_completed_flights_with_measured_coverage_generate_valid_contrast(tmp_path, monkeypatch):
    from math import ceil, dist
    from src.waypoints import grid_path_to_waypoints_3d
    terrain_case = PlanningCase("flat", np.zeros((3, 3)), 10, 10, 20,
                                CoverageWindow(0, 0, 2, 2), np.zeros((3, 3), bool), (0, 0))
    monkeypatch.setattr(comparison, "case_from_scenario", lambda path: terrain_case)
    scene = tmp_path / "scene.ttt"
    scene.touch()
    sim = SimpleNamespace(
        simulation_stopped=0, boolparam_infotext_visible=17,
        getSimulationState=lambda: 0, loadScene=lambda path: None,
        saveScene=lambda path: None, adjustView=lambda *args: None,
        getObject=lambda name: 0, setObjectSelection=lambda *args: None,
        setBoolParam=lambda *args: None,
    )

    def run(scenario, terrain, targets, route, *args, **kwargs):
        folder = scenario.output_root / scenario.scenario_id
        folder.mkdir(parents=True)
        (folder / "metrics.csv").write_text(
            "mission_completed,mission_completed_safely\nTrue,True\n", encoding="utf-8")
        waypoints = grid_path_to_waypoints_3d(terrain, route, 10, 10, 60)
        positions = [(p.x_m, p.y_m, p.z_m) for p in waypoints]
        with (folder / "telemetry.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["simulation_time_s", "drone_x_m", "drone_y_m", "drone_z_m", "application_active"])
            writer.writerow([0, *positions[0], True])
            elapsed = 0.
            for start, end in zip(positions, positions[1:]):
                steps = max(1, ceil(dist(start, end) / .25))
                for index in range(1, steps + 1):
                    elapsed += .05
                    position = [a + (b - a) * index / steps for a, b in zip(start, end)]
                    writer.writerow([elapsed, *position, True])
        return SimpleNamespace(success=True, output_directory=folder)

    monkeypatch.setattr(comparison, "run_wind_mission", run)
    output = comparison.compare_coverage_flights(Path("configs/demo_coverage.yaml"),
        tmp_path / "valid_pair", scene, client_factory=lambda **kw: SimpleNamespace(require=lambda name: sim))
    with (output / "comparison.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert all(r["energy_comparison_eligible"] == "True" for r in rows)
    assert all(float(r["executed_coverage_percent"]) == 100 for r in rows)
    assert all(float(r["estimated_energy_wh_per_covered_ha"]) > 0 for r in rows)
    with (output / "energy_contrasts.csv").open(encoding="utf-8-sig") as stream:
        contrast = next(csv.DictReader(stream))
    assert contrast["comparable"] == "True"
    assert float(contrast["estimated_energy_reduction_percent"]) == pytest.approx(0)


def test_preparation_restores_model_setting_and_uses_same_scene_twice(tmp_path, monkeypatch):
    previous = comparison.scene.DEFAULT_TREE_MODEL
    sim = SimpleNamespace(
        simulation_stopped=0, stringparam_application_path=1,
        boolparam_infotext_visible=17, getSimulationState=lambda: 0,
        saveScene=lambda path: None, getStringParam=lambda param: str(tmp_path),
        loadScene=lambda path: None, adjustView=lambda *args: None,
        getObject=lambda name: 0, setObjectSelection=lambda *args: None,
        setBoolParam=lambda *args: None,
    )
    client = SimpleNamespace(require=lambda name: sim)
    monkeypatch.setattr(comparison.scene, "setup_scene", lambda *args, **kw:
                        SimpleNamespace(success=False, error="model missing"))
    with pytest.raises(RuntimeError, match="model missing"):
        comparison.compare_coverage_flights(Path("configs/demo_coverage.yaml"),
                                            tmp_path / "prepare", client_factory=lambda **kw: client)
    assert comparison.scene.DEFAULT_TREE_MODEL == previous
