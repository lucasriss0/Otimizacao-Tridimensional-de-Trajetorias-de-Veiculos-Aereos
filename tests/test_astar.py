import numpy as np
import pytest

from src.astar import astar


def test_encontra_caminho_em_terreno_plano():
    terrain = np.zeros((5, 5))

    result = astar(
        terrain=terrain,
        start=(0, 0),
        goal=(4, 4),
    )

    assert result.success
    assert result.path[0] == (0, 0)
    assert result.path[-1] == (4, 4)
    assert result.total_cost == pytest.approx(4 * np.sqrt(2))
    assert len(result.path) == 5


def test_origem_igual_ao_destino():
    terrain = np.zeros((3, 3))

    result = astar(
        terrain=terrain,
        start=(1, 1),
        goal=(1, 1),
    )

    assert result.success
    assert result.path == [(1, 1)]
    assert result.total_cost == 0


def test_rejeita_origem_fora_do_terreno():
    terrain = np.zeros((3, 3))

    result = astar(
        terrain=terrain,
        start=(-1, 0),
        goal=(2, 2),
    )

    assert not result.success
    assert result.error is not None


def test_peso_de_subida_nao_pode_ser_negativo():
    terrain = np.zeros((3, 3))

    result = astar(
        terrain=terrain,
        start=(0, 0),
        goal=(2, 2),
        climb_weight=-1,
    )

    assert not result.success


def test_diagonal_considera_tamanho_real_da_celula():
    terrain = np.zeros((2, 2))

    result = astar(
        terrain=terrain,
        start=(0, 0),
        goal=(1, 1),
        cell_size_x_m=30,
        cell_size_y_m=30,
    )

    assert result.success
    assert result.path == [(0, 0), (1, 1)]
    assert result.total_cost == pytest.approx(np.sqrt(30**2 + 30**2))


def test_diagonal_nao_atravessa_canto_bloqueado():
    terrain = np.array([[0.0, np.nan], [np.nan, 0.0]])

    result = astar(terrain=terrain, start=(0, 0), goal=(1, 1))

    assert not result.success
    assert result.path == []


def test_rejeita_origem_bloqueada():
    terrain = np.array([[np.nan, 0.0], [0.0, 0.0]])

    result = astar(terrain=terrain, start=(0, 0), goal=(1, 1))

    assert not result.success
    assert "bloqueada" in result.error


def test_contorna_obstaculo_em_mascara_separada():
    terrain = np.zeros((5, 5))
    mask = np.zeros_like(terrain, dtype=bool)
    mask[2, 2] = True

    result = astar(terrain, (2, 0), (2, 4), obstacle_mask=mask)

    assert result.success
    assert (2, 2) not in result.path
