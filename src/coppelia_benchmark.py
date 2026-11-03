"""Executa a física no CoppeliaSim com controle e coleta locais em Lua.

O drone continua sendo movido pelo controlador original do Quadcopter. Apenas
o target recebe comandos de posição durante o voo. A máquina de estados
reproduz a interpolação, estabilização e espera do executor por RPC.
"""

import hashlib
import json
from math import isclose, isfinite
from pathlib import Path
from time import monotonic, sleep

import cbor2
import numpy as np

from src.coppeliasim import (
    SimulationLog, TelemetrySample, _route_scene_positions,
    _save_simulation_log, discover_drone, discover_target,
)
from src.telemetry_metrics import _flag


EXECUTOR = "lua_physics_v1"
STATUS_TAG = "coverage_benchmark.status"
BLOCK_TAG = "coverage_benchmark.samples."
CHUNK_SAMPLES = 128


# O script é filho do drone, com prioridade first. sysCall_actuation comanda
# o alvo antes do controlador original; sysCall_sensing lê depois da física.
LUA_EXECUTOR = r'''
sim = require('sim')
local cfg = __CONFIGURATION__
local state = {done=false, success=false, error='', steps=0, waypoints_completed=0,
               targets_completed=0, collisions=0, clearance_violations=0,
               next_block=0, simulation_time_s=0, physics_observed=false}
local owner, droneCollection, collisionHandles, droneShapes
local buffer = {}
local routeIndex, completedTargets, warmupRemaining = 1, 0, 0
local phase, waypointStarted, segmentStart, segmentSteps, segmentStep
local commanded, sampleActive, startedAt, lastStatus = nil, false, 0, -math.huge

local function finite(v)
    return type(v)=='number' and v==v and math.abs(v)<math.huge
end

local function vector(v)
    assert(type(v)=='table' and #v==3, 'Posição ausente ou inválida')
    for i=1,3 do assert(finite(v[i]), 'Posição não finita no simulador') end
    return v
end

local function distance(a,b)
    return math.sqrt((a[1]-b[1])^2+(a[2]-b[2])^2+(a[3]-b[3])^2)
end

local function writeBlock()
    if #buffer>0 then
        sim.writeCustomDataBlock(owner, cfg.block_tag..string.format('%06d',state.next_block), sim.packTable(buffer,1))
        state.next_block=state.next_block+1
        buffer={}
    end
end

local function publish(force)
    if force or state.simulation_time_s-lastStatus>=0.5 then
        sim.writeCustomDataBlock(owner,cfg.status_tag,sim.packTable(state,1))
        lastStatus=state.simulation_time_s
    end
end

local function finish(success,message,stop)
    if state.done then return end
    state.done=true
    state.success=success
    state.error=message or ''
    writeBlock()
    publish(true)
    if stop~=false then sim.stopSimulation() end
end

local function guard(fn)
    local ok,message=xpcall(fn,debug.traceback)
    if not ok then finish(false,tostring(message)) end
end

local function roundEven(value)
    local lower=math.floor(value)
    local fraction=value-lower
    if fraction>0.5 or (fraction==0.5 and lower%2~=0) then return lower+1 end
    return lower
end

local function groundAt(position)
    local row=roundEven((cfg.rows-1)/2-position[2]/cfg.scale/cfg.cell_y_m)
    local col=roundEven((cfg.columns-1)/2+position[1]/cfg.scale/cfg.cell_x_m)
    row=math.min(cfg.rows-1,math.max(0,row))
    col=math.min(cfg.columns-1,math.max(0,col))
    return cfg.ground_m[row*cfg.columns+col+1]
end

local function initialize()
    owner=sim.getObject('.')
    assert(sim.getBoolParam(sim.boolparam_dynamics_handling_enabled), 'A física do simulador precisa estar habilitada')
    local step=sim.getSimulationTimeStep()
    assert(finite(step) and step>0, 'Passo do simulador inválido')
    assert(math.abs(step-cfg.time_step_s)<1e-9, 'Passo do simulador mudou antes da execução')
    startedAt=sim.getSimulationTime()
    state.simulation_time_s=startedAt
    droneShapes=sim.getObjectsInTree(cfg.drone,sim.sceneobject_shape,0)
    assert(#droneShapes>0, 'Drone sem shapes para monitoramento de colisão')
    -- Override garante que todas as shapes entrem mesmo com collidable desligado.
    droneCollection=sim.createCollection(1)
    for _,shape in ipairs(droneShapes) do
        sim.addItemToCollection(droneCollection,sim.handle_single,shape,0)
    end
    collisionHandles={sim.getObject('/AgriculturalTerrain')}
    assert(sim.getObjectType(collisionHandles[1])==sim.sceneobject_shape, 'Terreno não é uma shape')
    for _,name in ipairs(cfg.obstacle_names) do
        local model=sim.getObject('/'..name)
        local shapes=sim.getObjectsInTree(model,sim.sceneobject_shape,0)
        assert(#shapes>0, 'Obstáculo sem shapes: '..name)
        for _,shape in ipairs(shapes) do collisionHandles[#collisionHandles+1]=shape end
    end
    -- Testa toda a monitoração antes de iniciar a missão. Erros não viram ausência de colisão.
    for _,handle in ipairs(collisionHandles) do
        local result=sim.checkCollision(droneCollection,handle)
        assert(result==0 or result==1, 'Resposta inválida no monitoramento de colisão')
    end
    warmupRemaining=math.ceil(cfg.warmup_s/step)
    phase=warmupRemaining>0 and 'warmup' or 'prepare'
    commanded=vector(sim.getObjectPosition(cfg.target,sim.handle_world))
    publish(true)
end

function sysCall_init()
    owner=sim.getObject('.')
    guard(initialize)
end

local function actuate()
    if state.done then return end
    local goal=cfg.positions[routeIndex]
    sampleActive=phase~='warmup'
    if phase=='prepare' then
        waypointStarted=sim.getSimulationTime()
        segmentStart=vector(sim.getObjectPosition(cfg.target,sim.handle_world))
        segmentSteps=math.ceil(distance(segmentStart,goal)/(cfg.speed_mps*cfg.scale*cfg.time_step_s))
        segmentStep=0
        phase=segmentSteps>0 and 'move' or 'wait'
    end
    if phase=='move' then
        segmentStep=segmentStep+1
        commanded={}
        for axis=1,3 do
            commanded[axis]=segmentStart[axis]+(goal[axis]-segmentStart[axis])*segmentStep/segmentSteps
        end
    elseif phase=='wait' then
        commanded=goal
    end
    -- ÚNICA manipulação de pose durante o voo: o alvo do controlador físico.
    sim.setObjectPosition(cfg.target,commanded,sim.handle_world)
end

function sysCall_actuation()
    guard(actuate)
end

local function sense()
    if state.done then return end
    assert(sim.getBoolParam(sim.boolparam_dynamics_handling_enabled), 'A física foi desabilitada durante a missão')
    local dynamic=false
    for _,shape in ipairs(droneShapes) do
        if sim.isDynamicallyEnabled(shape) then dynamic=true end
    end
    assert(dynamic, 'Drone sem shape dinamicamente habilitada após a física')
    state.physics_observed=true
    local position=vector(sim.getObjectPosition(cfg.drone,sim.handle_world))
    local target=vector(sim.getObjectPosition(cfg.target,sim.handle_world))
    -- Em sensing, a física deste passo já ocorreu, mas o relógio avança só
    -- depois do main script: associamos a pose ao fim do intervalo físico.
    local now=sim.getSimulationTime()+cfg.time_step_s
    assert(finite(now) and now>state.simulation_time_s, 'Tempo inválido ou não crescente')
    local clearance=position[3]/cfg.scale-groundAt(position)
    local violation=clearance<cfg.minimum_clearance_m
    local collision=false
    -- Sem short-circuit: toda shape ambiental é verificada em cada passo.
    for _,handle in ipairs(collisionHandles) do
        local result=sim.checkCollision(droneCollection,handle)
        assert(result==0 or result==1, 'Resposta inválida no monitoramento de colisão')
        if result>0 then collision=true end
    end
    state.steps=state.steps+1
    state.simulation_time_s=now
    state.collisions=state.collisions+(collision and 1 or 0)
    state.clearance_violations=state.clearance_violations+(violation and 1 or 0)
    buffer[#buffer+1]={now,0,routeIndex-1,completedTargets,
        position[1]/cfg.scale,position[2]/cfg.scale,position[3]/cfg.scale,
        target[1]/cfg.scale,target[2]/cfg.scale,target[3]/cfg.scale,
        distance(position,target)/cfg.scale,'sem_vento',0,0,clearance,violation,collision,sampleActive}
    if #buffer>=cfg.chunk_samples then writeBlock() end
    if now-startedAt>cfg.global_timeout_s then
        finish(false,'Tempo limite global da missão excedido.')
        return
    end
    if phase=='warmup' then
        warmupRemaining=warmupRemaining-1
        if warmupRemaining<=0 then phase='prepare' end
    elseif phase=='move' then
        if segmentStep>=segmentSteps then phase='wait' end
    elseif phase=='wait' then
        local goal=cfg.positions[routeIndex]
        if distance(position,goal)<=cfg.tolerance_m*cfg.scale then
            local cell=cfg.path[routeIndex]
            local nextTarget=cfg.targets[completedTargets+1]
            if nextTarget and cell[1]==nextTarget[1] and cell[2]==nextTarget[2] then
                completedTargets=completedTargets+1
            end
            state.targets_completed=completedTargets
            state.waypoints_completed=state.waypoints_completed+1
            routeIndex=routeIndex+1
            phase='prepare'
            if routeIndex>#cfg.positions then
                local complete=completedTargets>=#cfg.targets
                finish(complete,complete and '' or 'A rota terminou antes de todos os alvos de cobertura.')
                return
            end
        elseif now-waypointStarted>cfg.waypoint_timeout_s then
            finish(false,'Timeout aguardando o drone no waypoint '..tostring(routeIndex-1)..'.')
            return
        end
    end
    publish(false)
end

function sysCall_sensing()
    guard(sense)
end

function sysCall_cleanup()
    local ok,message=xpcall(function()
        if not state.done then
            finish(false,'Simulação interrompida antes da conclusão da missão.',false)
        else
            writeBlock()
            publish(true)
        end
        if droneCollection then sim.destroyCollection(droneCollection) end
    end,debug.traceback)
    if not ok then
        state.done=true
        state.success=false
        state.error='Falha na limpeza do executor Lua: '..tostring(message)
        pcall(writeBlock)
        pcall(function() publish(true) end)
    end
end
'''


