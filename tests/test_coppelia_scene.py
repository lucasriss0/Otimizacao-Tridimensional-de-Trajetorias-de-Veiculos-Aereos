from pathlib import Path

import numpy as np
import pytest

from src.coppelia_scene import (
    _create_crop_visualization,
    _terrain_visual_data,
    setup_scene,
    to_coppeliasim_path,
)
from src.coverage import CoverageWindow
from src.scenario import load_scenario


def test_converts_wsl_path_for_windows_coppeliasim():
    converted = to_coppeliasim_path(
        "/mnt/c/3D-DRONE/scenes/drone_agricola_wind.ttt"
    )
    assert converted == "C:/3D-DRONE/scenes/drone_agricola_wind.ttt"


def test_refuses_to_overwrite_scene_before_connecting(tmp_path: Path):
    destination = tmp_path / "existing.ttt"
    destination.write_bytes(b"scene")
    result = setup_scene(
        load_scenario("configs/demo_wind.yaml"), destination, overwrite=False
    )
    assert not result.success
    assert "--overwrite" in result.error


def test_crop_rows_are_one_upward_facing_mesh():
    class FakeSim:
        colorcomponent_ambient_diffuse = 0
        shapeintparam_static = 1

        def createShape(self, _options, _angle, vertices, indices):
            self.vertices = np.asarray(vertices).reshape(-1, 3)
            self.indices = np.asarray(indices).reshape(-1, 3)
            return 42

        def setObjectAlias(self, *_args):
            pass

        def setShapeColor(self, *_args):
            pass

        def setObjectInt32Param(self, *_args):
            pass

        def setObjectSpecialProperty(self, *_args):
            pass

    sim = FakeSim()
    handle = _create_crop_visualization(
        sim,
        np.array([[0.0, 0.1, 0.2], [0.2, 0.3, 0.4]]),
        CoverageWindow(0, 0, 1, 2),
        cell_size_m=30,
        scale=0.01,
    )

    triangles = sim.vertices[sim.indices]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    assert handle == 42
    assert len(sim.indices) == 8
    assert np.all(normals[:, 2] > 0)


def test_terrain_visualization_preserves_geometry_and_encodes_height():
    elevation = np.array([[0.0, 10.0], [20.0, 40.0]])
    vertices, indices, _uv, texture, resolution = _terrain_visual_data(
        elevation, cell_size_m=30, scale=0.01
    )
    points = np.asarray(vertices).reshape(-1, 3)
    triangles = points[np.asarray(indices).reshape(-1, 3)]
    normals = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )

    assert resolution == [256, 256]
    assert points[:, 2].min() == pytest.approx(0.006)
    assert points[:, 2].max() == pytest.approx(0.406)
    assert len(texture) == 256 * 256 * 3
    assert np.all(normals[:, 2] > 0)
