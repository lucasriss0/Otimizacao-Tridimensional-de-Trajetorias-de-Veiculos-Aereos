import csv
import json

import pytest

from src.benchmark_report import generate_benchmark_report


def _row(method, energy, case="a", repetition=1, **changes):
    return {"geographic_case": case, "repetition": repetition, "method": method,
            "energy_comparison_eligible": True, "mission_completed_safely": True,
            "executed_coverage_available": True, "executed_coverage_percent": 100,
            "minimum_executed_coverage_percent": 100, "coverage_telemetry_gaps": 0,
            "energy_estimate_available": True, "estimated_energy_wh": energy,
            "energy_outside_envelope_intervals": 0, "energy_model": "reference_v1",
            "energy_model_sha256": "a" * 64,
            "energy_calibrated": False, "cultivable_area_m2": 1000,
            "executed_covered_area_m2": 1000, **changes}


def _csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _report(path):
    return json.loads((path / "benchmark.json").read_text(encoding="utf-8"))


def test_report_preserves_missing_failures_negative_results_and_terrain_denominator(tmp_path):
    source = tmp_path / "suite"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"definition": {
        "locations": [{"id": "a"}, {"id": "b"}], "repetitions": 2,
        "minimum_executed_coverage_percent": 100,
    }}), encoding="utf-8")
    rows = []
    for case, repetition, energy in (("a", 1, 90), ("a", 2, 80), ("b", 1, 110)):
        rows += [_row("referencia_2d", 100, case, repetition),
                 _row("proposta_completa", energy, case, repetition)]
    _csv(source / "all_flights.csv", rows)
    attempts = [{"case": "b", "repetition": 2, "status": "failed", "error": "controlador falhou",
                 "output": str(source / "not_created")}]
    (source / "attempts.json").write_text(json.dumps(attempts), encoding="utf-8")
    result = generate_benchmark_report(source, tmp_path / "report")
    report = _report(result)
    summary = report["summary"]
    assert summary["expected_pairs"] == 4
    assert summary["eligible_pairs"] == 3
    assert summary["ineligible_or_missing_pairs"] == 1
    assert summary["positive_pairs"] == 2
    assert summary["negative_pairs"] == 1
    assert summary["mean_estimated_energy_reduction_percent"] == pytest.approx(20 / 3)
    assert summary["case_mean_estimated_energy_reduction_percent"] == pytest.approx(2.5)
    assert summary["geographic_cases_with_eligible_pairs"] == 2
    assert summary["real_battery_saving_proven"] is False
    assert report["real_battery_saving_proven"] is False
    assert report["pairs"][-1]["attempt_status"] == "failed"
    assert report["pairs"][-1]["attempt_error"] == "controlador falhou"
    assert report["pairs"][-1]["estimated_energy_reduction_percent"] is None
    assert not summary["all_pairs_eligible"]
    assert (result / "energy_comparison.png").is_file()
    assert (result / "energy_comparison.svg").is_file()
    assert "não comprova economia real de bateria" in (result / "index.html").read_text(encoding="utf-8")
    with (result / "all_recorded_flights.csv").open(encoding="utf-8-sig") as stream:
        assert len(list(csv.DictReader(stream))) == 6
    with pytest.raises(FileExistsError):
        generate_benchmark_report(source, result)


def test_report_rechecks_eligibility_and_does_not_turn_bad_flight_into_saving(tmp_path):
    source = tmp_path / "comparison.csv"
    rows = []
    changes = ({"mission_completed_safely": False},
               {"executed_coverage_percent": 98},
               {"coverage_telemetry_gaps": 1},
               {"energy_outside_envelope_intervals": 1},
               {"estimated_energy_wh": "nan"},
               {"energy_comparison_eligible": False})
    for index, invalid in enumerate(changes):
        rows.extend([_row("referencia_2d", 100, repetition=index + 1),
                     _row("proposta_completa", 1, repetition=index + 1, **invalid)])
    _csv(source, rows)
    result = generate_benchmark_report(source, tmp_path / "report")
    report = _report(result)
    assert report["summary"]["expected_pairs"] == 6
    assert report["summary"]["eligible_pairs"] == 0
    assert report["summary"]["mean_estimated_energy_reduction_percent"] is None
    assert not report["summary"]["observed_mean_estimated_energy_saving"]
    assert all(pair["estimated_energy_reduction_percent"] is None for pair in report["pairs"])
    assert "Não há pares elegíveis" in (result / "index.html").read_text(encoding="utf-8")


