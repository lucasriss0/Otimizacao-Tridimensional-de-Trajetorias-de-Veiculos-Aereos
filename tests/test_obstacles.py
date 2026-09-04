import numpy as np
import pytest

from src.obstacles import (
    StaticObstacle, create_obstacle_mask, load_obstacles_json,
    parse_obstacle_spec, save_obstacles_json,
)


def test_parses_obstacle_specification():
    obstacle = parse_obstacle_spec("arvore1, 0, -30, 45")
    assert obstacle == StaticObstacle(0, -30, 45, "arvore1")


def test_rejects_invalid_obstacle_specification():
    with pytest.raises(ValueError, match="formato"):
        parse_obstacle_spec("arvore,0,20")


def test_creates_circular_mask_in_local_coordinates():
    mask = create_obstacle_mask(
        (5, 5), [StaticObstacle(0, 0, 1.1, "arvore")], 1, 1
    )
    assert mask[2, 2]
    assert mask[1, 2] and mask[2, 1] and mask[2, 3] and mask[3, 2]
    assert not mask[0, 0]


def test_empty_obstacle_list_creates_free_mask():
    mask = create_obstacle_mask((3, 4), [], 1, 1)
    assert mask.shape == (3, 4)
    assert not np.any(mask)


def test_saves_and_loads_obstacles(tmp_path):
    original = [StaticObstacle(10, -20, 30, "ObstacleTree1")]
    path = save_obstacles_json(original, tmp_path / "obstacles.json")
    assert load_obstacles_json(path) == original
