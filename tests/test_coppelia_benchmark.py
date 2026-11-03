from dataclasses import replace
import json
from pathlib import Path

import cbor2
import numpy as np
import pytest

import src.coppelia_benchmark as benchmark
from src.coppelia_benchmark import (
    BLOCK_TAG, CHUNK_SAMPLES, EXECUTOR, LUA_EXECUTOR, STATUS_TAG,
    _append_telemetry, run_coverage_mission,
)
from src.coppeliasim import SimulationLog
from src.scenario import load_scenario


class CompletedLuaSim:
    simulation_stopped = 0
    handle_world = -1
    boolparam_dynamics_handling_enabled = 1
    boolparam_display_enabled = 2
    scripttype_simulation = 3
    scriptintparam_execorder = 4
    scriptexecorder_first = 5

    def __init__(self):
        self.started = False
        self.positions = []
        self.display = True
        self.removed = []
        self.source = ""
        self.stepping_calls = []
        self.status = {"done": True, "success": True, "error": "", "steps": 3,
                       "waypoints_completed": 3, "targets_completed": 3,
                       "collisions": 0, "clearance_violations": 0, "next_block": 1,
                       "simulation_time_s": .15, "physics_observed": True}
        self.rows = [[t, 0, index, index, 0, 0, 60, 0, 0, 60, 0,
                      "sem_vento", 0, 0, 60, False, False, index > 0]
                     for index, t in enumerate((.05, .1, .15))]
        self.missing = False

    def getSimulationState(self):
        return self.simulation_stopped

    def getBoolParam(self, parameter):
        return self.display if parameter == self.boolparam_display_enabled else True

    def setBoolParam(self, parameter, value):
        assert parameter == self.boolparam_display_enabled
        self.display = value

    def getObject(self, path):
        return {"/Drone": 10, "/DroneTarget": 11}[path]

    def getSimulationTimeStep(self):
        return .05

    def setObjectPosition(self, handle, position, world):
        assert not self.started, "O corpo só pode ser posicionado antes da física."
        self.positions.append((handle, position, world))

    def setObjectOrientation(self, handle, angles, world):
        assert not self.started

    def createScript(self, kind, source, options, language):
        assert language == "lua" and options == 0
        self.source = source
        return 99

    def setObjectAlias(self, handle, alias):
        assert handle == 99

    def setObjectParent(self, handle, parent, preserve):
        assert (handle, parent, preserve) == (99, 10, True)

    def setObjectInt32Param(self, handle, parameter, priority):
        assert (handle, parameter, priority) == (99, self.scriptintparam_execorder, self.scriptexecorder_first)

    def setStepping(self, level):
        assert isinstance(level, bool), "O wrapper ZMQ interpreta zero numérico como verdadeiro em Lua."
        self.stepping_calls.append(level)
        return 0

    def startSimulation(self):
        self.started = True

    def readCustomDataBlock(self, script, tag):
        assert script == 99
        if tag == STATUS_TAG:
            return cbor2.dumps(self.status)
        assert tag == BLOCK_TAG + "000000"
        return None if self.missing else cbor2.dumps(self.rows)

    def removeObjects(self, handles):
        self.removed.extend(handles)


def _run(tmp_path, sim, **kwargs):
    scenario = load_scenario(Path("configs/demo_coverage.yaml"))
    scenario = replace(scenario, output_root=tmp_path / "runs",
                       simulation=replace(scenario.simulation, target="/DroneTarget"))
    client = type("Client", (), {"require": lambda self, name: sim})()
    route = [(0, 0), (0, 1), (0, 0)]
    return run_coverage_mission(scenario, np.zeros((3, 3)), route, route,
                                Path("configs/demo_coverage.yaml"),
                                client_factory=lambda **kw: client, poll_interval_s=0, **kwargs)


def test_batched_executor_preserves_log_format_initializes_only_before_physics_and_restores_display(tmp_path):
    sim = CompletedLuaSim()
    log = _run(tmp_path, sim, disable_rendering=True)
    assert log.success and log.error is None
    assert log.waypoints_completed == log.targets_completed == log.simulation_steps == 3
    assert not log.replanning_enabled
    assert [sample.application_active for sample in log.telemetry] == [False, True, True]
    assert sim.display is True
    assert sim.stepping_calls == [False, False]
    assert all(value is False for value in sim.stepping_calls)
    assert sim.removed == [99]
    assert [handle for handle, _, _ in sim.positions] == [10, 11]
    assert (log.output_directory / "telemetry.csv").is_file()
    effective = json.loads((log.output_directory / "effective_configuration.json").read_text(encoding="utf-8"))
    assert effective["executor"]["name"] == EXECUTOR
    assert effective["executor"]["physics_observed"] is True
    assert effective["executor"]["chunk_samples"] == CHUNK_SAMPLES
    assert (log.output_directory / "executor.lua").read_text(encoding="utf-8") == sim.source


@pytest.mark.parametrize("change,expected", [
    ({"steps": 4}, "Contagem de passos"),
    ({"physics_observed": False}, "física dinâmica"),
    ({"collisions": 1}, "Contadores de segurança"),
    ({"done": False}, "sem confirmar conclusão"),
])
def test_unconfirmed_or_inconsistent_physical_measurements_invalidate_the_run(tmp_path, change, expected):
    sim = CompletedLuaSim()
    sim.status.update(change)
    log = _run(tmp_path, sim, disable_rendering=True)
    assert not log.success
    assert expected in log.error
    assert sim.display is True and sim.removed == [99]