def test_report_recovers_recorded_flight_from_failed_partial_attempt(tmp_path):
    source = tmp_path / "suite"
    source.mkdir()
    partial = source / "partial"
    partial.mkdir()
    _csv(partial / "comparison.csv", [_row("referencia_2d", 100)])
    (source / "attempts.json").write_text(json.dumps([{
        "case": "a", "repetition": 1, "status": "failed", "error": "conexão perdida",
        "output": str(partial),
    }]), encoding="utf-8")
    result = generate_benchmark_report(source, tmp_path / "report")
    report = _report(result)
    assert report["summary"]["recorded_flights_in_target_pairs"] == 1
    assert report["summary"]["expected_pairs"] == 1
    assert report["pairs"][0]["reference"]["estimated_energy_wh"] == 100
    assert report["pairs"][0]["proposed"] is None
    assert report["pairs"][0]["proposed_exclusion_reasons"] == ["voo_ausente"]


def test_report_does_not_choose_favorable_duplicate_or_accept_ideal_path(tmp_path):
    source = tmp_path / "comparison.csv"
    _csv(source, [_row("referencia_2d", 100), _row("referencia_2d", 200),
                 _row("proposta_completa", 50)])
    with pytest.raises(ValueError, match="duplicado"):
        generate_benchmark_report(source, tmp_path / "duplicate")
    _csv(source, [_row("referencia_2d", 100, trajectory_kind="ideal_constant_3d_speed")])
    with pytest.raises(ValueError, match="trajetórias ideais"):
        generate_benchmark_report(source, tmp_path / "ideal")


def test_pair_rejects_different_areas_models_and_dry_run(tmp_path):
    source = tmp_path / "comparison.csv"
    _csv(source, [_row("referencia_2d", 100, repetition=1),
                 _row("proposta_completa", 90, repetition=1, cultivable_area_m2=999),
                 _row("referencia_2d", 100, repetition=2),
                 _row("proposta_completa", 90, repetition=2, energy_model="other")])
    result = generate_benchmark_report(source, tmp_path / "report")
    pairs = _report(result)["pairs"]
    assert pairs[0]["pair_exclusion_reasons"] == ["areas_cultivaveis_diferentes"]
    assert pairs[1]["pair_exclusion_reasons"] == ["modelos_energeticos_diferentes"]
    assert all(pair["estimated_energy_reduction_percent"] is None for pair in pairs)
    (tmp_path / "protocol.json").write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    _csv(source, [_row("referencia_2d", 100), _row("proposta_completa", 90)])
    result = generate_benchmark_report(source, tmp_path / "dry_run")
    assert _report(result)["pairs"][0]["pair_exclusion_reasons"] == ["protocolo_sem_execucao"]


