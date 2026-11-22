"""Monta no CoppeliaSim uma cena lado a lado de replay das telemetrias.

O replay ilustra voos físicos do simulador já registrados. Não executa uma
segunda física e não constitui uma nova medição de energia ou bateria.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from math import isfinite, radians
from pathlib import Path
from time import monotonic, sleep

import numpy as np

from src.coppelia_scene import (
    _create_crop_visualization, _create_terrain_visualization,
    _load_empty_terrain_scene, _set_scene_appearance,
)
from src.coverage import CoverageWindow
from src.waypoints import grid_path_to_waypoints_3d
from src.benchmark_report import _pairs


@dataclass(frozen=True)
class ReplayFlight:
    method: str
    label: str
    run_directory: Path
    # Metros e segundos originais; a translação só é aplicada ao desenhar.
    samples: np.ndarray  # t, x, y, z, Wh acumulados
    planned_positions: np.ndarray
    coverage_percent: float | None
    eligible: bool
    energy_available: bool
    exclusion_reasons: tuple[str, ...] = ()
    planned_cost: float | None = None
    executed_cost: float | None = None

    @property
    def duration_s(self) -> float:
        return float(self.samples[-1, 0])


def _flag(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def frame_at(flight: ReplayFlight, time_s: float) -> np.ndarray:
    """Interpola no relógio da missão e congela posição/Wh após seu término."""
    if not isfinite(time_s):
        raise ValueError("Tempo do replay precisa ser finito.")
    return np.array([
        np.interp(time_s, flight.samples[:, 0], flight.samples[:, column])
        for column in range(1, 5)
    ])


def _run_directory(raw: str, source: Path) -> Path:
    candidate = Path(raw)
    options = [candidate, source / candidate, source / "runs" / candidate.name]
    for option in options:
        if (option / "telemetry.csv").is_file():
            return option.resolve()
    raise FileNotFoundError(f"Telemetria não encontrada para {raw}.")


def _load_flight(source: Path, row: dict, plan: dict, terrain: np.ndarray,
                 scenario: dict, label: str, exclusion_reasons) -> ReplayFlight:
    folder = _run_directory(row["run_directory"], source)
    with (folder / "telemetry.csv").open(encoding="utf-8-sig", newline="") as stream:
        raw = list(csv.DictReader(stream))
    samples = np.array([
        [float(item[key]) for key in (
            "simulation_time_s", "drone_x_m", "drone_y_m", "drone_z_m")]
        for item in raw
    ], dtype=float)
    if len(samples) < 2 or not np.all(np.isfinite(samples)):
        raise ValueError("O replay exige pelo menos duas amostras finitas por voo.")
    if not np.all(np.diff(samples[:, 0]) > 0):
        raise ValueError("A telemetria precisa ter tempos estritamente crescentes.")
    original_start = float(samples[0, 0])
    samples[:, 0] -= original_start
    energy = np.zeros(len(samples))
    energy_available = _flag(row.get("energy_estimate_available"))
    if energy_available:
        energy_path = folder / "energy" / "energy_timeseries.csv"
        with energy_path.open(encoding="utf-8-sig", newline="") as stream:
            intervals = list(csv.DictReader(stream))
        ends = np.array([float(item["end_time_s"]) - original_start
                         for item in intervals])
        values = np.array([float(item["cumulative_estimated_energy_wh"])
                           for item in intervals])
        if (not len(ends) or not np.all(np.isfinite(ends))
                or not np.all(np.isfinite(values)) or not np.all(np.diff(ends) > 0)
                or np.any(values < 0) or np.any(np.diff(values) < -1e-10)
                or ends[0] <= 0 or abs(ends[-1] - samples[-1, 0]) > 1e-6):
            raise ValueError("Série de energia incompatível com a telemetria.")
        total = float(row["estimated_energy_wh"])
        if not isfinite(total) or abs(values[-1] - total) > max(1e-6, abs(total) * 1e-7):
            raise ValueError("Energia final da série difere da comparação.")
        energy = np.interp(samples[:, 0], np.r_[0., ends], np.r_[0., values])
    cell_x = float(scenario["terrain"]["area_m"]) / terrain.shape[1]
    cell_y = float(scenario["terrain"]["area_m"]) / terrain.shape[0]
    waypoints = grid_path_to_waypoints_3d(
        terrain, [tuple(item) for item in plan["path"]], cell_x, cell_y,
        float(scenario["coverage"]["clearance_m"]),
    )
    planned = np.array([[item.x_m, item.y_m, item.z_m] for item in waypoints])
    coverage = (float(row["executed_coverage_percent"])
                if row.get("executed_coverage_percent") not in (None, "") else None)
    if coverage is not None and (not isfinite(coverage) or not 0 <= coverage <= 100.):
        raise ValueError("Cobertura executada inválida na comparação.")
    return ReplayFlight(
        row["method"], label, folder, np.column_stack([samples, energy]), planned,
        coverage, not exclusion_reasons, energy_available, tuple(exclusion_reasons),
        plan.get("normalized_cost"),
        float(row["executed_normalized_cost"]) if row.get("executed_normalized_cost") not in (None, "") else None,
    )


def load_replay_pair(source: Path, reference_method="referencia_2d",
                     proposed_method="proposta_subida_orientacao"):
    """Carrega um único par já coletado e identifica planos sem adivinhar dados."""
    source = Path(source).resolve()
    protocol = json.loads((source / "protocol.json").read_text(encoding="utf-8"))
    scenario = protocol["effective_scenario"]
    with (source / "comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if reference_method == proposed_method:
        raise ValueError("Escolha dois métodos distintos para o replay.")
    aliases = {"referencia_2d": "horizontal_2d",
               "proposta_subida_orientacao": "climb_orientation"}
    aliases.update(protocol.get("method_plan_mapping", {}))
    with np.load(source / "terrain.npz") as stored:
        terrain = stored["terrain"].copy()
    selected = []
    reference_label = ("Convencional — faixas paralelas, sem A*"
                       if protocol.get("baseline_planner") == "parallel_geometric_v1"
                       else "Referência histórica — A* sem otimização proposta")
    proposed_label = ("Proposta — A* com distância e subida"
                      if protocol.get("baseline_planner") == "parallel_geometric_v1"
                      else "Proposta — planejamento otimizado")
    for method, label in ((reference_method, reference_label),
                          (proposed_method, proposed_label)):
        matching = [row for row in rows if row["method"] == method]
        if len(matching) != 1:
            raise ValueError(f"Esperado exatamente um voo do método {method}.")
        plan = next((plan for plan in protocol["plans"]
                     if plan["method"] == method), None)
        if plan is None:
            plan = next((plan for plan in protocol["plans"]
                         if plan["method"] == aliases.get(method)), None)
        if plan is None:
            raise ValueError(f"Plano não encontrado para {method}.")
        selected.append((matching[0], plan, label))
    # Usa a mesma reauditoria do relatório: flags positivas não anulam missão
    # insegura, cobertura incompleta, lacunas ou violações do envelope energético.
    audit_rows = [{**row, "geographic_case": "replay", "repetition": 1}
                  for row, _, _ in selected]
    audit = _pairs(audit_rows, {("replay", 1): {"status": "recorded", "error": ""}},
                   protocol, reference_method, proposed_method)[0]
    flights = []
    for (row, plan, label), side in zip(selected, ("reference", "proposed")):
        reasons = audit[f"{side}_exclusion_reasons"] + audit["pair_exclusion_reasons"]
        flights.append(_load_flight(source, row, plan, terrain, scenario, label, reasons))
    return protocol, terrain, flights


def _shape(sim, vertices, indices, alias, color):
    handle = int(sim.createShape(0, radians(30), vertices, indices))
    sim.setObjectAlias(handle, alias)
    sim.setShapeColor(handle, None, sim.colorcomponent_ambient_diffuse, color)
    sim.setObjectInt32Param(handle, sim.shapeintparam_static, 1)
    sim.setObjectSpecialProperty(handle, 0)
    return handle


def _route_ribbon(sim, positions: np.ndarray, alias: str, color, width=.045):
    vertices, indices = [], []
    for start, end in zip(positions, positions[1:]):
        delta = end[:2] - start[:2]
        length = float(np.linalg.norm(delta))
        if length <= 1e-12:
            continue
        side = np.array([-delta[1], delta[0], 0.]) * (width / (2 * length))
        lift = np.array([0., 0., .008])
        index = len(vertices) // 3
        for vertex in (start - side + lift, end - side + lift,
                       start + side + lift, end + side + lift):
            vertices.extend(vertex.tolist())
        indices.extend([index, index + 1, index + 2, index + 2, index + 1, index + 3])
    if indices:
        return _shape(sim, vertices, indices, alias, color)
    return None


def _create_drone(sim, alias, color, position):
    """Ícone geométrico estático; a dinâmica já foi calculada no voo de origem."""
    root = int(sim.createDummy(.001))
    sim.setObjectAlias(root, alias)
    parts = [(.22, .09, .045, 0., 0., 0.),
             (.09, .22, .045, 0., 0., 0.)]
    for x in (-.105, .105):
        for y in (-.105, .105):
            parts.append((.10, .10, .012, x, y, .018))
    for index, (sx, sy, sz, x, y, z) in enumerate(parts):
        kind = sim.primitiveshape_cuboid if index < 2 else sim.primitiveshape_cylinder
        part = int(sim.createPrimitiveShape(kind, [sx, sy, sz]))
        sim.setObjectAlias(part, f"{alias}_parte_{index}")
        sim.setObjectInt32Param(part, sim.shapeintparam_static, 1)
        sim.setObjectSpecialProperty(part, 0)
        sim.setShapeColor(part, None, sim.colorcomponent_ambient_diffuse,
                          color if index < 2 else [.12, .14, .18])
        sim.setObjectParent(part, root, False)
        sim.setObjectPosition(part, [x, y, z], root)
    sim.setObjectPosition(root, position, sim.handle_world)
    return root


def _frame_camera(sim, width, center_z):
    camera = sim.getObject("/DefaultCamera")
    position = np.array([0., -.90 * width, 1.03 * width + center_z])
    target = np.array([0., 0., center_z])
    forward = target - position
    forward /= np.linalg.norm(forward)
    right = np.cross([0., 0., 1.], forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    matrix = [float(item) for row in range(3)
              for item in (right[row], up[row], forward[row], position[row])]
    sim.setObjectMatrix(camera, matrix, sim.handle_world)
    sim.adjustView(0, camera, 0)


def _lua_string(value):
    # JSON strings share the Lua escapes used here; escape Unicode literally.
    return json.dumps(str(value), ensure_ascii=False)


def replay_script(flights, offsets, scale, rate=1., loop=False,
                  terrain_description="Relevo original; consulte o protocolo do experimento.") -> str:
    """Script autocontido salvo na cena; não depende de Python para reapresentar."""
    if not isfinite(rate) or rate <= 0:
        raise ValueError("A velocidade de reprodução precisa ser positiva e finita.")
    tables = []
    for index, (flight, offset) in enumerate(zip(flights, offsets)):
        frames = flight.samples.copy()
        frames[:, 1:4] *= scale
        frames[:, 1] += offset
        encoded = ",\n".join("{" + ",".join(f"{value:.10g}" for value in row) + "}"
                             for row in frames)
        tables.append("{alias=" + _lua_string(f"/ReplayDrone{index}")
                      + ",label=" + _lua_string(flight.label)
                      + ",cost=" + _lua_string(
                          "Custo planejado: " + (f"{flight.planned_cost:.2f}" if flight.planned_cost is not None else "indisponível")
                          + " | executado: " + (f"{flight.executed_cost:.2f}" if flight.executed_cost is not None else "indisponível"))
                      + f",available={'true' if flight.energy_available else 'false'}"
                      + f",eligible={'true' if flight.eligible else 'false'}"
                      + ",coverage=" + (f"{flight.coverage_percent:.10g}"
                                          if flight.coverage_percent is not None else "nil")
                      + ",frames={\n" + encoded + "\n}}")
    data = ",\n".join(tables)
    return _LUA.replace("__TERRAIN_DESCRIPTION__", _lua_string(terrain_description)).replace("__DATA__", data).replace("__RATE__", f"{rate:.10g}").replace(
        "__LOOP__", "true" if loop else "false")


_LUA = r'''-- Replay de telemetrias já coletadas. Energia estimada; não é bateria medida.
sim = require 'sim'
local flights = {__DATA__}
local rate = __RATE__
local loop = __LOOP__
local terrainDescription = __TERRAIN_DESCRIPTION__
local ui, duration, started, finished, lastTime = nil, 0, 0, false, -1
local trails, handles, previous = {}, {}, {}
local trailLift = 0.06

local function sample(frames,t)
    if t<=frames[1][1] then return frames[1] end
    if t>=frames[#frames][1] then return frames[#frames] end
    local lo,hi=1,#frames
    while hi-lo>1 do
        local mid=math.floor((lo+hi)/2)
        if frames[mid][1]<=t then lo=mid else hi=mid end
    end
    local a,b=frames[lo],frames[hi]
    local f=(t-a[1])/(b[1]-a[1])
    return {t,a[2]+f*(b[2]-a[2]),a[3]+f*(b[3]-a[3]),
            a[4]+f*(b[4]-a[4]),a[5]+f*(b[5]-a[5])}
end

local function clearTrails()
    for _,h in ipairs(trails) do sim.removeDrawingObject(h) end
    trails,previous={},{}
    for i=1,2 do
        trails[i]=sim.addDrawingObject(sim.drawing_lines,3,0,sim.handle_world,100000,{1,1,1})
    end
end

local function update(t)
    t=math.max(0,math.min(duration,t))
    for i,flight in ipairs(flights) do
        local p=sample(flight.frames,t)
        sim.setObjectPosition(handles[i],{p[2],p[3],p[4]},sim.handle_world)
        if previous[i] and t>lastTime then
            local q=previous[i]
            sim.addDrawingObjectItem(trails[i],{q[2],q[3],q[4]+trailLift,p[2],p[3],p[4]+trailLift})
        end
        previous[i]=p
        if ui then
            local wh=flight.available and string.format('%.4f Wh estimados',p[5]) or 'Energia indisponível'
            local done=t>=flight.frames[#flight.frames][1]
            simUI.setLabelText(ui,10*i+1,wh..(done and ' | missão encerrada' or ''))
        end
    end
    lastTime=t
    if not ui then return end
    if t>=duration then
        local a,b=flights[1],flights[2]
        if a.available and b.available and a.eligible and b.eligible and a.frames[#a.frames][5]>0 then
            local reduction=100*(1-b.frames[#b.frames][5]/a.frames[#a.frames][5])
            simUI.setLabelText(ui,2,string.format('Redução final da energia estimada: %+.4f%% (valor negativo significa aumento)',reduction))
        else
            simUI.setLabelText(ui,2,'Sem conclusão de economia: par inelegível ou energia indisponível. Consulte o benchmark.')
        end
    else
        simUI.setLabelText(ui,2,'A redução final só é exibida após o término das duas missões elegíveis.')
    end
    simUI.setLabelText(ui,1,string.format('Replay do tempo original: %.1f / %.1f s | reprodução %.1fx',t,duration,rate))
end

local menu
function toggleDetails()
    if simUI.isVisible(ui) then simUI.hide(ui) else simUI.show(ui) end
end

local function createPanels()
    simUI = require 'simUI'
    menu=simUI.create([[<ui title="Replay" closeable="false" activate="false" placement="relative" position="-20,85">
      <button text="Métricas dos voos" on-click="toggleDetails" />
    </ui>]])
    ui=simUI.create([[<ui title="Comparação lado a lado — replay dos voos registrados" closeable="true" on-close="toggleDetails" resizable="false" placement="relative" position="20,130" layout="vbox">
      <label text="REPLAY DE TELEMETRIA | energia estimada, sem medição de bateria" style="font-weight: bold; font-size: 14px;" />
      <label id="3" text="Relevo" />
      <label id="1" text="Tempo original das missões" />
      <group layout="hbox" flat="true">
        <group layout="vbox" style="background-color: #fff0d8; padding: 6px;">
          <label id="23" text="ESQUERDA: proposta" style="font-weight: bold;" />
          <label id="21" text="0 Wh estimados" />
          <label id="22" text="Cobertura executada" />
          <label id="24" text="Custo normalizado" />
        </group>
        <group layout="vbox" style="background-color: #dcecff; padding: 6px;">
          <label id="13" text="DIREITA: referência" style="font-weight: bold;" />
          <label id="11" text="0 Wh estimados" />
          <label id="12" text="Cobertura executada" />
          <label id="14" text="Custo normalizado" />
        </group>
      </group>
      <label text="Rotas coloridas: planos | trilha branca: execução registrada | relógios não normalizados" />
      <label text="Custo normalizado = distância 3D + peso × subida | energia estimada em Wh" />
      <label id="2" text="Aguardando término das missões" />
      <label text="Os drones são ícones sem física. A comparação numérica vem das missões registradas." />
    </ui>]])
    simUI.hide(ui)
    simUI.setLabelText(ui,3,terrainDescription)
    simUI.setLabelText(ui,23,'ESQUERDA: '..flights[2].label)
    simUI.setLabelText(ui,13,'DIREITA: '..flights[1].label)
    for i,flight in ipairs(flights) do
        local status=flight.eligible and 'elegível para comparação' or 'INELEGÍVEL para comparação'
        local coverage=flight.coverage and string.format('%.2f%%',flight.coverage) or 'indisponível'
        simUI.setLabelText(ui,10*i+2,'Cobertura geométrica: '..coverage..' | '..status)
        simUI.setLabelText(ui,10*i+4,flight.cost)
    end
end

function sysCall_init()
    for i,flight in ipairs(flights) do
        handles[i]=sim.getObject(flight.alias)
        duration=math.max(duration,flight.frames[#flight.frames][1])
    end
    if not sim.getBoolParam(sim.boolparam_headless) then createPanels() end
    clearTrails()
    update(0)
end

function sysCall_beforeSimulation()
    started=sim.getSimulationTime()
    finished=false
    lastTime=-1
    clearTrails()
    update(0)
end

function sysCall_sensing()
    if finished then return end
    local t=(sim.getSimulationTime()-started)*rate
    if t>=duration and loop then
        started=sim.getSimulationTime()
        lastTime=-1
        clearTrails()
        t=0
    end
    update(t)
    if t>=duration and not loop then
        finished=true
        sim.pauseSimulation()
    end
end

function sysCall_afterSimulation()
    lastTime=-1
    clearTrails()
    update(0)
end

function sysCall_cleanup()
    if menu then simUI.destroy(menu) end
    if ui then simUI.destroy(ui) end
    for _,h in ipairs(trails) do sim.removeDrawingObject(h) end
end
'''


def create_comparison_scene(source: Path, output: Path,
                            reference_method="referencia_2d",
                            proposed_method="proposta_subida_orientacao",
                            host="127.0.0.1", port=23000,
                            replay=False, loop=False, rate=1., realtime=False,
                            client_factory=None) -> Path:
    """Salva backup, monta duas cópias visuais e embute replay autocontido.

    Os parâmetros de visualização nunca alteram os CSVs nem o benchmark.
    """
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    protocol, terrain, flights = load_replay_pair(source, reference_method, proposed_method)
    scenario = protocol["effective_scenario"]
    scale = float(scenario["simulation"]["scale"])
    if not isfinite(scale) or scale <= 0 or not isfinite(rate) or rate <= 0:
        raise ValueError("Escala e velocidade de reprodução precisam ser positivas e finitas.")
    if client_factory is None:
        from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        client_factory = RemoteAPIClient
    sim = client_factory(host=host, port=port).require("sim")
    if sim.getSimulationState() != sim.simulation_stopped:
        raise RuntimeError("Pare a simulação antes de preparar o replay lado a lado.")
    output.mkdir(parents=True, exist_ok=False)
    sim.saveScene((output / "scene_before.ttt").as_posix())
    _load_empty_terrain_scene(sim)
    _set_scene_appearance(sim)
    cell = float(scenario["terrain"]["area_m"]) / terrain.shape[1]
    raw_window = scenario["coverage"].get("window")
    window = CoverageWindow(**raw_window) if raw_window else CoverageWindow(
        0, 0, terrain.shape[0] - 1, terrain.shape[1] - 1)
    mission_window = window
    window = window.expanded(scenario["simulation"].get("terrain_padding_cells", 0), terrain.shape)
    application_window = CoverageWindow(
        mission_window.row_start - window.row_start, mission_window.col_start - window.col_start,
        mission_window.row_end - window.row_start, mission_window.col_end - window.col_start)
    crop = terrain[window.row_start:window.row_end + 1,
                   window.col_start:window.col_end + 1]
    width = max(crop.shape[1] * cell * scale, 1.)
    separation = width + .8
    offsets = [separation / 2, -separation / 2]
    # Centragem do recorte no referencial do grid completo, sem mover trajetórias.
    crop_x = ((window.col_start + window.col_end) / 2 - (terrain.shape[1] - 1) / 2) * cell * scale
    crop_y = ((terrain.shape[0] - 1) / 2 - (window.row_start + window.row_end) / 2) * cell * scale
    crop_z = (float(np.min(crop)) - float(np.min(terrain))) * scale
    colors = [[.12, .45, .93], [1., .53, .07]]
    for index, (flight, offset, color) in enumerate(zip(flights, offsets, colors)):
        tile = _create_terrain_visualization(sim, crop, cell, scale)
        sim.setObjectAlias(tile, f"ReplayTerrain{index}")
        sim.setObjectPosition(tile, [offset + crop_x, crop_y, crop_z], sim.handle_world)
        crop_handle = _create_crop_visualization(
            sim, crop, application_window, cell, scale)
        sim.setObjectAlias(crop_handle, f"ReplayCrop{index}")
        sim.setObjectPosition(crop_handle, [offset + crop_x, crop_y, crop_z], sim.handle_world)
        positions = flight.planned_positions * scale
        positions[:, 0] += offset
        _route_ribbon(sim, positions, f"ReplayPlannedRoute{index}", color)
        start = flight.samples[0, 1:4] * scale
        start[0] += offset
        _create_drone(sim, f"ReplayDrone{index}", color, start.tolist())
        for number, obstacle in enumerate(scenario.get("obstacles", [])):
            x, y = float(obstacle["x_m"]), float(obstacle["y_m"])
            row = round((terrain.shape[0] - 1) / 2 - y / cell)
            column = round((terrain.shape[1] - 1) / 2 + x / cell)
            row = min(terrain.shape[0] - 1, max(0, row))
            column = min(terrain.shape[1] - 1, max(0, column))
            z = (float(terrain[row, column]) - float(np.min(terrain))) * scale
            marker = int(sim.createPrimitiveShape(sim.primitiveshape_cylinder, [.12, .12, .40]))
            sim.setObjectAlias(marker, f"ReplayObstacle{index}_{number}")
            sim.setObjectInt32Param(marker, sim.shapeintparam_static, 1)
            sim.setObjectSpecialProperty(marker, 0)
            sim.setShapeColor(marker, None, sim.colorcomponent_ambient_diffuse, [.18, .27, .13])
            sim.setObjectPosition(marker, [offset + x * scale, y * scale, z + .20], sim.handle_world)
    mission_elevation = terrain[mission_window.row_start:mission_window.row_end + 1,
                                 mission_window.col_start:mission_window.col_end + 1]
    factor = float(scenario["terrain"].get("height_scale", 1.))
    description = (f"Relevo {'sintético amplificado' if factor != 1 else 'original'} ×{factor:g} | "
                   f"desnível da missão {float(np.ptp(mission_elevation)):.2f} m | mesmo terreno nos dois lados")
    code = replay_script(flights, offsets, scale, rate, loop, description)
    (output / "replay.lua").write_text(code, encoding="utf-8")
    script = sim.createScript(sim.scripttype_customization, code, 0, "lua")
    sim.setObjectAlias(script, "ReplayTelemetrias")
    sim.setObjectSelection([])
    if not sim.getBoolParam(sim.boolparam_headless):
        sim.setBoolParam(sim.boolparam_infotext_visible, False)
        center_z = crop_z + float(np.mean(crop - np.min(crop))) * scale + .25
        _frame_camera(sim, separation + width + .8, center_z)
    scene_path = output / "comparacao_lado_a_lado.ttt"
    # A cena reaberta deve conservar a mesma cadência da apresentação inicial.
    sim.setBoolParam(sim.boolparam_realtime_simulation, realtime)
    sim.saveScene(scene_path.as_posix())
    manifest = {
        "source": str(Path(source).resolve()),
        "terrain_description": description,
        "height_scale": factor,
        "source_protocol_sha256": hashlib.sha256((Path(source) / "protocol.json").read_bytes()).hexdigest(),
        "reference_method": flights[0].method, "proposed_method": flights[1].method,
        "scene": str(scene_path), "playback_rate": rate, "loop": loop, "realtime": realtime,
        "scope": "Replay visual de telemetrias de voos do simulador; sem física nova. Energia estimada, sem medição de bateria.",
        "clock_policy": "Mesmo tempo decorrido original; posição e energia congelam ao término de cada missão. Sem normalização de duração.",
        "flights": [{"method": flight.method, "run_directory": str(flight.run_directory),
                     "duration_s": flight.duration_s,
                     "final_estimated_energy_wh": float(flight.samples[-1, 4]) if flight.energy_available else None,
                     "comparison_eligible": flight.eligible,
                     "comparison_exclusion_reasons": list(flight.exclusion_reasons),
                     "telemetry_sha256": hashlib.sha256((flight.run_directory / "telemetry.csv").read_bytes()).hexdigest(),
                     "visual_offset_scene_units": offset}
                    for flight, offset in zip(flights, offsets)],
    }
    (output / "replay_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if replay:
        # O próprio Lua sincroniza os dois lados. Tempo real controla somente a apresentação.
        sim.setStepping(False)
        sim.startSimulation()
        if not loop:
            deadline = monotonic() + max(60., max(f.duration_s for f in flights) / rate * (2. if realtime else 1.) + 60.)
            while sim.getSimulationState() not in (sim.simulation_paused, sim.simulation_stopped):
                if monotonic() > deadline:
                    raise RuntimeError("O replay não concluiu no tempo previsto; a cena salva pode ser reaberta.")
                sleep(.1)
    return scene_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pasta de um par de voos coletado por coverage_comparison.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", default="referencia_2d")
    parser.add_argument("--proposed", default="proposta_subida_orientacao")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--replay", action="store_true", help="Inicia a reprodução e deixa o resultado final pausado.")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--rate", type=float, default=1.)
    parser.add_argument("--realtime", action="store_true", help="Apresenta no tempo de parede, dividido por --rate.")
    args = parser.parse_args()
    result = create_comparison_scene(args.source, args.output, args.reference, args.proposed,
                                     args.host, args.port, args.replay, args.loop, args.rate, args.realtime)
    print(f"Cena de replay salva: {result}")


if __name__ == "__main__":
    main()
