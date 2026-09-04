from __future__ import annotations

import argparse
from dataclasses import dataclass
from math import radians
from pathlib import Path
from typing import Callable

import numpy as np

from src.coppelia_terrain import prepare_heightfield
from src.coverage import CoverageWindow, generate_boustrophedon_targets
from src.scenario import MissionScenario, load_scenario
from src.terrain import load_topodata
from src.waypoints import grid_path_to_waypoints_3d, local_xy_to_grid


DEFAULT_QUADCOPTER_MODEL = Path(
    "/mnt/c/Program Files/CoppeliaRobotics/CoppeliaSimEdu/models/robots/mobile/Quadcopter.ttm"
)
DEFAULT_TREE_MODEL = Path(
    "/mnt/c/Program Files/CoppeliaRobotics/CoppeliaSimEdu/models/nature/Tree.ttm"
)
TREE_VISUAL_HEIGHT_M = 45.0


@dataclass(frozen=True)
class SceneSetupResult:
    success: bool
    scene_path: Path | None = None
    drone_handle: int | None = None
    terrain_handle: int | None = None
    target_handle: int | None = None
    body_handle: int | None = None
    error: str | None = None


def to_coppeliasim_path(path: str | Path) -> str:
    """Converte /mnt/c/... para um caminho entendido pelo CoppeliaSim no Windows."""

    resolved = Path(path).resolve()
    parts = resolved.parts
    if len(parts) >= 4 and parts[:3] == ("/", "mnt", "c"):
        return "C:/" + "/".join(parts[3:])
    return str(resolved)


def _remove_if_present(sim: object, path: str) -> None:
    try:
        handle = sim.getObject(path)
    except Exception:
        return
    try:
        sim.removeModel(handle)
    except Exception:
        sim.removeObject(handle)


def _terrain_visual_data(
    elevation: np.ndarray,
    cell_size_m: float,
    scale: float,
) -> tuple[list[float], list[int], list[float], bytes, list[int]]:
    """Gera uma malha texturizada que evidencia altitude sem alterar o MDE."""

    rows, columns = elevation.shape
    center_row = (rows - 1) / 2
    center_column = (columns - 1) / 2
    cell_scene = cell_size_m * scale
    relative = elevation - float(np.min(elevation))
    height_range = max(float(np.ptp(relative)), 1e-9)

    vertices = [
        coordinate
        for row in range(rows)
        for column in range(columns)
        for coordinate in (
            (column - center_column) * cell_scene,
            (center_row - row) * cell_scene,
            float(relative[row, column]) * scale + 0.006,
        )
    ]
    indices: list[int] = []
    texture_coordinates: list[float] = []

    def add_triangle(*triangle: int) -> None:
        indices.extend(triangle)
        for vertex in triangle:
            row, column = divmod(vertex, columns)
            texture_coordinates.extend(
                [column / (columns - 1), 1.0 - row / (rows - 1)]
            )

    for row in range(rows - 1):
        for column in range(columns - 1):
            northwest = row * columns + column
            northeast = northwest + 1
            southwest = northwest + columns
            southeast = southwest + 1
            add_triangle(northwest, southwest, northeast)
            add_triangle(northeast, southwest, southeast)

    texture_size = 256
    source_x = np.linspace(0.0, 1.0, columns)
    source_y = np.linspace(0.0, 1.0, rows)
    texture_axis = np.linspace(0.0, 1.0, texture_size)
    horizontal = np.asarray(
        [np.interp(texture_axis, source_x, row) for row in relative]
    )
    visual_height = np.asarray(
        [
            np.interp(texture_axis, source_y, horizontal[:, column])
            for column in range(texture_size)
        ]
    ).T
    normalized = visual_height / height_range
    palette = np.asarray(
        [
            [0.10, 0.30, 0.12],
            [0.28, 0.48, 0.17],
            [0.52, 0.56, 0.22],
            [0.70, 0.57, 0.31],
            [0.84, 0.74, 0.55],
        ]
    )
    palette_position = normalized * (len(palette) - 1)
    lower = np.floor(palette_position).astype(int)
    upper = np.minimum(lower + 1, len(palette) - 1)
    fraction = (palette_position - lower)[..., None]
    colors = palette[lower] * (1 - fraction) + palette[upper] * fraction

    # Contornos finos e discretos, sem esconder o gradiente de altitude.
    contour_spacing = height_range / 7
    contour_phase = np.mod(visual_height, contour_spacing)
    contour_distance = np.minimum(contour_phase, contour_spacing - contour_phase)
    colors[contour_distance < height_range * 0.0025] *= 0.78
    texture = np.clip(colors * 255, 0, 255).astype(np.uint8).tobytes()
    return vertices, indices, texture_coordinates, texture, [texture_size, texture_size]