def test_pair_requires_matching_parameter_fingerprints_and_known_positive_area(tmp_path):
    source = tmp_path / "comparison.csv"
    changes = [
        ({"energy_model_sha256": None}, "parametros_energeticos_nao_verificados"),
        ({"energy_model_sha256": ""}, "parametros_energeticos_nao_verificados"),
        ({"energy_model_sha256": "b" * 64}, "parametros_energeticos_diferentes"),
        ({"cultivable_area_m2": None}, "area_cultivavel_indisponivel"),
        ({"cultivable_area_m2": 0}, "area_cultivavel_indisponivel"),
        ({"cultivable_area_m2": "nan"}, "area_cultivavel_indisponivel"),
    ]
    rows = []
    for repetition, (invalid, _) in enumerate(changes, start=1):
        rows.extend([_row("referencia_2d", 100, repetition=repetition),
                     _row("proposta_completa", 1, repetition=repetition, **invalid)])
    _csv(source, rows)
    result = generate_benchmark_report(source, tmp_path / "report_fingerprints")
    report = _report(result)
    assert report["summary"]["expected_pairs"] == len(changes)
    assert report["summary"]["eligible_pairs"] == 0
    assert report["summary"]["observed_mean_estimated_energy_saving"] is False
    for pair, (_, expected_reason) in zip(report["pairs"], changes):
        assert pair["pair_exclusion_reasons"] == [expected_reason]
        assert pair["estimated_energy_reduction_percent"] is None
    # O relatório preserva os dados, inclusive a identidade ausente, sem inventar
    # um hash retroativo para permitir a comparação.
    assert report["pairs"][0]["proposed"]["energy_model_sha256"] == ""
    assert report["pairs"][2]["proposed"]["energy_model_sha256"] == "b" * 64


def test_report_uses_real_telemetry_for_exported_trajectory_plot(tmp_path):
    folder = tmp_path / "flight"
    folder.mkdir()
    _csv(folder / "telemetry.csv", [
        {"drone_x_m": 0, "drone_y_m": 0}, {"drone_x_m": 3, "drone_y_m": 4}])
    source = tmp_path / "comparison.csv"
    _csv(source, [_row("referencia_2d", 100, run_directory=str(folder)),
                 _row("proposta_completa", 90, run_directory=str(folder))])
    result = generate_benchmark_report(source, tmp_path / "report")
    assert (result / "trajectory_comparison.png").is_file()
    assert "trajectory_comparison.png" in (result / "index.html").read_text(encoding="utf-8")


def test_ablation_attributes_change_to_orientation_without_inventing_climb_effect(tmp_path):
    source = tmp_path / "comparison.csv"
    _csv(source, [_row("referencia_2d", 100), _row("distancia_3d", 100),
                  _row("somente_subida", 100), _row("somente_orientacao", 90),
                  _row("proposta_completa", 90)])
    output = generate_benchmark_report(source, tmp_path / "report_ablation")
    results = {item["method"]: item["summary"] for item in _report(output)["method_comparisons"]}
    assert results["somente_subida"]["case_mean_estimated_energy_reduction_percent"] == 0
    assert results["somente_orientacao"]["case_mean_estimated_energy_reduction_percent"] == 10
    assert results["proposta_completa"]["case_mean_estimated_energy_reduction_percent"] == 10
    assert "Contribuição de cada alteração" in (output / "index.html").read_text(encoding="utf-8")


def test_report_preserves_failed_temporal_check_without_changing_primary_result(tmp_path):
    source = tmp_path / "comparison.csv"
    _csv(source, [_row("referencia_2d", 100), _row("proposta_completa", 99)])
    diagnosis = tmp_path / "resolution"
    diagnosis.mkdir()
    (diagnosis / "protocol.json").write_text(json.dumps({"requested_time_step_s": .025}))
    _csv(diagnosis / "time_step_comparison.csv", [{"case": "a", "refined_time_step_s": .025,
        "comparable": False, "refined_reference_error": "Timeout no waypoint 0",
        "refined_proposed_error": "Timeout no waypoint 0"}])
    output = generate_benchmark_report(source, tmp_path / "report_with_diagnosis", time_step_check=diagnosis)
    report = _report(output)
    assert report["summary"]["mean_estimated_energy_reduction_percent"] == 1
    assert report["time_step_check"]["cases"][0]["comparable"] == "False"
    assert report["real_battery_saving_proven"] is False
    assert "Timeout no waypoint 0" in (output / "index.html").read_text(encoding="utf-8")
