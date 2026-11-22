"""Apresenta todos os cenários e suas rotas planejadas na mesma cena."""

import argparse
import csv
from datetime import datetime
from math import isfinite
from pathlib import Path

import numpy as np

from src.benchmark import check_simulator, find_recorded_pair
from src.comparison_scene import _create_drone, _frame_camera, _lua_string, _route_ribbon
from src.coppelia_scene import (
    _create_crop_visualization, _create_terrain_visualization, _create_tree_obstacle,
    _load_empty_terrain_scene, _set_scene_appearance,
)
from src.coverage import CoverageWindow
from src.coverage_comparison import plan_coverage_routes
from src.planning_experiments import case_from_scenario
from src.scenario import load_scenario
from src.waypoints import grid_path_to_waypoints_3d


SCENARIOS = (
    ("demo_coverage", "Original"),
    ("demo_obstacles", "12 árvores"),
    ("serra_do_cipo", "Serra do Cipó"),
    ("monte_verde", "Monte Verde"),
)


def create_presentation(output: Path, port: int = 23000) -> Path:
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient

    output = output.resolve()
    settings = []
    for scenario_id, name in SCENARIOS:
        path = Path("configs") / f"{scenario_id}.yaml"
        scenario = load_scenario(path)
        case = case_from_scenario(path)
        plans, window = plan_coverage_routes(case, scenario)
        settings.append((name, scenario, case, plans, window))

    benchmark_labels = _benchmark_labels(Path("output/experiments").resolve())
    check_simulator(port=port)
    sim = RemoteAPIClient(port=port).require("sim")
    if sim.getSimulationState() != sim.simulation_stopped:
        raise RuntimeError("Clique em Stop no CoppeliaSim antes de abrir a apresentação.")

    output.mkdir(parents=True, exist_ok=False)
    backup = (output / "scene_before.ttt").as_posix()
    sim.saveScene(backup)
    app = Path(sim.getStringParam(sim.stringparam_application_path))
    try:
        _load_empty_terrain_scene(sim)
        _set_scene_appearance(sim)
        _populate_scene(sim, app, settings, benchmark_labels)
        scene_path = output / "todos_os_cenarios.ttt"
        sim.saveScene(scene_path.as_posix())
    except Exception:
        sim.loadScene(backup)
        raise
    return scene_path


