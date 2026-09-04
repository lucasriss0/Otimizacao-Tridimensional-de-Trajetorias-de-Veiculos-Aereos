import numpy as np
import pytest

from src.coppelia_terrain import (
    create_heightfield_in_coppeliasim,
    prepare_heightfield,
)


class FakeTerrainSim:
    handle_world = -1
    shapeintparam_static = 3003

    def __init__(self):
        selfe = None

    def getObject(self, path):
        raise RuntimeError("not found")

    def createHeightfieldShape(self, *args):
        self.created = args
        return 42

    def setObjectAlias(self, handle, alias):
        self.alias = (handle, alias)

    def setObjectPosition(self, handle, position, relative):
        self.position = (handle, position, relative)

    def setObjectInt32Param(self, handle, parameter, value):
        self.static = (handle, parameter, value)


class FakeClient:
    def __init__(self, sim, **kwargs):
        self.sim = sim

    def require(self, name):
        assert name == "sim"
        return self.sim


def test_prepares_scaled_and_oriented_heightfield():
    elevation = np.array([[10.0, 11.0], [12.0, 14.0]])
    data = prepare_heightfield(elevation, cell_size_x_m=30, scale=0.01)
    assert data.x_size == pytest.approx(0.3)
    assert data.minimum_elevation_m == 10
    assert data.maximum_relative_height == pytest.approx(0.04)
    assert data.heights == pytest.approx([0.0, 0.01, 0.02, 0.04])


def test_rejects_invalid_heightfield():
    with pytest.raises(ValueError):
        prepare_heightfield(np.array([[1.0]]), 30, 0.01)


def test_creates_named_static_heightfield():
    data = prepare_heightfield(np.array([[0.0, 1.0], [2.0, 4.0]]), 30, 0.01)
    sim = FakeTerrainSim()
    factory = lambda **kwargs: FakeClient(sim, **kwargs)
    result = create_heightfield_in_coppeliasim(data, client_factory=factory)
    assert result.success
    assert result.handle == 42
    assert sim.alias == (42, "AgriculturalTerrain")
    assert sim.position == (42, [0.0, 0.0, 0.0], -1)
    assert sim.static == (42, 3003, 1)
