import csv
import json
from pathlib import Path

import numpy as np
import pytest

from src.comparison_scene import (
    create_comparison_scene, frame_at, load_replay_pair, replay_script,
)


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def recorded_pair(tmp_path):
    source = tmp_path / "pair"
    source.mkdir()
    protocol = {
        "effective_scenario": {
            "terrain": {"area_m": 30.},
            "coverage": {"window": {"row_start": 0, "col_start": 0,
                                      "row_end": 2, "col_end": 2}, "clearance_m": 60.},
            "simulation": {"scale": .01}, "obstacles": [],
        },
        "plans": [{"method": "horizontal_2d", "path": [[0, 0], [0, 2], [0, 0]]},
                  {"method": "climb_orientation", "path": [[0, 0], [2, 0], [0, 0]]}],
    }
    (source / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
    np.savez_compressed(source / "terrain.npz", terrain=np.zeros((3, 3)),
                        obstacle_mask=np.zeros((3, 3), bool))
    comparisons = []
    for index, method in enumerate(("referencia_2d", "proposta_subida_orientacao")):
        run = source / "runs" / method
        run.mkdir(parents=True)
        duration = 4. if index == 0 else 2.
        positions = [[0., -10., 10., 60.], [duration / 2, 0., 10., 60.],
                     [duration, -10., 10., 60.]]
        _write_csv(run / "telemetry.csv", [dict(zip(
            ("simulation_time_s", "drone_x_m", "drone_y_m", "drone_z_m"),
            [p[0] + .05, *p[1:]])) for p in positions])
        (run / "energy").mkdir()
        _write_csv(run / "energy" / "energy_timeseries.csv", [
            {"end_time_s": duration / 2 + .05, "cumulative_estimated_energy_wh": duration / 2},
            {"end_time_s": duration + .05, "cumulative_estimated_energy_wh": duration},
        ])
        comparisons.append({"method": method, "run_directory": str(run),
                            "energy_estimate_available": True,
                            "estimated_energy_wh": duration,
                            "executed_coverage_percent": 100.,
                            "energy_comparison_eligible": index == 0,
                            "mission_completed_safely": True,
                            "executed_coverage_available": True,
                            "coverage_telemetry_gaps": 0,
                            "energy_outside_envelope_intervals": 0,
                            "energy_model": "zeng_level_plus_climb_v1",
                            "energy_model_sha256": "same_parameters",
                            "cultivable_area_m2": 900.})
    _write_csv(source / "comparison.csv", comparisons)
    return source


def test_replay_uses_original_seconds_and_freezes_finished_flight(recorded_pair):
    _, terrain, flights = load_replay_pair(recorded_pair)
    reference, proposed = flights
    assert terrain.shape == (3, 3)
    assert reference.duration_s == pytest.approx(4.)
    assert proposed.duration_s == pytest.approx(2.)
    # No instante t=2, a proposta terminou e a referência está na metade da missão.
    assert frame_at(reference, 2.) == pytest.approx([0., 10., 60., 2.])
    assert frame_at(proposed, 2.) == pytest.approx([-10., 10., 60., 2.])
    assert frame_at(proposed, 4.) == pytest.approx(frame_at(proposed, 2.))
    assert frame_at(reference, -1.)[-1] == 0.
    assert reference.eligible is True
    assert proposed.eligible is False
    with pytest.raises(ValueError, match="finito"):
        frame_at(reference, float("nan"))


def test_replay_rejects_energy_that_does_not_match_flight(recorded_pair):
    path = recorded_pair / "comparison.csv"
    with path.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["estimated_energy_wh"] = 999.
    _write_csv(path, rows)
    with pytest.raises(ValueError, match="Energia final"):
        load_replay_pair(recorded_pair)


def test_missing_energy_stays_unknown_and_missing_method_fails(recorded_pair):
    path = recorded_pair / "comparison.csv"
    with path.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["energy_estimate_available"] = False
    rows[0]["estimated_energy_wh"] = ""
    _write_csv(path, rows)
    _, _, flights = load_replay_pair(recorded_pair)
    assert flights[0].energy_available is False
    code = replay_script(flights, [-2., 2.], .01)
    assert "Energia indisponível" in code
    assert "available=false" in code
    with pytest.raises(ValueError, match="exatamente um voo"):
        load_replay_pair(recorded_pair, proposed_method="ausente")
    with pytest.raises(ValueError, match="distintos"):
        load_replay_pair(recorded_pair, proposed_method="referencia_2d")


@pytest.mark.parametrize("invalid", [
    {"mission_completed_safely": False},
    {"executed_coverage_percent": 98.},
    {"coverage_telemetry_gaps": 1},
    {"energy_outside_envelope_intervals": 1},
    {"energy_model": "other_model"},
    {"cultivable_area_m2": 899.},
])
def test_replay_reaudits_inconsistent_positive_eligibility_flag(recorded_pair, invalid):
    path = recorded_pair / "comparison.csv"
    with path.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    rows[0].update(invalid)
    rows[0]["energy_comparison_eligible"] = True
    rows[1]["energy_comparison_eligible"] = True
    _write_csv(path, rows)
    _, _, flights = load_replay_pair(recorded_pair)
    assert flights[0].eligible is False
    assert flights[0].exclusion_reasons
    code = replay_script(flights, [-2., 2.], .01)
    assert "eligible=false" in code


def test_dry_run_protocol_never_enables_replay_reduction(recorded_pair):
    protocol_path = recorded_pair / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["dry_run"] = True
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    _, _, flights = load_replay_pair(recorded_pair)
    assert all(not flight.eligible for flight in flights)
    assert all("protocolo_sem_execucao" in flight.exclusion_reasons for flight in flights)


def test_embedded_script_is_self_contained_and_preserves_data(recorded_pair):
    _, _, flights = load_replay_pair(recorded_pair)
    before = [flight.samples.copy() for flight in flights]
    code = replay_script(flights, [-2., 2.], .01, rate=3., loop=True)
    assert "local rate = 3" in code
    assert "local loop = true" in code
    assert "sim.pauseSimulation()" in code
    assert "t>=frames[#frames][1] then return frames[#frames]" in code
    assert "0,-2.1,0.1,0.6,0" in code
    assert "0,1.9,0.1,0.6,0" in code
    assert "Energia estimada" in code or "Energia estimada" in code.capitalize()
    assert "sim.createScript" not in code
    assert "sim.addDrawingObject(sim.drawing_lines,3,0,sim.handle_world," in code
    assert "terrainHandles" not in code
    for original, flight in zip(before, flights):
        np.testing.assert_array_equal(original, flight.samples)
    with pytest.raises(ValueError, match="positiva"):
        replay_script(flights, [-2., 2.], .01, rate=0.)


class FakeSim:
    simulation_stopped = 0
    handle_world = -1
    stringparam_application_path = 1
    colorcomponent_ambient_diffuse = 2
    shapeintparam_static = 3
    primitiveshape_cuboid = 4
    primitiveshape_cylinder = 5
    scripttype_customization = 6
    boolparam_infotext_visible = 7
    arrayparam_background_color1 = 8
    arrayparam_background_color2 = 9
    arrayparam_ambient_light = 10
    boolparam_realtime_simulation = 11
    boolparam_headless = 12
    handle_scene = 13
    sceneobject_shape = 14
    handle_all = 15
    sceneobject_camera = 16
    sceneobject_light = 17

    def __init__(self, headless=False):
        self.counter = 100
        self.saved = []
        self.loaded = []
        self.positions = []
        self.aliases = []
        self.code = None
        self.bool_params = {self.boolparam_headless: headless}
        self.saved_bool_params = []
        self.removed_shapes = []

    def getSimulationState(self):
        return 0

    def saveScene(self, path):
        self.saved.append(path)
        self.saved_bool_params.append(self.bool_params.copy())

    def setBoolParam(self, key, value):
        self.bool_params[key] = value

    def getBoolParam(self, key):
        return self.bool_params[key]

    def loadScene(self, path):
        self.loaded.append(path)

    def getObjectsInTree(self, tree, object_type, options):
        assert (tree, object_type, options) == (self.handle_scene, self.handle_all, 0)
        return [20, 21]  # Piso e caixa decorativa presentes na cena padrão.

    def getObjectParent(self, handle):
        return self.handle_world

    def getObjectAlias(self, handle, options):
        return "OldReplay"

    def getObjectType(self, handle):
        return self.sceneobject_shape

    def removeObjects(self, handles):
        self.removed_shapes.extend(handles)

    def getStringParam(self, _key):
        return "C:/sim"

    def getObject(self, path):
        if path == "/Floor":
            raise RuntimeError("not found")
        return 12

    def createShape(self, *args):
        self.counter += 1
        return self.counter

    createDummy = createShape
    createPrimitiveShape = createShape

    def createScript(self, _kind, code, _options, language):
        self.code = code
        assert language == "lua"
        return 150

    def setObjectAlias(self, handle, alias):
        self.aliases.append(alias)

    def setObjectPosition(self, handle, position, relative):
        self.positions.append((handle, list(position), relative))

    def setShapeColor(self, *args):
        pass

    setObjectInt32Param = setShapeColor
    setObjectSpecialProperty = setShapeColor
    setObjectParent = setShapeColor
    setObjectSelection = setShapeColor
    setArrayParam = setShapeColor
    setObjectMatrix = setShapeColor
    adjustView = setShapeColor


@pytest.mark.parametrize("realtime", [False, True])
@pytest.mark.parametrize("headless", [False, True])
def test_creates_two_visual_copies_and_backs_up_original_scene(recorded_pair, tmp_path, realtime, headless):
    sim = FakeSim(headless)
    class Client:
        def require(self, name):
            assert name == "sim"
            return sim
    output = tmp_path / "replay"
    scene = create_comparison_scene(recorded_pair, output,
                                     realtime=realtime,
                                     client_factory=lambda **kwargs: Client())
    assert scene.name == "comparacao_lado_a_lado.ttt"
    assert Path(sim.saved[0]).name == "scene_before.ttt"
    assert sim.saved[-1] == scene.as_posix()
    assert sim.saved_bool_params[-1][sim.boolparam_realtime_simulation] is realtime
    assert sim.loaded == [""]
    assert sim.removed_shapes == [20, 21]
    assert (sim.boolparam_infotext_visible in sim.bool_params) is not headless
    assert "ReplayDrone0" in sim.aliases and "ReplayDrone1" in sim.aliases
    assert "ReplayTerrain0" in sim.aliases and "ReplayTerrain1" in sim.aliases
    manifest = json.loads((output / "replay_manifest.json").read_text(encoding="utf-8"))
    assert manifest["flights"][0]["visual_offset_scene_units"] > 0
    assert manifest["flights"][1]["visual_offset_scene_units"] < 0
    assert manifest["flights"][0]["duration_s"] == pytest.approx(4.)
    assert manifest["realtime"] is realtime
    assert manifest["flights"][1]["duration_s"] == pytest.approx(2.)
    assert manifest["flights"][1]["comparison_eligible"] is False
    assert len(manifest["flights"][0]["telemetry_sha256"]) == 64
    assert (output / "replay.lua").read_text(encoding="utf-8") == sim.code
    with pytest.raises(FileExistsError):
        create_comparison_scene(recorded_pair, output,
                                client_factory=lambda **kwargs: pytest.fail("Não deve conectar"))
