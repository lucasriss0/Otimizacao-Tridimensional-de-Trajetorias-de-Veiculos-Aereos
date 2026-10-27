import csv
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import src.coppeliasim as flight
import src.wind_comparison as comparison
from src.scenario import load_scenario
from src.wind import WindEvent, WindVector


def test_pair_reloads_scene_and_only_changes_replanning(tmp_path, monkeypatch):
    scene = tmp_path / "scene.ttt"
    scene.write_bytes(b"scene")
    calls, loaded = [], []
    sim = SimpleNamespace(simulation_stopped=0, getSimulationState=lambda: 0,
                          loadScene=lambda path: loaded.append(path))
    client = SimpleNamespace(require=lambda name: sim)
    monkeypatch.setattr(comparison, "prepare_scenario_route",
                        lambda scenario: (np.zeros((2, 2)), [(0, 0), (1, 1)], [(0, 0), (1, 1)]))

    def run(scenario, terrain, targets, path, source, host, port, **kwargs):
        calls.append((scenario, targets, path, kwargs["replanning_enabled"]))
        folder = scenario.output_root / str(len(calls))
        folder.mkdir(parents=True)
        (folder / "metrics.csv").write_text("success,route_revisions\nTrue,0\n", encoding="utf-8")
        return SimpleNamespace(output_directory=folder)

    monkeypatch.setattr(comparison, "run_wind_mission", run)
    output = comparison.compare_wind_flights(Path("configs/demo_wind.yaml"), scene,
                                             tmp_path / "pair", client_factory=lambda **kw: client)
    assert len(loaded) == 2
    assert loaded[0] == loaded[1]
    assert [c[3] for c in calls] == [False, True]
    first, second = calls[0][0], calls[1][0]
    assert replace(first, scenario_id=second.scenario_id) == second
    assert first.wind.maximum_drift_m == 0
    assert first.simulation.apply_visual_force
    assert calls[0][1:3] == calls[1][1:3]
    with (output / "comparison.csv").open(encoding="utf-8-sig") as stream:
        assert len(list(csv.DictReader(stream))) == 2


def test_dry_run_never_connects(tmp_path):
    scene = tmp_path / "scene.ttt"
    scene.touch()
    output = comparison.compare_wind_flights(Path("configs/demo_wind.yaml"), scene,
                                             tmp_path / "dry", dry_run=True,
                                             client_factory=lambda **kw: pytest.fail("Conexão indevida"))
    assert json.loads((output / "protocol.json").read_text(encoding="utf-8"))["dry_run"]
    assert not (output / "comparison.csv").exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_flight_keeps_wind_and_drifts_with_replanning_off(tmp_path, monkeypatch, enabled):
    scenario = load_scenario("configs/demo_wind.yaml")
    scenario = replace(scenario, output_root=tmp_path,
                       obstacles=(), simulation=replace(scenario.simulation,
                       target="/target", body="/body", warmup_s=0, speed_mps=30,
                       tolerance_m=1, scale=1),
                       wind=replace(scenario.wind, replan_delay_s=.2, maximum_drift_m=2,
                       events=(WindEvent("gust", .1, WindVector(5, 0)),)))

    class Sim:
        handle_world = -1
        simulation_stopped = 0
        handle_all = -2
        def __init__(self):
            self.time = 0.
            self.state = 0
            self.positions = {1: [0, 0, 60], 2: [0, 0, 60], 3: [0, 0, 60]}
        def getObject(self, path):
            if path == "/AgriculturalTerrain":
                raise ValueError("no terrain")
            return {"/target": 1, "/Drone": 2, "/body": 3}[path]
        def getSimulationState(self): return self.state
        def getSimulationTime(self): return self.time
        def getSimulationTimeStep(self): return .1
        def setStepping(self, enabled): pass
        def startSimulation(self): self.state = 1
        def stopSimulation(self): self.state = 0
        def setObjectPosition(self, handle, position, relative): self.positions[handle] = list(position)
        def getObjectPosition(self, handle, relative): return self.positions[handle]
        def step(self):
            self.time += .1
            self.positions[2] = self.positions[1].copy()

    sim = Sim()
    winds = []
    monkeypatch.setattr(flight, "_apply_visual_wind_force",
                        lambda sim, body, wind, scenario, elapsed: winds.append(wind))
    for name in ("_draw_route", "_draw_wind"):
        monkeypatch.setattr(flight, name, lambda *args: None)
    result = flight.run_wind_mission(
        scenario, np.zeros((2, 2)), [(0, 0), (0, 1)], [(0, 0), (0, 1)],
        Path("configs/demo_wind.yaml"), client_factory=lambda **kw: SimpleNamespace(require=lambda name: sim),
        replanning_enabled=enabled,
    )
    assert result.success, result.error
    assert any(wind.east_mps == 5 for wind in winds)
    assert result.route_revisions == int(enabled)
    assert any(s.wind_event == "gust" for s in result.telemetry)
    if enabled:
        assert result.replan_events[0].planning_time_s >= 0
