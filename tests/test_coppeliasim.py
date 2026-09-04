from pathlib import Path

import pytest

from src.coppeliasim import interpolate_segment, load_waypoint_positions, run_simulation


class FakeSim:
    handle_world = -1

    def __init__(self):
        self.positions = []
        self.started = False
        self.stopped = False
        self.steps = 0

    def getObject(self, path):
        assert path == "/DroneTarget"
        return 42

    def getObjectPosition(self, handle, relative_to):
        assert handle == 42 and relative_to == -1
        return [0.0, 0.0, 1.0]

    def setStepping(self, enabled):
        assert enabled

    def setObjectPosition(self, handle, position, relative_to):
        assert handle == 42 and relative_to == -1
        self.positions.append(position)

    def startSimulation(self):
        self.started = True

    def stopSimulation(self):
        self.stopped = True

    def getSimulationTimeStep(self):
        return 0.1

    def step(self):
        self.steps += 1


class FakeClient:
    def __init__(self, sim, **kwargs):
        self.sim = sim

    def require(self, name):
        assert name == "sim"
        return self.sim


def test_loads_and_scales_csv(tmp_path: Path):
    path = tmp_path / "waypoints.csv"
    path.write_text("x_m,y_m,z_m\n100,-50,20\n", encoding="utf-8")
    assert load_waypoint_positions(path, 0.01) == [(1.0, -0.5, 0.2)]


def test_interpolates_without_exceeding_step_distance():
    points = interpolate_segment((0, 0, 0), (1, 0, 0), 0.3)
    assert len(points) == 4
    assert points[-1] == pytest.approx((1, 0, 0))


def test_runs_synchronized_simulation_and_stops_it():
    sim = FakeSim()
    factory = lambda **kwargs: FakeClient(sim, **kwargs)
    result = run_simulation(
        [(0, 0, 1), (1, 0, 1)], speed=2,
        warmup_seconds=0,
        client_factory=factory,
    )
    assert result.success
    assert result.waypoints_completed == 2
    assert result.simulation_steps == 5
    assert sim.started and sim.stopped
    assert sim.positions[-1] == pytest.approx([1, 0, 1])


def test_rejects_empty_route_without_connecting():
    result = run_simulation([])
    assert not result.success


def test_waits_for_warmup_before_moving_target():
    sim = FakeSim()
    factory = lambda **kwargs: FakeClient(sim, **kwargs)
    result = run_simulation(
        [(0, 0, 1)], speed=1, warmup_seconds=0.3,
        client_factory=factory,
    )
    assert result.success
    assert result.simulation_steps == 3
    assert sim.positions == []
