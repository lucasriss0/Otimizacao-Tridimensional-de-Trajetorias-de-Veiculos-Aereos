import pytest

from src.sync_obstacles import read_obstacles_from_coppeliasim


class FakeSim:
    handle_scene = -1
    handle_all = -2
    handle_world = -1

    def getObjectsInTree(self, base, object_type, options):
        return [10, 20]

    def getObjectAlias(self, handle, options):
        return {10: "ObstacleTree1", 20: "Quadcopter"}[handle]

    def getObjectPosition(self, handle, relative):
        return [1.5, -0.9, 0.5]

    def getShapeBB(self, handle):
        return [0.4, 0.2, 1.0], [0, 0, 0, 0, 0, 0, 1]


class FakeClient:
    def __init__(self, **kwargs):
        self.sim = FakeSim()

    def require(self, name):
        return self.sim


def test_reads_prefixed_objects_and_converts_scene_scale():
    result = read_obstacles_from_coppeliasim(
        scale=0.01, safety_margin_m=30, client_factory=FakeClient
    )
    assert result.success
    assert len(result.obstacles) == 1
    obstacle = result.obstacles[0]
    assert obstacle.name == "ObstacleTree1"
    assert obstacle.x_m == pytest.approx(150)
    assert obstacle.y_m == pytest.approx(-90)
    assert obstacle.safety_radius_m == pytest.approx(50)


def test_reports_when_no_prefix_matches():
    result = read_obstacles_from_coppeliasim(
        alias_prefix="TreeThatDoesNotExist", client_factory=FakeClient
    )
    assert not result.success
