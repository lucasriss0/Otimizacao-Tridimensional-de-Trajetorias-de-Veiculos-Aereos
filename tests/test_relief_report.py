import csv
import json

import numpy as np
import pytest

from src.relief_report import generate_relief_report, summarize_levels


def test_level_summary_preserves_worsening_ties_and_failed_cases():
    rows = [{"height_scale": 1., "comparable": True, "estimated_energy_reduction_percent": 0.},
            {"height_scale": 5., "comparable": True, "estimated_energy_reduction_percent": -2.},
            {"height_scale": 5., "comparable": False, "estimated_energy_reduction_percent": None},
            {"height_scale": 10., "comparable": True, "estimated_energy_reduction_percent": 3.}]
    levels = summarize_levels(rows)
    assert levels[0]["tied_pairs"] == 1
    assert levels[1]["mean_estimated_energy_reduction_percent"] == -2
    assert levels[1]["eligible_pairs"] == 1 and levels[1]["expected_pairs"] == 2
    assert levels[1]["negative_pairs"] == 1


def _study(tmp_path, different_speed=False):
    root = tmp_path / "study"
    root.mkdir()
    locations, attempts, rows = [], [], []
    for index, factor in enumerate((1., 5.)):
        case = f"terrain_x{factor:g}"
        locations.append({"id": case, "geographic_origin": "terrain", "height_scale": factor})
        folder = root / f"case_{index:02d}_repeat_01"
        folder.mkdir()
        protocol = {"effective_scenario": {"simulation": {"speed_mps": 8 if different_speed and index else 4},
            "coverage": {"window": {"row_start": 0, "col_start": 0, "row_end": 2, "col_end": 2}},
            "terrain": {"area_m": 90., "size": 3, "height_scale": factor}}, "energy_model": {"model": "reference"}}
        (folder / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
        np.savez_compressed(folder / "terrain.npz", terrain=np.arange(9).reshape(3, 3) * factor)
        attempts.append({"case": case, "repetition": 1, "output": str(folder), "status": "recorded"})
        for method, energy in (("referencia_2d", 100), ("proposta_subida_orientacao", 100 if index == 0 else 95)):
            rows.append({"geographic_case": case, "repetition": 1, "method": method,
                "energy_comparison_eligible": True, "mission_completed_safely": True,
                "energy_estimate_available": True, "estimated_energy_wh": energy,
                "energy_model": "reference", "energy_model_sha256": "a" * 64,
                "energy_outside_envelope_intervals": 0, "executed_coverage_available": True,
                "executed_coverage_percent": 100, "coverage_telemetry_gaps": 0,
                "cultivable_area_m2": 8100, "executed_covered_area_m2": 8100})
    (root / "manifest.json").write_text(json.dumps({"definition": {"locations": locations, "repetitions": 1}}), encoding="utf-8")
    (root / "attempts.json").write_text(json.dumps(attempts), encoding="utf-8")
    with (root / "all_flights.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return root


def test_report_compares_executed_pairs_and_labels_synthetic_relief(tmp_path):
    source = _study(tmp_path)
    output = generate_relief_report(source, tmp_path / "report")
    data = json.loads((output / "relief_comparison.json").read_text(encoding="utf-8"))
    assert data["expected_pairs"] == data["eligible_pairs"] == 2
    assert data["real_battery_saving_proven"] is False
    assert [r["relief_m"] for r in data["records"]] == [8., 40.]
    assert [r["synthetic_terrain"] for r in data["records"]] == [False, True]
    assert data["records"][1]["change_vs_original_percentage_points"] == 5
    assert (output / "energy_by_relief.png").exists()
    assert (output / "terrain_levels.png").exists()
    assert "terrenos sintéticos" in (output / "index.html").read_text(encoding="utf-8")


def test_report_rejects_changed_controller_speed_between_relief_levels(tmp_path):
    with pytest.raises(ValueError, match="mesmo regime"):
        generate_relief_report(_study(tmp_path, different_speed=True), tmp_path / "report")


def test_report_rejects_mixing_conventional_and_legacy_astar_reference(tmp_path):
    source = _study(tmp_path)
    path = source / 'case_01_repeat_01/protocol.json'
    protocol = json.loads(path.read_text(encoding='utf-8'))
    protocol['baseline_planner'] = 'parallel_geometric_v1'
    path.write_text(json.dumps(protocol),encoding='utf-8')
    with pytest.raises(ValueError,match='mesmo regime'):
        generate_relief_report(source,tmp_path/'report')


def test_smaller_loss_with_relief_is_not_reported_as_energy_saving(tmp_path):
    source = _study(tmp_path)
    path = source/'all_flights.csv'
    with path.open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['method']=='proposta_subida_orientacao':
            row['estimated_energy_wh'] = 110 if row['geographic_case']=='terrain_x1' else 105
    with path.open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    output=generate_relief_report(source,tmp_path/'report')
    text=(output/'relatorio.md').read_text(encoding='utf-8')
    assert 'a desvantagem estimada diminuiu' in text
    assert 'a vantagem estimada cresceu' not in text


def test_report_preserves_blocked_case_and_explains_missing_flight(tmp_path):
    source = _study(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["definition"]["locations"].append({"id": "terrain_x10", "geographic_origin": "terrain", "height_scale": 10})
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    attempts = json.loads((source / "attempts.json").read_text(encoding="utf-8"))
    attempts.append({"case": "terrain_x10", "repetition": 1, "output": str(source / "missing"),
                     "status": "failed", "error": "A rota sai do terreno físico."})
    (source / "attempts.json").write_text(json.dumps(attempts), encoding="utf-8")
    output = generate_relief_report(source, tmp_path / "report")
    data = json.loads((output / "relief_comparison.json").read_text(encoding="utf-8"))
    assert data["expected_pairs"] == 3 and data["eligible_pairs"] == 2
    blocked = data["records"][-1]
    assert not blocked["comparable"] and blocked["estimated_energy_reduction_percent"] is None
    assert blocked["attempt_error"] == attempts[-1]["error"]
    assert attempts[-1]["error"] in (output / "index.html").read_text(encoding="utf-8")
    assert data["trends"][0]["all_levels_eligible"] is False