def _create_terrain_visualization(
    sim: object,
    elevation: np.ndarray,
    cell_size_m: float,
    scale: float,
) -> int:
    vertices, indices, coordinates, texture, resolution = _terrain_visual_data(
        elevation, cell_size_m, scale
    )
    handle = int(
        sim.createShape(
            8,
            radians(60),
            vertices,
            indices,
            None,
            coordinates,
            texture,
            resolution,
        )
    )
    sim.setObjectAlias(handle, "TerrainVisualization")
    if hasattr(sim, "shapeintparam_static"):
        sim.setObjectInt32Param(handle, sim.shapeintparam_static, 1)
    if hasattr(sim, "setObjectSpecialProperty"):
        sim.setObjectSpecialProperty(handle, 0)
    return handle


def _create_crop_visualization(
    sim: object,
    elevation: np.ndarray,
    window: CoverageWindow,
    cell_size_m: float,
    scale: float,
) -> int:
    """Cria uma única malha de fileiras contínuas sobre a área da missão."""

    rows, columns = elevation.shape
    center_row = (rows - 1) / 2
    center_column = (columns - 1) / 2
    minimum_terrain = float(np.min(elevation))
    cell_scene = cell_size_m * scale
    half_row_width = cell_scene * 0.065
    vertices: list[float] = []
    indices: list[int] = []

    for row in range(window.row_start, window.row_end + 1):
        first_vertex = len(vertices) // 3
        y_center = (center_row - row) * cell_scene
        for point_index, column in enumerate(
            range(window.col_start, window.col_end + 1)
        ):
            x = (column - center_column) * cell_scene
            z = (float(elevation[row, column]) - minimum_terrain) * scale + 0.025
            vertices.extend([x, y_center - half_row_width, z])
            vertices.extend([x, y_center + half_row_width, z])
            if point_index:
                previous = first_vertex + (point_index - 1) * 2
                current = first_vertex + point_index * 2
                # Ordem anti-horária vista de cima: as normais apontam para
                # cima e a faixa não desaparece por back-face culling.
                indices.extend(
                    [previous, current, previous + 1, previous + 1, current, current + 1]
                )

    crop_handle = int(sim.createShape(0, radians(20), vertices, indices))
    sim.setObjectAlias(crop_handle, "CropVisualization")
    sim.setShapeColor(
        crop_handle,
        None,
        sim.colorcomponent_ambient_diffuse,
        [0.42, 0.72, 0.06],
    )
    if hasattr(sim, "shapeintparam_static"):
        sim.setObjectInt32Param(crop_handle, sim.shapeintparam_static, 1)
    if hasattr(sim, "setObjectSpecialProperty"):
        sim.setObjectSpecialProperty(crop_handle, 0)
    return crop_handle


def _set_scene_appearance(sim: object) -> None:
    """Aplica cores com contraste suficiente para enxergar o relevo."""

    try:
        sim.setArrayParam(sim.arrayparam_background_color1, [0.45, 0.68, 0.88])
        sim.setArrayParam(sim.arrayparam_background_color2, [0.75, 0.86, 0.95])
        sim.setArrayParam(sim.arrayparam_ambient_light, [0.45, 0.45, 0.45])
    except Exception:
        return


def _frame_default_camera(sim: object) -> None:
    """Enquadra o centro do terreno em perspectiva oblíqua."""

    try:
        camera = sim.getObject("/DefaultCamera")
        position = np.array([-2.5, 3.3, 2.8], dtype=float)
        target = np.array([0.0, 0.0, 0.30], dtype=float)
        forward = target - position
        forward /= np.linalg.norm(forward)
        right = np.cross(np.array([0.0, 0.0, 1.0]), forward)
        right /= np.linalg.norm(right)
        up = np.cross(forward, right)
        matrix = [
            right[0], up[0], forward[0], position[0],
            right[1], up[1], forward[1], position[1],
            right[2], up[2], forward[2], position[2],
        ]
        sim.setObjectMatrix(camera, [float(value) for value in matrix], sim.handle_world)
    except Exception:
        # A cena continua utilizável mesmo se o layout padrão não tiver essa câmera.
        return


def _find_target_under(sim: object, drone_handle: int) -> int:
    for handle in sim.getObjectsInTree(drone_handle, sim.handle_all, 0):
        if str(sim.getObjectAlias(handle)).lstrip("/").lower() == "target":
            return int(handle)
    raise RuntimeError("O modelo carregado não contém um objeto com alias 'target'.")


