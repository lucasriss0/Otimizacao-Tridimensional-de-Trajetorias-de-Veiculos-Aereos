from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class TerrainData:
    elevation: np.ndarray
    source_path: Path
    crs: str | None
    bounds: tuple[float, float, float, float]
    pixel_size: tuple[float, float]
    original_shape: tuple[int, int]


def load_topodata(input_path: str | Path, target_size: int = 50) -> TerrainData:
    """Lê e reduz um GeoTIFF TOPODATA para uma matriz quadrada."""
    try:
        import rasterio
        from rasterio.enums import Resampling
    except ImportError as exc:
        raise RuntimeError(
            "Rasterio não está instalado. Execute: python -m pip install rasterio"
        ) from exc

    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(f"GeoTIFF não encontrado: {path}")
    if target_size < 2:
        raise ValueError("target_size precisa ser pelo menos 2.")

    with rasterio.open(path) as dataset:
        if dataset.count < 1:
            raise ValueError("O GeoTIFF não possui banda de elevação.")

        original_shape = (dataset.height, dataset.width)
        masked = dataset.read(
            1,
            out_shape=(target_size, target_size),
            resampling=Resampling.bilinear,
            masked=True,
        )
        mask = np.ma.getmaskarray(masked)
        if np.any(mask):
            raise ValueError(
                f"O recorte contém {int(mask.sum())} células sem elevação (NoData)."
            )

        elevation = np.asarray(masked, dtype=float)
        if not np.all(np.isfinite(elevation)):
            raise ValueError("O GeoTIFF contém elevações inválidas.")

        return TerrainData(
            elevation=elevation,
            source_path=path.resolve(),
            crs=dataset.crs.to_string() if dataset.crs else None,
            bounds=(
                float(dataset.bounds.left),
                float(dataset.bounds.bottom),
                float(dataset.bounds.right),
                float(dataset.bounds.top),
            ),
            pixel_size=(
                abs(float(dataset.transform.a)) * dataset.width / target_size,
                abs(float(dataset.transform.e)) * dataset.height / target_size,
            ),
            original_shape=original_shape,
        )


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
