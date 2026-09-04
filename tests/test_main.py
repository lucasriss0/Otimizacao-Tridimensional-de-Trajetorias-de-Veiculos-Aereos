import pytest

from src.main import resolve_endpoints


def test_resolve_endpoints_uses_default_edges():
    start, goal = resolve_endpoints((50, 50), None, None, None, None)

    assert start == (25, 0)
    assert goal == (25, 49)


def test_resolve_endpoints_accepts_custom_points():
    start, goal = resolve_endpoints((50, 50), 4, 6, 42, 45)

    assert start == (4, 6)
    assert goal == (42, 45)


def test_resolve_endpoints_requires_all_coordinates():
    with pytest.raises(ValueError, match="Informe juntos"):
        resolve_endpoints((50, 50), 4, 6, None, None)


def test_resolve_endpoints_rejects_point_outside_grid():
    with pytest.raises(ValueError, match="fora do grid"):
        resolve_endpoints((50, 50), 4, 6, 50, 45)