def _find_dynamic_body(sim: object, drone_handle: int) -> int | None:
    try:
        if sim.getObjectType(drone_handle) == sim.sceneobject_shape:
            return int(drone_handle)
    except Exception:
        pass
    shapes: list[tuple[int, int]] = []
    for handle in sim.getObjectsInTree(drone_handle, sim.handle_all, 0):
        try:
            if sim.getObjectType(handle) != sim.sceneobject_shape:
                continue
            alias = str(sim.getObjectAlias(handle)).lower()
            dynamic = int(bool(sim.isDynamicallyEnabled(handle)))
            priority = 0 if "respondable" in alias else 1
            shapes.append((priority - dynamic, int(handle)))
        except Exception:
            continue
    return min(shapes)[1] if shapes else None


def _create_tree_obstacle(
    sim: object,
    model_path: Path,
    name: str,
    x_m: float,
    y_m: float,
    elevation: np.ndarray,
    cell_size_m: float,
    scale: float,
) -> int:
    """Carrega uma árvore estática alinhada ao mesmo grid usado pelo A*."""

    model_handle = int(sim.loadModel(to_coppeliasim_path(model_path)))
    objects = list(sim.getObjectsInTree(model_handle, sim.handle_all, 0))
    shapes = [
        item for item in objects
        if sim.getObjectType(item) == sim.sceneobject_shape
    ]
    if not shapes:
        raise RuntimeError("O modelo de árvore não contém nenhuma shape.")
    if len(shapes) != 1:
        raise RuntimeError("O modelo de árvore esperado precisa conter uma única shape.")

    # O Tree.ttm oficial usa um script de customização que redimensiona a
    # árvore depois do carregamento. Mantemos só a geometria para que a escala
    # do experimento seja determinística.
    tree_handle = int(shapes[0])
    sim.setObjectParent(tree_handle, sim.handle_world, True)
    try:
        sim.removeModel(model_handle)
    except Exception:
        sim.removeObject(model_handle)

    shape_heights = [float(sim.getShapeBB(item)[0][2]) for item in shapes]
    sim.scaleObjects(
        shapes, TREE_VISUAL_HEIGHT_M * scale / max(shape_heights), True
    )
    sim.setObjectAlias(tree_handle, name)

    grid = local_xy_to_grid(
        x_m, y_m, elevation.shape, cell_size_m, cell_size_m
    )
    ground_z = (float(elevation[grid]) - float(np.min(elevation))) * scale
    sim.setObjectPosition(
        tree_handle,
        [
            x_m * scale,
            y_m * scale,
            ground_z + TREE_VISUAL_HEIGHT_M * scale / 2,
        ],
        sim.handle_world,
    )
    for item in shapes:
        try:
            sim.setObjectInt32Param(item, sim.shapeintparam_static, 1)
        except Exception:
            pass
    return tree_handle


