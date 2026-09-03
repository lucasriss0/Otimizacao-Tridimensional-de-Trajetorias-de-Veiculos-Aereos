import numpy as np

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
    assert result.total_cost == 8


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