def _benchmark_labels(root: Path) -> list[str]:
    labels = []
    has_ineligible = False
    for scenario_id, name in SCENARIOS:
        path = Path("configs") / f"{scenario_id}.yaml"
        pair = find_recorded_pair(root, path)
        if pair is None:
            labels.append(f"{name}: sem coleta")
            continue
        with (pair / "comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = {row["method"]: row for row in csv.DictReader(stream)}
        results = []
        for method in ("proposta_subida_orientacao", "referencia_2d"):
            row = rows[method]
            coverage = _display_metric(row.get("executed_coverage_percent"), "%")
            energy = _display_metric(row.get("estimated_energy_wh"), " Wh")
            marker = "" if row.get("energy_comparison_eligible") == "True" else "*"
            has_ineligible |= bool(marker)
            results.append(f"{coverage} · {energy}{marker}")
        labels.append(f"{name}: {results[0]}  |  {results[1]}")
    if has_ineligible:
        labels.append("* Voo inelegível para comparação de energia")
    return labels


def _display_metric(value: str | None, unit: str) -> str:
    try:
        number = float(value or "")
    except ValueError:
        return "—"
    return f"{number:.1f}".replace(".", ",") + unit if isfinite(number) else "—"


def _populate_scene(sim, app, settings, benchmark_labels):
    tile_size = max(max(window.row_end - window.row_start + 1,
                        window.col_end - window.col_start + 1)
                    * case.cell_x_m * scenario.simulation.scale
                    for _, scenario, case, _, window in settings)
    spacing = tile_size + 1.6
    flight_tables = []
    for column, (name, scenario, case, plans, window) in enumerate(settings):
        scale = scenario.simulation.scale
        cell = case.cell_x_m
        terrain = case.terrain
        mission = case.window
        crop = terrain[window.row_start:window.row_end + 1, window.col_start:window.col_end + 1]
        application_window = CoverageWindow(
            mission.row_start - window.row_start, mission.col_start - window.col_start,
            mission.row_end - window.row_start, mission.col_end - window.col_start,
        )
        crop_origin = np.array([
            ((window.col_start + window.col_end) / 2 - (terrain.shape[1] - 1) / 2) * cell * scale,
            ((terrain.shape[0] - 1) / 2 - (window.row_start + window.row_end) / 2) * cell * scale,
            (float(np.min(crop)) - float(np.min(terrain))) * scale,
        ])
        for row, (plan, color) in enumerate(zip(
            plans, ([.12, .45, .93], [1., .53, .07]),
        )):
            alias = f"Painel{column}_{row}"
            center = np.array([(column - (len(settings) - 1) / 2) * spacing,
                               (row - .5) * spacing, 0.])
            offset = center - crop_origin
            tile = _create_terrain_visualization(sim, crop, cell, scale)
            crop_handle = _create_crop_visualization(sim, crop, application_window, cell, scale)
            for handle, kind in ((tile, "Terreno"), (crop_handle, "Cultivo")):
                sim.setObjectAlias(handle, f"{kind}{alias}")
                sim.setObjectPosition(handle, center.tolist(), sim.handle_world)
            for number, obstacle in enumerate(scenario.obstacles):
                tree = _create_tree_obstacle(sim, app / "models/nature/Tree.ttm",
                                             f"Arvore{alias}_{number}", obstacle.x_m, obstacle.y_m,
                                             terrain, cell, scale)
                position = np.array(sim.getObjectPosition(tree, sim.handle_world)) + offset
                sim.setObjectPosition(tree, position.tolist(), sim.handle_world)

            waypoints = grid_path_to_waypoints_3d(
                terrain, plan.path, cell, case.cell_y_m, scenario.coverage.clearance_m,
            )
            positions = np.array([[item.x_m, item.y_m, item.z_m] for item in waypoints])
            durations = np.linalg.norm(np.diff(positions, axis=0), axis=1) / scenario.simulation.speed_mps
            keep = np.r_[True, durations > 0]
            timestamps = np.r_[0., np.cumsum(durations)][keep]
            positions = positions[keep] * scale + offset
            _route_ribbon(sim, positions, f"Rota{alias}", color, width=.065)
            drone_alias = f"Drone{alias}"
            drone = _create_drone(sim, drone_alias, color, positions[0].tolist())
            sim.scaleObjects([drone, *sim.getObjectsInTree(drone, sim.handle_all, 1)], 1.6, False)
            frames = ",\n".join("{" + ",".join(f"{value:.10g}" for value in frame) + "}"
                                for frame in np.column_stack([timestamps, positions]))
            flight_tables.append(
                f"{{alias={_lua_string('/' + drone_alias)}, frames={{\n{frames}\n}}}}"
            )

    code = _LUA.replace("__ROUTES__", ",\n".join(flight_tables))
    code = code.replace("__COLUMNS__", _lua_string("   ·   ".join(name for name, *_ in settings)))
    code = code.replace("__BENCHMARK__", _lua_string("\n".join(benchmark_labels)))
    script = sim.createScript(sim.scripttype_customization, code, 0, "lua")
    sim.setObjectAlias(script, "AnimacaoRotasPlanejadas")
    sim.setObjectSelection([])
    if not sim.getBoolParam(sim.boolparam_headless):
        sim.setBoolParam(sim.boolparam_infotext_visible, False)
        _frame_camera(sim, len(settings) * spacing * .88, 1.)
    sim.setBoolParam(sim.boolparam_realtime_simulation, True)


_LUA = '''sim = require 'sim'
local routes = {__ROUTES__}
local playbackRate = 8
local duration = 0
local ui

function sysCall_init()
    if not sim.getBoolParam(sim.boolparam_headless) then
        simUI = require 'simUI'
        ui = simUI.create([[<ui title="Rotas planejadas" placement="relative" position="12,110" activate="false" closeable="false" layout="vbox">
            <label id="1" text="" />
            <label text="Linha superior: A* (laranja)   |   Linha inferior: convencional (azul)" />
            <label text="Voos registrados · Cobertura e energia estimada" style="font-weight: bold;" />
            <label text="A*  |  Convencional" />
            <label id="2" text="" />
        </ui>]])
        simUI.setLabelText(ui, 1, __COLUMNS__)
        simUI.setLabelText(ui, 2, __BENCHMARK__)
    end
    for _,route in ipairs(routes) do
        route.handle = sim.getObject(route.alias)
        duration = math.max(duration, route.frames[#route.frames][1])
    end
end

function sysCall_beforeSimulation()
    for _,route in ipairs(routes) do route.index = 1 end
end

function sysCall_sensing()
    local t = sim.getSimulationTime() * playbackRate
    for _,route in ipairs(routes) do
        local frames = route.frames
        while route.index < #frames and frames[route.index + 1][1] <= t do
            route.index = route.index + 1
        end
        local a = frames[route.index]
        local b = frames[math.min(route.index + 1, #frames)]
        local fraction = 0
        if b[1] > a[1] then fraction = (t - a[1]) / (b[1] - a[1]) end
        sim.setObjectPosition(route.handle, {
            a[2] + (b[2] - a[2]) * fraction,
            a[3] + (b[3] - a[3]) * fraction,
            a[4] + (b[4] - a[4]) * fraction,
        }, sim.handle_world)
    end
    if t >= duration then sim.pauseSimulation() end
end

function sysCall_cleanup()
    if ui then simUI.destroy(ui) end
end
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=23000)
    args = parser.parse_args(argv)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    scene = create_presentation(Path("output/experiments") / f"apresentacao_todos_{stamp}", args.port)
    print(f"Cena com {len(SCENARIOS)} cenários: {scene}")
    print(f"Aperte Play para animar as {2 * len(SCENARIOS)} rotas planejadas.")


if __name__ == "__main__":
    main()
