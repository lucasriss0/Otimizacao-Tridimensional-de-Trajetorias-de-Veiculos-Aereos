import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.energy import EnergyModel, estimate_energy, load_energy_model, model_manifest
from src.energy_calibration import FIELDS, calibrate_energy, fit_parameters, read_measurements


def measurements(model=None):
    model = model or replace(EnergyModel(), electrical_efficiency=.7,
                              climb_efficiency=.65, auxiliary_power_w=30.)
    rows = []
    for split, maneuvers in (
        ("train", [(0, 0), (5, 0), (10, 0), (0, 1), (5, 2), (10, 1)]),
        ("validation", [(0, 0), (3, 0), (8, 1), (5, 1.5)]),
    ):
        for index, (horizontal, vertical) in enumerate(maneuvers):
            power = (model.horizontal_power_w(horizontal) / model.electrical_efficiency
                     + model.weight_n * vertical / model.climb_efficiency + model.auxiliary_power_w)
            rows.append(dict(flight_id=f"{split}_flight", split=split, duration_s=10 + index,
                             horizontal_speed_mps=horizontal, vertical_speed_mps=vertical,
                             voltage_v=24., current_a=power / 24))
    return rows


def save_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_recovers_known_parameters_and_preserves_explicit_synthetic_origin(tmp_path):
    source = save_csv(tmp_path / "synthetic.csv", measurements())
    output = tmp_path / "fit"
    report = calibrate_energy(source, Path("configs/energy_reference.json"), output,
                              "synthetic_reference", "synthetic")
    candidate = load_energy_model(output / "candidate_model.json")
    assert candidate.electrical_efficiency == pytest.approx(.7)
    assert candidate.climb_efficiency == pytest.approx(.65)
    assert candidate.auxiliary_power_w == pytest.approx(30.)
    assert report["validation"]["duration_weighted_mape_percent"] < 1e-8
    assert report["calibration"]["held_out_criterion_passed"]
    assert not report["calibration"]["real_measurements_declared"]
    manifest = model_manifest(candidate)
    assert manifest["parameter_fit_available"]
    assert not manifest["calibrated_for_project_drone"]
    assert manifest["calibration"]["vehicle_id"] == "synthetic_reference"
    assert (output / "measurements.csv").read_bytes() == source.read_bytes()
    assert (output / "flight_validation.csv").is_file()
    summary, _ = estimate_energy([
        dict(simulation_time_s=t, drone_x_m=0, drone_y_m=0, drone_z_m=60)
        for t in (0, 1)], candidate)
    assert summary["energy_parameter_fit_available"]
    assert not summary["energy_calibrated"]
    outside, _ = estimate_energy([
        dict(simulation_time_s=t, drone_x_m=t * 15, drone_y_m=0, drone_z_m=60)
        for t in (0, 1)], candidate)
    assert outside["energy_outside_calibration_envelope_intervals"] == 1
    assert outside["energy_outside_envelope_intervals"] == 1
    with pytest.raises(FileExistsError):
        calibrate_energy(source, Path("configs/energy_reference.json"), output, "test", "synthetic")


def test_validation_cannot_influence_fit_and_failed_candidate_cannot_be_loaded(tmp_path):
    source = save_csv(tmp_path / "data.csv", measurements())
    initial = tmp_path / "initial"
    calibrate_energy(source, Path("configs/energy_reference.json"), initial, "test", "synthetic")
    altered = measurements()
    for row in altered:
        if row["split"] == "validation":
            row["current_a"] *= 3
    source = save_csv(tmp_path / "changed.csv", altered)
    output = tmp_path / "changed"
    report = calibrate_energy(source, Path("configs/energy_reference.json"), output, "test", "synthetic")
    assert not report["calibration"]["held_out_criterion_passed"]
    a = json.loads((initial / "candidate_model.json").read_text(encoding="utf-8"))
    b = json.loads((output / "candidate_model.json").read_text(encoding="utf-8"))
    assert a["parameters"] == b["parameters"]
    with pytest.raises(ValueError, match="validação"):
        load_energy_model(output / "candidate_model.json")


def test_rejects_leakage_missing_holdout_bad_units_and_insufficient_maneuvers(tmp_path):
    for index, mutate in enumerate((
        lambda rows: [dict(r, flight_id="same") for r in rows],
        lambda rows: [r for r in rows if r["split"] == "train"],
        lambda rows: [dict(r, voltage_v=-24) for r in rows],
        lambda rows: [dict(r, duration_s=float("nan")) for r in rows],
        lambda rows: [dict(r, horizontal_speed_mps=100) for r in rows],
        lambda rows: [dict(r, vertical_speed_mps=-1) for r in rows],
    )):
        path = save_csv(tmp_path / f"bad_{index}.csv", mutate(measurements()))
        with pytest.raises(ValueError):
            read_measurements(path, EnergyModel())
    path = save_csv(tmp_path / "hover_only.csv", [dict(r, horizontal_speed_mps=0,
                     vertical_speed_mps=0) for r in measurements()])
    rows = read_measurements(path, EnergyModel())
    with pytest.raises(ValueError):
        fit_parameters([r for r in rows if r["split"] == "train"], EnergyModel())


def test_lower_bounds_prevent_efficiencies_above_one_or_negative_auxiliary_power(tmp_path):
    rows = measurements(replace(EnergyModel(), electrical_efficiency=1.,
                               climb_efficiency=1., auxiliary_power_w=0.))
    for row in rows:
        row["current_a"] *= .5
    source = save_csv(tmp_path / "bounds.csv", rows)
    parsed = read_measurements(source, EnergyModel())
    fitted, _ = fit_parameters([r for r in parsed if r["split"] == "train"], EnergyModel())
    assert 0 < fitted.electrical_efficiency <= 1
    assert 0 < fitted.climb_efficiency <= 1
    assert fitted.auxiliary_power_w >= 0


def test_extrapolated_validation_is_reported_not_silently_approved(tmp_path):
    rows = measurements()
    for row in rows:
        if row["split"] == "validation":
            row["horizontal_speed_mps"] = 20
    source = save_csv(tmp_path / "extrapolation.csv", rows)
    report = calibrate_energy(source, Path("configs/energy_reference.json"), tmp_path / "fit",
                              "test", "synthetic", maximum_validation_mape=1000)
    assert report["calibration"]["validation_outside_training_envelope_rows"] > 0
    assert not report["calibration"]["held_out_criterion_passed"]
