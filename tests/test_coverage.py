import numpy as np
import pytest

from src.coverage import (
    calculate_coverage_percent,
    generate_boustrophedon_targets,
    generate_boustrophedon_waypoints,
    plan_boustrophedon_coverage,
)


def test_generates_alternating_stripes():
    terrain = np.zeros((5, 4))
    assert generate_boustrophedon_waypoints(terrain, 2) == [
        (0, 0), (0, 3),
        (2, 3), (2, 0),
        (4, 0), (4, 3),
    ]


def test_avoids_redundant_last_stripe_when_border_is_already_covered():
    terrain = np.zeros((6, 3))
    waypoints = generate_boustrophedon_waypoints(terrain, 2)
    assert waypoints[-2:] == [(4, 0), (4, 2)]


def test_includes_last_row_when_border_would_remain_uncovered():
    terrain = np.zeros((6, 3))
    waypoints = generate_boustrophedon_waypoints(terrain, 3)
    assert waypoints[-2:] == [(5, 0), (5, 2)]


def test_generates_every_required_cell_along_stripes():
    terrain = np.zeros((3, 3))
    assert generate_boustrophedon_targets(terrain, 2) == [
        (0, 0), (0, 1), (0, 2),
        (2, 2), (2, 1), (2, 0),
    ]


def test_plans_complete_coverage_on_flat_grid():
    result = plan_boustrophedon_coverage(
        np.zeros((5, 5)), swath_width_m=2,
        climb_weight=0, cell_size_x_m=1, cell_size_y_m=1,
    )
    assert result.success
    assert result.path[0] == (0, 0)
    assert result.path[-1] == (4, 4)
    assert result.coverage_percent == pytest.approx(100.0)


def test_rejects_non_positive_swath():
    result = plan_boustrophedon_coverage(
        np.zeros((3, 3)), 0, 1, 1, 1
    )
    assert not result.success


def test_empty_path_has_zero_coverage():
    assert calculate_coverage_percent((3, 3), [], 2, 1, 1) == 0


def test_coverage_avoids_static_obstacle():
    terrain = np.zeros((7, 7))
    mask = np.zeros_like(terrain, dtype=bool)
    mask[3, 3] = True
    result = plan_boustrophedon_coverage(
        terrain, 2, 0, 1, 1, obstacle_mask=mask
    )
    assert result.success
    assert (3, 3) not in result.path
    assert result.coverage_percent == pytest.approx(100.0)
