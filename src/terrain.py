from dataclasses import dataclass
from math import cos, radians, isfinite
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
    area_size_m: float | None = None
    height_scale: float = 1.


def elevation_at(terrain: np.ndarray, point: tuple[float, float]) -> float:
    """Altura bilinear para rotas geométricas; centros inteiros são preservados."""
    row, col = point
    if not (isfinite(row) and isfinite(col) and 0 <= row <= terrain.shape[0] - 1
            and 0 <= col <= terrain.shape[1] - 1):
        raise ValueError(f"A posição {point} está fora do terreno.")
    r, c = int(row), int(col)
    dr, dc = row - r, col - c
    values = terrain[r:min(r+2, terrain.shape[0]), c:min(c+2, terrain.shape[1])]
    if not np.isfinite(values).all():
        raise ValueError(f"A posição {point} não possui elevação válida.")
    r1, c1 = min(r+1, terrain.shape[0]-1), min(c+1, terrain.shape[1]-1)
    return float((1-dr)*((1-dc)*terrain[r,c]+dc*terrain[r,c1])
                 + dr*((1-dc)*terrain[r1,c]+dc*terrain[r1,c1]))


def load_topodata(
    input_path: str | Path,
    target_size: int = 50,
    center_lat: float | None = None,
    center_lon: float | None = None,
    area_size_m: float | None = None,
    height_scale: float = 1.,
) -> TerrainData:
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
    if isinstance(height_scale, bool) or not isfinite(height_scale) or height_scale <= 0:
        raise ValueError("O fator de relevo deve ser finito e positivo.")

    crop_values = (center_lat, center_lon, area_size_m)
    if any(value is not None for value in crop_values) and not all(
        value is not None for value in crop_values
    ):
        raise ValueError(
            "Para recortar, informe center_lat, center_lon e area_size_m juntos."
        )
    if area_size_m is not None and area_size_m <= 0:
        raise ValueError("area_size_m precisa ser positivo.")

    with rasterio.open(path) as dataset:
        if dataset.count < 1:
            raise ValueError("O GeoTIFF não possui banda de elevação.")

        original_shape = (dataset.height, dataset.width)
        window = None
        selected_bounds = dataset.bounds

        if center_lat is not None and center_lon is not None and area_size_m is not None:
            from rasterio.warp import transform_bounds
            from rasterio.windows import Window, bounds as window_bounds, from_bounds

            half_size_m = area_size_m / 2.0
            latitude_delta = half_size_m / 111_320.0
            longitude_scale = 111_320.0 * cos(radians(center_lat))
            if longitude_scale <= 0:
                raise ValueError("Latitude inválida para o recorte.")
            longitude_delta = half_size_m / longitude_scale

            wgs84_bounds = (
                center_lon - longitude_delta,
                center_lat - latitude_delta,
                center_lon + longitude_delta,
                center_lat + latitude_delta,
            )
            raster_bounds = transform_bounds(
                "EPSG:4326", dataset.crs, *wgs84_bounds, densify_pts=21
            )

            if (
                raster_bounds[0] < dataset.bounds.left
                or raster_bounds[1] < dataset.bounds.bottom
                or raster_bounds[2] > dataset.bounds.right
                or raster_bounds[3] > dataset.bounds.top
            ):
                raise ValueError(
                    "A área solicitada ultrapassa os limites desta folha TOPODATA."
                )

            window = from_bounds(*raster_bounds, transform=dataset.transform)
            window = window.round_offsets().round_lengths()
            full_window = Window(0, 0, dataset.width, dataset.height)
            window = window.intersection(full_window)
            selected_bounds = window_bounds(window, dataset.transform)

        masked = dataset.read(
            1,
            window=window,
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
        # Exagero vertical declarado: preserva o datum mínimo e o plano XY.
        # Fator diferente de 1 produz terreno sintético derivado do TOPODATA.
        if height_scale != 1.:
            minimum = float(np.min(elevation))
            elevation = minimum + (elevation - minimum) * height_scale

        return TerrainData(
            elevation=elevation,
            source_path=path.resolve(),
            crs=dataset.crs.to_string() if dataset.crs else None,
            bounds=tuple(float(value) for value in selected_bounds),
            pixel_size=(
                abs(float(dataset.transform.a)) * dataset.width / target_size,
                abs(float(dataset.transform.e)) * dataset.height / target_size,
            ),
            original_shape=original_shape,
            area_size_m=area_size_m,
            height_scale=height_scale,
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
