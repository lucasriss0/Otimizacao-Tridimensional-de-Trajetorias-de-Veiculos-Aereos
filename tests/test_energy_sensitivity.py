import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.energy_sensitivity import analyze_energy_sensitivity, sensitivity_configurations


def _benchmark(tmp_path, durations=(("a", 1, 20., 10.),), **report_changes):
    """Dados sintéticos exclusivamente para verificar a ferramenta, sem voos reais."""
    folder = tmp_path / "benchmark"
    folder.mkdir()
    pairs = []
    for case, repetition, reference_time, proposed_time in durations:
        pair = {"geographic_case": case, "repetition": repetition, "comparable": True}
        for side, duration in (("reference", reference_time), ("proposed", proposed_time)):
            run = folder / f"{case}_{repetition}_{side}"
            run.mkdir()
            with (run / "telemetry.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(["simulation_time_s", "drone_x_m", "drone_y_m", "drone_z_m"])
                writer.writerow([0., 0., 0., 60.])
                writer.writerow([duration, 0., 0., 60.])
            pair[side] = {"method": side, "mission_completed_safely": True,
                          "executed_coverage_percent": 100., "cultivable_area_m2": 1000.,
                          # Este valor deliberadamente falso não deve ser usado na sensibilidade.
                          "estimated_energy_wh": 999., "run_directory": str(run)}
        pairs.append(pair)
    report = {"evidence_kind": "simulator_trajectory_with_estimated_energy",
              "reference_method": "reference", "proposed_method": "proposed",
              "benchmark_definition": {"minimum_executed_coverage_percent": 100.},
              "pairs": pairs, **report_changes}
    source = folder / "benchmark.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    return source, report


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_fixed_grid_contains_eighteen_theoretical_models_without_calibration():
    configurations = sensitivity_configurations()
    assert len(configurations) == 18
    parameters = [item["model"]["parameters"] for item in configurations]
    assert {item["weight_n"] for item in parameters} == {80., 100., 120.}
    assert {round(item["electrical_efficiency"], 2) for item in parameters} == {.64, .8, .96}
    assert {item["auxiliary_power_w"] for item in parameters} == {0., 100.}
    assert len({(p["weight_n"], p["electrical_efficiency"], p["auxiliary_power_w"]) for p in parameters}) == 18
    assert all(p["climb_efficiency"] == .8 for p in parameters)
    assert all(0 < p["electrical_efficiency"] <= 1 for p in parameters)
    assert all(c["model"]["calibration"] is None for c in configurations)
    assert all(c["model"]["calibrated_for_project_drone"] is False for c in configurations)


def test_recomputes_same_telemetry_preserves_hashes_and_uses_equal_case_weight(tmp_path):
    source, report = _benchmark(tmp_path, durations=(
        ("a", 1, 20., 10.), ("a", 2, 20., 10.), ("b", 1, 20., 22.)))
    original = {source: source.read_bytes()}
    for pair in report["pairs"]:
        for side in ("reference", "proposed"):
            path = Path(pair[side]["run_directory"]) / "telemetry.csv"
            original[path] = path.read_bytes()
    output = analyze_energy_sensitivity(source.parent, tmp_path / "sensitivity")
    summary = _read(output / "sensitivity_summary.json")
    assert summary["configuration_count"] == 18
    assert summary["analyzed_pairs"] == 3
    assert summary["geographic_cases_analyzed"] == 2
    # A=50%, B=-10%: mesmo peso para cada recorte resulta em20%, não30%.
    assert summary["minimum_case_mean_estimated_energy_reduction_percent"] == pytest.approx(20.)
    assert summary["maximum_case_mean_estimated_energy_reduction_percent"] == pytest.approx(20.)
    assert summary["configurations_with_estimated_saving"] == 18
    assert summary["all_configurations_show_estimated_saving_for_analyzed_pairs"] is True
    assert summary["real_battery_saving_proven"] is False
    assert summary["benchmark_sha256"] == hashlib.sha256(original[source]).hexdigest()
    assert len(summary["telemetry_sources"]) == 6
    assert all(len(item["sha256"]) == 64 for item in summary["telemetry_sources"])
    with (output / "pair_sensitivity.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 18 * 3
    assert all(float(row["estimated_energy_reduction_percent"]) == pytest.approx(-10.)
               for row in rows if row["geographic_case"] == "b")
    assert all(float(row["reference_estimated_energy_wh"]) != 999. for row in rows)
    assert (output / "energy_sensitivity.png").is_file()
    assert (output / "energy_sensitivity.svg").is_file()
    assert all(path.read_bytes() == content for path, content in original.items())
    with pytest.raises(FileExistsError):
        analyze_energy_sensitivity(source, output)


@pytest.mark.parametrize("outside_x, outside_z", [(61., 60.), (0., 66.)])
def test_ineligible_missing_or_outside_envelope_pairs_do_not_enter_means(tmp_path, outside_x, outside_z):
    source, report = _benchmark(tmp_path, durations=(
        ("ineligible", 1, 20., 1.), ("missing", 1, 20., 1.),
        ("outside", 1, 20., 1.), ("invalid", 1, 20., 1.)))
    report["pairs"][0]["comparable"] = False
    report["pairs"][1]["proposed"]["run_directory"] = str(tmp_path / "not_existing")
    outside = Path(report["pairs"][2]["proposed"]["run_directory"]) / "telemetry.csv"
    outside.write_text("simulation_time_s,drone_x_m,drone_y_m,drone_z_m\n"
                       f"0,0,0,60\n1,{outside_x},0,{outside_z}\n", encoding="utf-8")
    invalid = Path(report["pairs"][3]["proposed"]["run_directory"]) / "telemetry.csv"
    invalid.write_text("simulation_time_s,drone_x_m,drone_y_m,drone_z_m\n1,0,0,60\n1,0,0,60\n", encoding="utf-8")
    _save(source, report)
    output = analyze_energy_sensitivity(source, tmp_path / "sensitivity")
    summary = _read(output / "sensitivity_summary.json")
    assert summary["source_reported_pairs"] == 4
    assert summary["source_comparable_pairs"] == 3
    assert summary["analyzed_pairs"] == 0
    assert len(summary["excluded_pairs"]) == 4
    assert any("fora do envelope" in item.get("error", "") for item in summary["excluded_pairs"])
    assert summary["configurations_with_estimated_saving"] == 0
    assert summary["configurations_without_result"] == 18
    assert summary["minimum_case_mean_estimated_energy_reduction_percent"] is None
    assert not summary["all_configurations_show_estimated_saving_for_analyzed_pairs"]
    with (output / "pair_sensitivity.csv").open(encoding="utf-8-sig") as stream:
        assert list(csv.DictReader(stream)) == []


@pytest.mark.parametrize("proposed_duration, positive, negative, tied", [
    (22., 0, 18, 0), (20., 0, 0, 18),
])
def test_increases_and_ties_remain_in_summary(tmp_path, proposed_duration, positive, negative, tied):
    source, _ = _benchmark(tmp_path, durations=(("a", 1, 20., proposed_duration),))
    output = analyze_energy_sensitivity(source, tmp_path / "sensitivity")
    summary = _read(output / "sensitivity_summary.json")
    assert summary["configurations_with_estimated_saving"] == positive
    assert summary["configurations_with_estimated_increase"] == negative
    assert summary["configurations_with_tie"] == tied


def test_fitted_source_is_not_treated_as_valid_calibration_of_theoretical_grid(tmp_path):
    source, report = _benchmark(tmp_path, energy_model={
        "calibration": {"held_out_criterion_passed": True, "data_kind": "measured"},
        "parameters": {"weight_n": 200., "electrical_efficiency": .7}})
    report["pairs"][0]["reference"]["energy_parameter_fit_available"] = True
    _save(source, report)
    output = analyze_energy_sensitivity(source, tmp_path / "sensitivity")
    summary = _read(output / "sensitivity_summary.json")
    configuration = _read(output / "sensitivity_configuration.json")
    assert summary["source_parameter_fit_detected"] is True
    assert summary["energy_calibrated"] is False
    assert summary["real_battery_saving_proven"] is False
    assert configuration["base_model"]["parameters"]["weight_n"] == 100.
    assert all(c["model"]["calibration"] is None for c in configuration["configurations"])
    assert "não comprova economia real de bateria" in configuration["warning"]


def test_rejects_ideal_benchmark_and_favorable_duplicate(tmp_path):
    source, report = _benchmark(tmp_path)
    report["evidence_kind"] = "ideal_constant_3d_speed"
    _save(source, report)
    with pytest.raises(ValueError, match="executadas no simulador"):
        analyze_energy_sensitivity(source, tmp_path / "ideal")
    report["evidence_kind"] = "simulator_trajectory_with_estimated_energy"
    report["pairs"].append(report["pairs"][0])
    _save(source, report)
    with pytest.raises(ValueError, match="duplicado"):
        analyze_energy_sensitivity(source, tmp_path / "duplicate")


def test_changed_telemetry_cannot_reuse_a_recorded_benchmark_hash(tmp_path):
    source, report = _benchmark(tmp_path)
    report["pairs"][0]["reference"]["telemetry_sha256"] = "0" * 64
    _save(source, report)
    output = analyze_energy_sensitivity(source, tmp_path / "sensitivity")
    summary = _read(output / "sensitivity_summary.json")
    assert summary["analyzed_pairs"] == 0
    assert "Hash da telemetria" in summary["excluded_pairs"][0]["error"]
