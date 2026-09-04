from pathlib import Path

import pytest

from src.coppeliasim import (
    _check_collision,
    _draw_wind,
    discover_dynamic_body,
    discover_target,
    interpolate_segment,
    load_waypoint_positions,
    run_simulation,
)
from src.wind import WindVector


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


def test_interprets_compound_collision_result():
    class CollisionSim:
        def checkCollision(self, first, second):
            return (0, [-1, -1])

    assert not _check_collision(CollisionSim(), 1, 2)


def test_discovers_nested_target_before_simulation_starts():
    class DiscoverySim:
        handle_scene = -1
        handle_all = -2

        def getObjectsInTree(self, root, object_type, options):
            return [10, 11]

        def getObjectAlias(self, handle, options=None):
            if options == 1:
                return "/Drone/target" if handle == 11 else "/Drone"
            return "target" if handle == 11 else "Drone"

    assert discover_target(DiscoverySim()) == 11


def test_uses_drone_root_as_force_body_instead_of_propeller_body():
    class BodySim:
        sceneobject_shape = 0
        handle_all = -2

        def getObjectType(self, handle):
            return 0

        def isDynamicallyEnabled(self, handle):
            return True

    assert discover_dynamic_body(BodySim(), 10) == 10


def test_wind_arrow_reuses_and_clears_the_same_drawing():
    class DrawingSim:
        drawing_lines = 1
        handle_world = -1

        def __init__(self):
            self.created = 0
            self.items = []

        def addDrawingObject(self, *args):
            self.created += 1
            return 77

        def addDrawingObjectItem(self, handle, item):
            assert handle == 77
            self.items.append(item)

    sim = DrawingSim()
    handle = _draw_wind(sim, WindVector(10, 0), (0, 0, 1), None)
    reused = _draw_wind(sim, WindVector(0, -10), (1, 1, 1), handle)

    assert handle == reused == 77
    assert sim.created == 1
    assert None in sim.items
