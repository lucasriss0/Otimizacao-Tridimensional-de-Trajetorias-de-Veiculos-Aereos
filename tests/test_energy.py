import csv
import json
from dataclasses import replace
from math import pi, sqrt
from pathlib import Path

import pytest

from src.energy import EnergyModel, analyze_telemetry, estimate_energy, load_energy_model


def point(t, x=0, z=0):
    return {"simulation_time_s": t, "drone_x_m": x, "drone_y_m": 0, "drone_z_m": z}


def test_hover_uses_published_components_and_integrates_real_duration():
    model = load_energy_model(Path("configs/energy_reference.json"))
    area = pi * .5 ** 2
    p0 = .012 / 8 * 1.225 * .05 * area * 200 ** 3
    pi_hover = 1.1 * 100 ** 1.5 / sqrt(2 * 1.225 * area)
    expected_power = (p0 + pi_hover) / .8
    summary, series = estimate_energy([point(5), point(15), point(65)], model)
    assert model.horizontal_power_w(0) == pytest.approx(p0 + pi_hover)
    assert summary["estimated_energy_wh"] == pytest.approx(expected_power / 60)
    assert summary["energy_observed_duration_s"] == 60
    assert series[-1]["cumulative_estimated_energy_wh"] == summary["estimated_energy_wh"]


def test_forward_power_matches_equation_6_independently():
    model = EnergyModel()
    speed = 8.
    area = pi * model.rotor_radius_m ** 2
    v0 = sqrt(model.weight_n / (2 * model.air_density_kg_m3 * area))
    p0 = .012 / 8 * 1.225 * .05 * area * 200 ** 3
    induced = 1.1 * 100 ** 1.5 / sqrt(2 * 1.225 * area)
    expected = (p0 * (1 + 3 * speed ** 2 / 200 ** 2)
                + induced * sqrt(sqrt(1 + speed ** 4 / (4 * v0 ** 4)) - speed ** 2 / (2 * v0 ** 2))
                + .5 * .3 * 1.225 * .05 * area * speed ** 3)
    assert model.horizontal_power_w(speed) == pytest.approx(expected)


def test_climb_addition_is_weight_times_positive_height_without_descent_credit():
    model = EnergyModel()
    summary, _ = estimate_energy([point(0), point(10, z=10), point(20)], model)
    expected_climb_j = 100 * 10 / .8
    assert summary["estimated_climb_energy_wh"] == pytest.approx(expected_climb_j / 3600)
    assert summary["estimated_energy_wh"] == pytest.approx(
        model.horizontal_power_w(0) / .8 * 20 / 3600 + expected_climb_j / 3600
    )


def test_constant_speed_is_invariant_to_sampling_and_auxiliary_energy_is_separate():
    model = replace(EnergyModel(), auxiliary_power_w=20)
    first, _ = estimate_energy([point(0), point(10, 80)], model)
    second, _ = estimate_energy([point(0), point(2, 16), point(10, 80)], model)
    assert first["estimated_energy_wh"] == pytest.approx(second["estimated_energy_wh"])
    assert first["estimated_auxiliary_energy_wh"] == pytest.approx(200 / 3600)


def test_unobserved_energy_is_unavailable_and_speed_envelope_is_visible():
    for rows in ([], [point(0)]):
        summary, _ = estimate_energy(rows, EnergyModel())
        assert not summary["energy_estimate_available"]
        assert summary["estimated_energy_wh"] is None
    summary, _ = estimate_energy([point(0), point(1, 100, 10)], EnergyModel())
    assert summary["energy_outside_envelope_intervals"] == 1


@pytest.mark.parametrize("rows", [
    [point(1), point(1)], [point(2), point(1)], [point(0), point(float("nan"))],
    [point(0), point(1, float("inf"))],
])
def test_invalid_measurements_are_rejected(rows):
    with pytest.raises(ValueError):
        estimate_energy(rows, EnergyModel())


@pytest.mark.parametrize("params", [
    {"electrical_efficiency": 0}, {"climb_efficiency": 1.1}, {"weight_n": -1},
    {"tip_speed_mps": float("nan")}, {"rotor_solidity": 2},
])
def test_invalid_model_is_rejected(params):
    with pytest.raises(ValueError):
        EnergyModel(**params)


def test_standalone_export_preserves_parameters_and_source_csv(tmp_path):
    source = tmp_path / "telemetry.csv"
    source.write_text("simulation_time_s,drone_x_m,drone_y_m,drone_z_m\n0,0,0,0\n1,0,0,0\n", encoding="utf-8")
    before = source.read_bytes()
    output = tmp_path / "energy"
    summary = analyze_telemetry(source, EnergyModel(), output)
    manifest = json.loads((output / "energy_model.json").read_text(encoding="utf-8"))
    assert not manifest["calibrated_for_project_drone"]
    assert manifest["parameters"]["weight_n"] == 100
    assert summary["estimated_energy_wh"] > 0
    assert (output / "energy_timeseries.csv").is_file()
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        analyze_telemetry(source, EnergyModel(), output)
