from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from src.terrain import load_topodata


def write_geotiff(path: Path, data: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:31983",
        transform=from_origin(500000, 7500000, 30, 30),
    ) as dataset:
        dataset.write(data, 1)


def test_load_topodata_reduces_geotiff(tmp_path: Path):
    source = np.arange(100, dtype=np.float32).reshape(10, 10)
    path = tmp_path / "terrain.tif"
    write_geotiff(path, source)

    result = load_topodata(path, target_size=5)

    assert result.elevation.shape == (5, 5)
    assert result.original_shape == (10, 10)
    assert result.crs == "EPSG:31983"
    assert np.all(np.isfinite(result.elevation))


def test_vertical_exaggeration_preserves_xy_source_and_minimum(tmp_path):
    path = tmp_path / "terrain.tif"
    write_geotiff(path, np.arange(100, dtype=np.float32).reshape(10, 10) + 400)
    original = load_topodata(path, target_size=5)
    amplified = load_topodata(path, target_size=5, height_scale=10)
    minimum = original.elevation.min()
    assert amplified.elevation.min() == minimum
    assert np.allclose(amplified.elevation - minimum, (original.elevation - minimum) * 10)
    assert amplified.bounds == original.bounds
    assert amplified.pixel_size == original.pixel_size
    assert amplified.source_path == original.source_path
    assert amplified.height_scale == 10


@pytest.mark.parametrize("factor", [0, -1, float("nan"), float("inf"), True])
def test_invalid_vertical_exaggeration_is_rejected(tmp_path, factor):
    path = tmp_path / "terrain.tif"
    write_geotiff(path, np.zeros((4, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="fator de relevo"):
        load_topodata(path, height_scale=factor)


def test_load_topodata_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_topodata(tmp_path / "missing.tif")


def test_load_topodata_rejects_invalid_size(tmp_path: Path):
    source = np.ones((3, 3), dtype=np.float32)
    path = tmp_path / "terrain.tif"
    write_geotiff(path, source)

    with pytest.raises(ValueError, match="pelo menos 2"):
        load_topodata(path, target_size=1)


def test_load_topodata_crops_area_around_coordinate(tmp_path: Path):
    source = np.arange(10000, dtype=np.float32).reshape(100, 100)
    path = tmp_path / "terrain.tif"
    write_geotiff(path, source)

    longitude, latitude = transform(
        "EPSG:31983", "EPSG:4326", [501500], [7498500]
    )

    result = load_topodata(
        path,
        target_size=20,
        center_lat=latitude[0],
        center_lon=longitude[0],
        area_size_m=1000,
    )

    assert result.elevation.shape == (20, 20)
    assert result.area_size_m == 1000


def test_load_topodata_requires_complete_crop_parameters(tmp_path: Path):
    source = np.ones((3, 3), dtype=np.float32)
    path = tmp_path / "terrain.tif"
    write_geotiff(path, source)

    with pytest.raises(ValueError, match="informe"):
        load_topodata(path, center_lat=-22.5)
