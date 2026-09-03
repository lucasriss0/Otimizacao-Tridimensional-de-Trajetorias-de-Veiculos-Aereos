from pathlib import Path

import numpy as np
import pytest

from src.metrics import (
    calculate_path_metrics,
    calculate_reduction_percent,
    export_metrics_csv,
)


def test_calculates_distance_and_elevation_gain():
    terrain = np.array([[0.0, 3.0, 3.0]])
    path = [(0, 0), (0, 1), (0, 2)]

    metrics = calculate_path_metrics(
        route_name="teste",
        terrain=terrain,
        path=path,
        cell_size_x_m=4.0,
        cell_size_y_m=4.0,
        climb_weight=2.0,
        planning_time_s=0.1,
        expanded_nodes=3,
    )

    assert metrics.horizontal_distance_m == pytest.approx(8.0)
    assert metrics.distance_3d_m == pytest.approx(9.0)
    assert metrics.elevation_gain_m == pytest.approx(3.0)
    assert metrics.elevation_loss_m == pytest.approx(0.0)
    assert metrics.normalized_energy_cost == pytest.approx(15.0)


def test_calculates_cost_reduction():
    assert calculate_reduction_percent(100.0, 80.0) == pytest.approx(20.0)


def test_exports_csv(tmp_path: Path):
    terrain = np.zeros((1, 2))
    metrics = calculate_path_metrics(
        "rota", terrain, [(0, 0), (0, 1)], 30, 30, 3, 0.01, 2
    )

    destination = export_metrics_csv([metrics], tmp_path / "metrics.csv")

    assert destination.exists()
    assert "route_name" in destination.read_text(encoding="utf-8-sig")