def _lua(value):
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{" + ",".join(f"[{_lua(str(k))}]={_lua(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(_lua(v) for v in value) + "}"
    if isinstance(value, (int, float)) and isfinite(value):
        return repr(value)
    raise ValueError(f"Valor inválido para o executor Lua: {value!r}")


def _decode(buffer):
    if not buffer:
        return None
    def text_keys(value):
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, list):
            return [text_keys(v) for v in value]
        if isinstance(value, dict):
            return {text_keys(k): text_keys(v) for k, v in value.items()}
        return value
    return text_keys(cbor2.loads(bytes(buffer)))


def _append_telemetry(log, rows, time_step, path_length):
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Bloco de telemetria ausente ou inválido.")
    for values in rows:
        if not isinstance(values, list) or len(values) != len(TelemetrySample.__dataclass_fields__):
            raise RuntimeError("Amostra de telemetria com formato inválido.")
        for i in (0, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14):
            if isinstance(values[i], bool) or not isinstance(values[i], (float, int)) or not isfinite(values[i]):
                raise RuntimeError("Telemetria contém valor não finito ou inválido.")
        for i in (1, 2, 3):
            if isinstance(values[i], bool) or not isinstance(values[i], int) or values[i] < 0:
                raise RuntimeError("Índice de telemetria inválido.")
        if values[1] != 0 or values[2] >= path_length or values[10] < 0:
            raise RuntimeError("Revisão, waypoint ou erro de rastreamento inválido.")
        for i in (15, 16, 17):
            values[i] = _flag(values[i])
        if log.telemetry and not isclose(values[0] - log.telemetry[-1].simulation_time_s,
                                         time_step, rel_tol=1e-7, abs_tol=1e-8):
            raise RuntimeError("Telemetria não crescente ou com passos físicos ausentes.")
        log.telemetry.append(TelemetrySample(*values))


def _disable_remote_stepping(sim):
    """ZMQ acumula níveis e trata qualquer número, inclusive zero, como True."""
    previous = sim.setStepping(False)
    if isinstance(previous, bool) or not isinstance(previous, int) or previous < 0:
        raise RuntimeError("Nível de stepping remoto inválido.")
    # A primeira chamada já removeu um nível. Drena os restantes para que o
    # executor físico realmente possa avançar sem sim.step() por RPC.
    for _ in range(max(0, previous - 1)):
        sim.setStepping(False)
    return previous


def run_coverage_mission(
    scenario, terrain, targets, initial_path, scenario_path, host="127.0.0.1", port=23000,
    client_factory=None, replanning_enabled=False, strict_safety=True, *,
    disable_rendering=False, poll_interval_s=.1, wall_timeout_s=None,
) -> SimulationLog:
    """Mantém física e controlador originais; elimina RPCs por passo físico.

    Requer rota fechada e vento zero. A criação do script, posição inicial e
    orientação acontecem com o simulador parado. Monitoramento indisponível
    invalida a missão; não é convertido em ausência de colisão.
    """
    log = SimulationLog(False, scenario.scenario_id, 0, 0, 0, 0, [], [], [initial_path.copy()],
                        replanning_enabled=False)
    sim = script = previous_display = previous_stepping = None
    started = False
    headless = None
    script_text = ""
    status = {}
    wall_started = monotonic()
    try:
        if replanning_enabled or not strict_safety:
            raise ValueError("O benchmark Lua exige replanejamento desligado e segurança estrita.")
        if any(event.wind.speed_mps > 1e-12 for event in scenario.wind.events) or scenario.wind.maximum_drift_m:
            raise ValueError("O benchmark Lua exige vento e desvio artificial iguais a zero.")
        if not initial_path or not targets or initial_path[0] != initial_path[-1]:
            raise ValueError("O benchmark exige rota não vazia, fechada e alvos explícitos.")
        if terrain.ndim != 2 or not terrain.size or not np.all(np.isfinite(terrain)):
            raise ValueError("Terreno inválido ou não finito.")
        for value in (scenario.simulation.scale, scenario.simulation.speed_mps,
                      scenario.simulation.tolerance_m, scenario.simulation.minimum_clearance_m,
                      scenario.simulation.waypoint_timeout_s, scenario.simulation.global_timeout_s):
            if not isfinite(value) or value <= 0:
                raise ValueError("Parâmetros da missão devem ser finitos e positivos.")
        if not isfinite(scenario.simulation.warmup_s) or scenario.simulation.warmup_s < 0:
            raise ValueError("Estabilização deve ser finita e não negativa.")
        if not isfinite(poll_interval_s) or poll_interval_s < 0:
            raise ValueError("Intervalo de polling inválido.")
        if wall_timeout_s is None:
            wall_timeout_s = max(120., scenario.simulation.global_timeout_s * 3)
        if not isfinite(wall_timeout_s) or wall_timeout_s <= 0:
            raise ValueError("Timeout de relógio deve ser finito e positivo.")
        cell_x, cell_y = scenario.terrain.area_m / terrain.shape[1], scenario.terrain.area_m / terrain.shape[0]
        positions = _route_scene_positions(terrain, initial_path, cell_x, cell_y,
                                            scenario.coverage.clearance_m, scenario.simulation.scale)
        if client_factory is None:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
            client_factory = RemoteAPIClient
        sim = client_factory(host=host, port=port).require("sim")
        if sim.getSimulationState() != sim.simulation_stopped:
            raise RuntimeError("A simulação precisa estar parada antes da missão.")
        if not sim.getBoolParam(sim.boolparam_dynamics_handling_enabled):
            raise RuntimeError("A física do simulador precisa estar habilitada.")
        drone = discover_drone(sim, scenario.simulation.drone)
        target = discover_target(sim, scenario.simulation.target)
        time_step = float(sim.getSimulationTimeStep())
        if not isfinite(time_step) or time_step <= 0:
            raise RuntimeError("Passo do simulador inválido.")
        # Inicialização somente antes de startSimulation: o executor nunca
        # teleporta o corpo nem desabilita a dinâmica durante o voo.
        sim.setObjectPosition(drone, list(positions[0]), sim.handle_world)
        sim.setObjectPosition(target, list(positions[0]), sim.handle_world)
        sim.setObjectOrientation(drone, [0., 0., 0.], sim.handle_world)
        cfg = {"drone": drone, "target": target, "positions": positions,
               "path": initial_path, "targets": targets, "rows": terrain.shape[0],
               "columns": terrain.shape[1], "ground_m": (terrain - np.min(terrain)).flatten().tolist(),
               "cell_x_m": cell_x, "cell_y_m": cell_y, "time_step_s": time_step,
               "obstacle_names": [obstacle.name for obstacle in scenario.obstacles],
               "status_tag": STATUS_TAG, "block_tag": BLOCK_TAG, "chunk_samples": CHUNK_SAMPLES,
               **{key: getattr(scenario.simulation, key) for key in (
                   "scale", "speed_mps", "warmup_s", "tolerance_m", "minimum_clearance_m",
                   "waypoint_timeout_s", "global_timeout_s")}}
        script_text = LUA_EXECUTOR.replace("__CONFIGURATION__", _lua(cfg))
        script = int(sim.createScript(sim.scripttype_simulation, script_text, 0, "lua"))
        sim.setObjectAlias(script, "CoverageBenchmarkExecutor")
        sim.setObjectParent(script, drone, True)
        sim.setObjectInt32Param(script, sim.scriptintparam_execorder, sim.scriptexecorder_first)
        headless = bool(sim.getBoolParam(sim.boolparam_headless)) if hasattr(sim, "boolparam_headless") else False
        if disable_rendering and not headless:
            previous_display = bool(sim.getBoolParam(sim.boolparam_display_enabled))
            sim.setBoolParam(sim.boolparam_display_enabled, False)
        previous_stepping = _disable_remote_stepping(sim)
        # Mesmo uma exceção durante start pode deixar a simulação avançando.
        started = True
        sim.startSimulation()
        polling_started = monotonic()
        last_status_progress = polling_started
        last_status_steps = -1
        next_block = 0
        last_progress_sim = last_progress_wall = 0.
        stopped_at = None
        while True:
            decoded = _decode(sim.readCustomDataBlock(script, STATUS_TAG))
            if decoded:
                if not isinstance(decoded, dict):
                    raise RuntimeError("Status do executor Lua inválido.")
                status = decoded
                if status.get("steps") != last_status_steps:
                    last_status_progress = monotonic()
                    last_status_steps = status.get("steps")
                available = status.get("next_block")
                if isinstance(available, bool) or not isinstance(available, int) or available < next_block:
                    raise RuntimeError("Sequência de blocos de telemetria inválida.")
                while next_block < available:
                    data = _decode(sim.readCustomDataBlock(script, BLOCK_TAG + f"{next_block:06d}"))
                    _append_telemetry(log, data, time_step, len(initial_path))
                    next_block += 1
                simulated = float(status["simulation_time_s"])
                elapsed = monotonic() - wall_started
                if simulated - last_progress_sim >= 15 or elapsed - last_progress_wall >= 15:
                    print(f"[BENCHMARK t={simulated:.1f}s] {status['waypoints_completed']}/{len(initial_path)} waypoints; {len(log.telemetry)} amostras recebidas; {elapsed:.1f}s de relógio", flush=True)
                    last_progress_sim, last_progress_wall = simulated, elapsed
            state = sim.getSimulationState()
            if state == sim.simulation_stopped:
                # cleanup pode publicar um último bloco entre a leitura e a parada.
                final = _decode(sim.readCustomDataBlock(script, STATUS_TAG))
                if final:
                    status = final
                    while next_block < status["next_block"]:
                        data = _decode(sim.readCustomDataBlock(script, BLOCK_TAG + f"{next_block:06d}"))
                        _append_telemetry(log, data, time_step, len(initial_path))
                        next_block += 1
                break
            if not status and monotonic() - polling_started > 30:
                raise RuntimeError("Executor Lua sem status após 30 segundos; sysCall_init pode não ter executado.")
            if status and not status.get("done") and monotonic() - last_status_progress > 30:
                raise RuntimeError("Executor Lua sem novos passos físicos há 30 segundos.")
            if status.get("done") and stopped_at is None:
                stopped_at = monotonic()
            if stopped_at is not None and monotonic() - stopped_at > 10:
                raise RuntimeError("O simulador não confirmou a parada em 10 segundos.")
            if monotonic() - wall_started > wall_timeout_s:
                raise TimeoutError("Timeout de relógio aguardando executor Lua.")
            sleep(poll_interval_s)
        log.simulation_steps = len(log.telemetry)
        log.waypoints_completed = int(status.get("waypoints_completed", 0))
        log.targets_completed = int(status.get("targets_completed", 0))
        log.collisions = sum(sample.collision for sample in log.telemetry)
        log.clearance_violations = sum(sample.clearance_violation for sample in log.telemetry)
        if not status.get("done"):
            raise RuntimeError("Executor Lua terminou sem confirmar conclusão.")
        if status.get("steps") != len(log.telemetry):
            raise RuntimeError("Contagem de passos e telemetria não coincidem.")
        if status.get("collisions") != log.collisions or status.get("clearance_violations") != log.clearance_violations:
            raise RuntimeError("Contadores de segurança divergem da telemetria.")
        if not status.get("physics_observed"):
            raise RuntimeError("Não houve observação de física dinâmica do drone.")
        log.error = status.get("error") or None
        log.success = bool(status.get("success") and not log.error and
                           log.waypoints_completed == len(initial_path) and
                           log.targets_completed == len(targets) and log.telemetry)
    except Exception as error:
        log.success = False
        log.error = str(error)
    finally:
        if sim is not None:
            if started:
                try:
                    if sim.getSimulationState() != sim.simulation_stopped:
                        sim.stopSimulation()
                        deadline = monotonic() + 10
                        while sim.getSimulationState() != sim.simulation_stopped and monotonic() < deadline:
                            sleep(.05)
                        if sim.getSimulationState() != sim.simulation_stopped:
                            raise RuntimeError("Parada do simulador não confirmada.")
                except Exception as error:
                    log.success = False
                    log.error = (log.error + "; " if log.error else "") + str(error)
            if previous_display is not None:
                try:
                    sim.setBoolParam(sim.boolparam_display_enabled, previous_display)
                except Exception as error:
                    log.success = False
                    log.error = (log.error + "; " if log.error else "") + f"Falha restaurando visualização: {error}"
            if previous_stepping is not None:
                try:
                    # O servidor ZMQ usa `if enabled then`: em Lua o número
                    # 0 é verdadeiro. Enviar 0 habilita stepping e bloqueia o
                    # próximo voo; esta interface exige bool explícito.
                    # Normaliza porque stopSimulation remoto também pode
                    # zerar o contador. Restaura cada nível por bool, nunca int.
                    _disable_remote_stepping(sim)
                    for _ in range(previous_stepping):
                        sim.setStepping(True)
                except Exception as error:
                    log.success = False
                    log.error = (log.error + "; " if log.error else "") + f"Falha restaurando stepping: {error}"
            if script is not None:
                try:
                    sim.removeObjects([script])
                except Exception as error:
                    log.success = False
                    log.error = (log.error + "; " if log.error else "") + f"Falha removendo executor: {error}"
        # Mantém o progresso conhecido mesmo quando a conexão falhou entre
        # blocos; uma falha continua tendo success=False e erro explícito.
        for name, maximum in (("waypoints_completed", len(initial_path)),
                              ("targets_completed", len(targets))):
            count = status.get(name)
            if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= maximum:
                setattr(log, name, count)
        log.simulation_steps = len(log.telemetry)
        log.collisions = sum(sample.collision for sample in log.telemetry)
        log.clearance_violations = sum(sample.clearance_violation for sample in log.telemetry)
        destination = _save_simulation_log(log, scenario, Path(scenario_path))
        effective_path = destination / "effective_configuration.json"
        effective = json.loads(effective_path.read_text(encoding="utf-8"))
        effective["executor"] = {"name": EXECUTOR, "strict_safety": True,
            "headless_collection": headless,
            "physics_required": True, "physics_observed": bool(status.get("physics_observed")),
            "telemetry_capture": "sysCall_sensing_post_physics_every_step",
            "time_reference": "Fim do intervalo físico: getSimulationTime() em sensing + passo de simulação.",
            "chunk_samples": CHUNK_SAMPLES, "rendering_disabled_during_run": disable_rendering,
            "wall_elapsed_s": monotonic() - wall_started,
            "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest() if script_text else None}
        effective_path.write_text(json.dumps(effective, ensure_ascii=False, indent=2), encoding="utf-8")
        if script_text:
            (destination / "executor.lua").write_text(script_text, encoding="utf-8")
    return log
