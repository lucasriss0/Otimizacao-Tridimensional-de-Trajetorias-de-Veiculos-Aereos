import numpy as np


def create_example_terrain() -> np.ndarray:
    """
    Cria um terreno artificial.
    Cada número representa a altitude daquela célula.
    Valores maiores representam regiões mais altas.
    """
    return np.array(
        [
            [0, 0, 0, 0, 0, 0, 0],
            [0, 1, 2, 4, 2, 1, 0],
            [0, 2, 5, 9, 5, 2, 0],
            [0, 3, 8, 15, 8, 3, 0],
            [0, 2, 5, 9, 5, 2, 0],
            [0, 1, 2, 4, 2, 1, 0],
            [0, 0, 0, 0, 0, 0, 0],
        ],
        dtype=float,
    )