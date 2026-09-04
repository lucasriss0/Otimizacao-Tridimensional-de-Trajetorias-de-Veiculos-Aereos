from pathlib import Path

import numpy as np
import pytest

from src.waypoints import export_waypoints_csv, grid_path_to_waypoints_3d


def test_converts_grid_to_centered_local_coordinates():
    terrain = np.array([[100.0, 102.0], [105.0, 110.0]])
    waypoints = grid_path_to_waypoints_3d(
        terrain, [(0, 0), (1, 1)], 30, 20, clearance_m=15
    )
    assert waypoints[0].x_m == pytest.approx(-15)
    assert waypoints[0].y_m == pytest.approx(10)
    assert waypoints[0].terrain_z_m == pytest.approx(0)
    assert waypoints[0].z_m == pytest.approx(15)
    assert waypoints[1].x_m == pytest.approx(15)
    assert waypoints[1].y_m == pytest.approx(-10)
    assert waypoints[1].terrain_z_m == pytest.approx(10)
    assert waypoints[1].z_m == pytest.approx(25)
    assert waypoints[1].altitude_asl_m == pytest.approx(125)


def test_rejects_non_positive_clearance():
    with pytest.raises(ValueError, match="segurança"):
        grid_path_to_waypoints_3d(np.zeros((2, 2)), [(0, 0)], 1, 1, 0)


def test_rejects_position_outside_terrain():
    with pytest.raises(ValueError, match="fora"):
        grid_path_to_waypoints_3d(np.zeros((2, 2)), [(2, 0)], 1, 1, 10)


def test_exports_waypoints_csv(tmp_path: Path):
    waypoints = grid_path_to_waypoints_3d(
        np.zeros((2, 2)), [(0, 0), (1, 1)], 1, 1, 10
    )
    destination = export_waypoints_csv(waypoints, tmp_path / "waypoints.csv")
    content = destination.read_text(encoding="utf-8-sig")
    assert destination.exists()
    assert "x_m,y_m,z_m" in content
    assert len(content.splitlines()) == 3
