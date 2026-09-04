import argparse
from dataclasses import dataclass
from math import radians
from pathlib import Path
from typing import Callable

import numpy as np

from src.terrain import load_topodata


@dataclass(frozen=True)
class HeightfieldData:
    x_point_count: int
    y_point_count: int
    x_size: float
    heights: list[float]
    minimum_elevation_m: float
    maximum_relative_height: float


@dataclass(frozen=True)
class TerrainCreationResult:
    success: bool
    handle: int | None = None
    error: str | None = None


def prepare_heightfield(
    elevation: np.ndarray,
    cell_size_x_m: float,
    scale: float,
) -> HeightfieldData:
    """Converte o raster para o heightfield preservando norte em +Y."""
    if elevation.ndim != 2 or min(elevation.shape) < 2:
        raise ValueError("O heightfield exige uma matriz 2D de pelo menos 2 x 2.")
    if not np.all(np.isfinite(elevation)):
        raise ValueError("O terreno contém altitudes inválidas.")
    if cell_size_x_m <= 0 or scale <= 0:
        raise ValueError("Tamanho da célula e escala precisam ser positivos.")

    minimum = float(np.min(elevation))
    relative = (elevation - minimum) * scale
    # No heightfield do Coppelia, a primeira linha recebida aparece em +Y.
    # Portanto ela já coincide com a linha zero (norte) usada pelo planejador.
    heights = relative.ravel(order="C").astype(float).tolist()
    rows, columns = elevation.shape
    return HeightfieldData(
        x_point_count=columns,
        y_point_count=rows,
        x_size=(columns - 1) * cell_size_x_m * scale,
        heights=heights,
        minimum_elevation_m=minimum,
        maximum_relative_height=float(np.max(relative)),
    )


def create_heightfield_in_coppeliasim(
    data: HeightfieldData,
    alias: str = "AgriculturalTerrain",
    host: str = "localhost",
    port: int = 23000,
    client_factory: Callable[..., object] | None = None,
) -> TerrainCreationResult:
    """Cria um terreno estático/respondable na cena atualmente aberta."""
    try:
        if client_factory is None:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
            client_factory = RemoteAPIClient
        client = client_factory(host=host, port=port)
        sim = client.require("sim")

        # Remove apenas um terreno gerado anteriormente com o mesmo alias.
        try:
            old_handle = sim.getObject(f"/{alias}")
            sim.removeObject(old_handle)
        except Exception:
            pass

        handle = sim.createHeightfieldShape(
            0,
            radians(30),
            data.x_point_count,
            data.y_point_count,
            data.x_size,
            data.heights,
        )
        sim.setObjectAlias(handle, alias)
        sim.setObjectPosition(handle, [0.0, 0.0, 0.0], sim.handle_world)

        # Heightfields normalmente já são estáticos; esta chamada torna isso explícito.
        if hasattr(sim, "shapeintparam_static"):
            sim.setObjectInt32Param(handle, sim.shapeintparam_static, 1)
        return TerrainCreationResult(True, handle)
    except ImportError:
        return TerrainCreationResult(False, error="Cliente ZeroMQ não está instalado.")
    except Exception as exc:
        return TerrainCreationResult(
            False, error=f"Falha ao criar o heightfield no CoppeliaSim: {exc}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cria relevo TOPODATA no CoppeliaSim.")
    parser.add_argument("--topodata", type=Path, required=True)
    parser.add_argument("--center-lat", type=float, required=True)
    parser.add_argument("--center-lon", type=float, required=True)
    parser.add_argument("--area-m", type=float, default=1500)
    parser.add_argument("--size", type=int, default=50)
    parser.add_argument("--scale", type=float, default=0.01)
    parser.add_argument("--alias", default="AgriculturalTerrain")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    terrain = load_topodata(
        args.topodata, args.size, args.center_lat, args.center_lon, args.area_m
    )
    cell_size_x_m = args.area_m / terrain.elevation.shape[1]
    data = prepare_heightfield(terrain.elevation, cell_size_x_m, args.scale)
    print(f"Pontos do relevo: {data.x_point_count} x {data.y_point_count}")
    print(f"Largura na cena: {data.x_size:.3f}")
    print(f"Altitude base real: {data.minimum_elevation_m:.2f} m")
    print(f"Altura máxima na cena: {data.maximum_relative_height:.3f}")
    if args.dry_run:
        print("Heightfield validado; nenhuma conexão realizada (--dry-run).")
        return

    result = create_heightfield_in_coppeliasim(
        data, args.alias, args.host, args.port
    )
    if not result.success:
        raise RuntimeError(result.error)
    print(f"Terreno criado com sucesso! Handle: {result.handle}")
    print(f"Objeto da cena: /{args.alias}")
    print("Salve a cena no CoppeliaSim para preservar o terreno.")


if __name__ == "__main__":
    main()