def test_headless_collection_keeps_physics_without_using_window_parameters(tmp_path):
    class HeadlessSim(CompletedLuaSim):
        boolparam_headless = 90

        def getBoolParam(self, parameter):
            assert parameter != self.boolparam_display_enabled
            return True

        def setBoolParam(self, parameter, value):
            pytest.fail("Não alterar exibição de janela inexistente.")

    log = _run(tmp_path, HeadlessSim(), disable_rendering=True)
    assert log.success and log.error is None
    effective = json.loads((log.output_directory / "effective_configuration.json").read_text(encoding="utf-8"))
    assert effective["executor"]["headless_collection"] is True
    assert effective["executor"]["physics_observed"] is True


def test_missing_block_cannot_be_interpreted_as_no_collision_or_completed_mission(tmp_path):
    sim = CompletedLuaSim()
    sim.missing = True
    log = _run(tmp_path, sim)
    assert not log.success and "Bloco de telemetria" in log.error
    assert not log.telemetry


@pytest.mark.parametrize("options", [{"strict_safety": False}, {"replanning_enabled": True}])
def test_benchmark_rejects_disabling_strict_safety_or_requesting_replanning_without_connecting(tmp_path, options):
    sim = CompletedLuaSim()
    log = _run(tmp_path, sim, **options)
    assert not log.success and "segurança estrita" in log.error
    assert not sim.started


def test_telemetry_decoder_rejects_missing_steps_nan_and_invalid_flags():
    row = CompletedLuaSim().rows[0]
    for field, value in ((0, float("nan")), (10, -1), (15, "unknown")):
        log = SimulationLog(False, "test", 0, 0, 0, 0, [], [], [])
        modified = row.copy()
        modified[field] = value
        with pytest.raises((RuntimeError, ValueError)):
            _append_telemetry(log, [modified], .05, 3)
    log = SimulationLog(False, "test", 0, 0, 0, 0, [], [], [])
    _append_telemetry(log, [row.copy()], .05, 3)
    missing = row.copy()
    missing[0] = .15
    with pytest.raises(RuntimeError, match="passos físicos ausentes"):
        _append_telemetry(log, [missing], .05, 3)


def test_lua_source_checks_all_shapes_after_physics_and_never_sets_the_drone_pose():
    # A prova de execução vem do piloto real. Aqui protegemos o contrato de
    # segurança contra uma regressão que troque física por reprodução de pose.
    assert "function sysCall_sensing()" in LUA_EXECUTOR
    assert "sim.createCollection(1)" in LUA_EXECUTOR
    assert "getObjectsInTree(cfg.drone,sim.sceneobject_shape,0)" in LUA_EXECUTOR
    assert "getObjectsInTree(model,sim.sceneobject_shape,0)" in LUA_EXECUTOR
    assert "sim.getObject('/AgriculturalTerrain')" in LUA_EXECUTOR
    assert "sim.checkCollision(droneCollection,handle)" in LUA_EXECUTOR
    assert "sim.setObjectPosition(cfg.target,commanded,sim.handle_world)" in LUA_EXECUTOR
    assert "setObjectPosition(cfg.drone" not in LUA_EXECUTOR
    assert "sim.setBoolParam" not in LUA_EXECUTOR


@pytest.mark.parametrize("publish_status,expected", [
    (False, "sem status após 30 segundos"),
    (True, "sem novos passos físicos há 30 segundos"),
])
def test_missing_or_frozen_script_status_stops_the_owned_simulation(tmp_path, monkeypatch, publish_status, expected):
    from itertools import count
    ticks = count(0, 11)
    monkeypatch.setattr(benchmark, "monotonic", lambda: next(ticks))
    sim = CompletedLuaSim()
    sim.getSimulationState = lambda: 1 if sim.started else sim.simulation_stopped
    sim.stopSimulation = lambda: setattr(sim, "started", False)
    sim.status.update(done=False, steps=0, next_block=0)
    if not publish_status:
        sim.readCustomDataBlock = lambda *args: None
    log = _run(tmp_path, sim, disable_rendering=True)
    assert not log.success and expected in log.error
    assert not sim.started and sim.display is True and sim.removed == [99]


def test_exception_during_start_still_stops_physics_and_restores_the_display(tmp_path):
    sim = CompletedLuaSim()
    sim.getSimulationState = lambda: 1 if sim.started else sim.simulation_stopped
    sim.stopSimulation = lambda: setattr(sim, "started", False)
    def start():
        sim.started = True
        raise RuntimeError("falha ao iniciar")
    sim.startSimulation = start
    log = _run(tmp_path, sim, disable_rendering=True)
    assert not log.success and "falha ao iniciar" in log.error
    assert not sim.started and sim.display is True and sim.removed == [99]


def test_nested_remote_stepping_levels_are_disabled_and_restored_using_only_booleans(tmp_path):
    sim = CompletedLuaSim()
    sim.level = 2
    def stepping(enabled):
        assert isinstance(enabled, bool)
        sim.stepping_calls.append(enabled)
        previous = sim.level
        sim.level = sim.level + 1 if enabled else max(0, sim.level - 1)
        return previous
    sim.setStepping = stepping
    def start():
        assert sim.level == 0, "O executor Lua não pode iniciar ainda preso ao stepping remoto."
        sim.started = True
    sim.startSimulation = start
    log = _run(tmp_path, sim)
    assert log.success and sim.level == 2
    assert sim.stepping_calls == [False, False, False, True, True]
