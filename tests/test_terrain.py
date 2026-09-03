from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

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


def test_load_topodata_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_topodata(tmp_path / "missing.tif")


def test_load_topodata_rejects_invalid_size(tmp_path: Path):
    source = np.ones((3, 3), dtype=np.float32)
    path = tmp_path / "terrain.tif"
    write_geotiff(path, source)

    with pytest.raises(ValueError, match="pelo menos 2"):
        load_topodata(path, target_size=1)