def setup_scene(
    scenario: MissionScenario,
    save_path: str | Path,
    model_path: str | Path = DEFAULT_QUADCOPTER_MODEL,
    overwrite: bool = False,
    host: str = "localhost",
    port: int = 23000,
    client_factory: Callable[..., object] | None = None,
) -> SceneSetupResult:
    destination = Path(save_path).resolve()
    if destination.exists() and not overwrite:
        return SceneSetupResult(
            False, error=f"A cena já existe: {destination}. Use --overwrite para substituí-la."
        )
    model = Path(model_path)
    if not model.is_file():
        return SceneSetupResult(False, error=f"Modelo Quadcopter não encontrado: {model}")
    if scenario.obstacles and not DEFAULT_TREE_MODEL.is_file():
        return SceneSetupResult(
            False, error=f"Modelo de árvore não encontrado: {DEFAULT_TREE_MODEL}"
        )
    try:
        terrain = load_topodata(
            scenario.terrain.topodata,
            scenario.terrain.size,
            scenario.terrain.center_lat,
            scenario.terrain.center_lon,
            scenario.terrain.area_m,
        )
        cell_size = scenario.terrain.area_m / terrain.elevation.shape[1]
        window = scenario.coverage.window
        if window is None:
            scene_elevation = terrain.elevation
            scene_window = CoverageWindow(
                0, 0, scene_elevation.shape[0] - 1, scene_elevation.shape[1] - 1
            )
        else:
            scene_elevation = terrain.elevation[
                window.row_start : window.row_end + 1,
                window.col_start : window.col_end + 1,
            ]
            scene_window = CoverageWindow(
                0, 0, scene_elevation.shape[0] - 1, scene_elevation.shape[1] - 1
            )
        scene_z_offset = (
            float(np.min(scene_elevation)) - float(np.min(terrain.elevation))
        ) * scenario.simulation.scale
        heightfield = prepare_heightfield(
            scene_elevation, cell_size, scenario.simulation.scale
        )
        if client_factory is None:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient

            client_factory = RemoteAPIClient
        client = client_factory(host=host, port=port)
        sim = client.require("sim")
        if sim.getSimulationState() != sim.simulation_stopped:
            raise RuntimeError("Pare a simulação antes de preparar a cena.")

        try:
            sim.removeDrawingObject(sim.handle_all)
        except Exception:
            pass
        _set_scene_appearance(sim)

        for path in (
            "/Drone",
            "/AgriculturalTerrain",
            "/TerrainVisualization",
            "/TerrainColorPreview",
            "/CropVisualization",
        ):
            _remove_if_present(sim, path)
        for obstacle in scenario.obstacles:
            _remove_if_present(sim, f"/{obstacle.name}")
        _remove_if_present(sim, "/Floor")

        terrain_handle = sim.createHeightfieldShape(
            0,
            radians(30),
            heightfield.x_point_count,
            heightfield.y_point_count,
            heightfield.x_size,
            heightfield.heights,
        )
        sim.setObjectAlias(terrain_handle, "AgriculturalTerrain")
        sim.setObjectPosition(
            terrain_handle, [0.0, 0.0, scene_z_offset], sim.handle_world
        )
        sim.setShapeColor(
            terrain_handle,
            None,
            sim.colorcomponent_ambient_diffuse,
            [0.34, 0.20, 0.08],
        )
        if hasattr(sim, "shapeintparam_static"):
            sim.setObjectInt32Param(terrain_handle, sim.shapeintparam_static, 1)

        terrain_visualization = _create_terrain_visualization(
            sim,
            scene_elevation,
            cell_size,
            scenario.simulation.scale,
        )
        sim.setObjectPosition(
            terrain_visualization, [0.0, 0.0, scene_z_offset], sim.handle_world
        )
        crop_visualization = _create_crop_visualization(
            sim,
            scene_elevation,
            scene_window,
            cell_size,
            scenario.simulation.scale,
        )
        sim.setObjectPosition(
            crop_visualization, [0.0, 0.0, scene_z_offset], sim.handle_world
        )

        for obstacle in scenario.obstacles:
            _create_tree_obstacle(
                sim,
                DEFAULT_TREE_MODEL,
                obstacle.name,
                obstacle.x_m,
                obstacle.y_m,
                terrain.elevation,
                cell_size,
                scenario.simulation.scale,
            )

        drone_handle = int(sim.loadModel(to_coppeliasim_path(model)))
        sim.setObjectAlias(drone_handle, "Drone")
        target_handle = _find_target_under(sim, drone_handle)
        body_handle = _find_dynamic_body(sim, drone_handle)

        # Posiciona o modelo no primeiro alvo para evitar um traslado longo antes da missão.
        spacing = max(1, round(scenario.coverage.swath_m / cell_size))
        first_target = generate_boustrophedon_targets(
            terrain.elevation, spacing, scenario.coverage.window
        )[0]
        first_waypoint = grid_path_to_waypoints_3d(
            terrain.elevation,
            [first_target],
            cell_size,
            cell_size,
            scenario.coverage.clearance_m,
        )[0]
        sim.setObjectPosition(
            drone_handle,
            [
                first_waypoint.x_m * scenario.simulation.scale,
                first_waypoint.y_m * scenario.simulation.scale,
                first_waypoint.z_m * scenario.simulation.scale,
            ],
            sim.handle_world,
        )
        _frame_default_camera(sim)

        destination.parent.mkdir(parents=True, exist_ok=True)
        sim.saveScene(to_coppeliasim_path(destination))
        return SceneSetupResult(
            True,
            destination,
            drone_handle,
            int(terrain_handle),
            target_handle,
            body_handle,
        )
    except Exception as exc:
        return SceneSetupResult(False, error=f"Falha ao preparar a cena: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepara e salva a cena agrícola no CoppeliaSim aberto."
    )
    parser.add_argument("--scenario", type=Path, default=Path("configs/demo_wind.yaml"))
    parser.add_argument("--save", type=Path, default=Path("scenes/drone_agricola_wind.ttt"))
    parser.add_argument("--model", type=Path, default=DEFAULT_QUADCOPTER_MODEL)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario = load_scenario(args.scenario)
    result = setup_scene(
        scenario, args.save, args.model, args.overwrite, args.host, args.port
    )
    if not result.success:
        raise RuntimeError(result.error)
    print(f"Cena salva em: {result.scene_path}")
    print(f"Drone: /Drone (handle {result.drone_handle})")
    print(f"Target: handle {result.target_handle}")
    print(f"Corpo dinâmico: handle {result.body_handle}")
    print(f"Terreno: /AgriculturalTerrain (handle {result.terrain_handle})")


if __name__ == "__main__":
    main()
