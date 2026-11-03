import csv
import json
from pathlib import Path

import src.validation_suite as suite


def test_batch_keeps_geographic_cases_repetitions_and_failures(tmp_path, monkeypatch):
    manifest = {
        "base_scenario": str(Path("configs/demo_coverage.yaml").resolve()),
        "energy_model": str(Path("configs/energy_reference.json").resolve()),
        "repetitions": 2, "minimum_executed_coverage_percent": 100,
        "maximum_telemetry_gap_s": 1,
        "locations": [{"id": "a", "center_lat": -22.48, "center_lon": -47.26},
                      {"id": "b", "center_lat": -22.50, "center_lon": -47.26}],
    }
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []

    def compare(path, folder, **kwargs):
        calls.append((path, folder, kwargs))
        if len(calls) == 2:
            raise RuntimeError("falha preservada")
        folder.mkdir()
        (folder / "comparison.csv").write_text("method,energy_comparison_eligible\nreference,False\n", encoding="utf-8")

    monkeypatch.setattr(suite, "compare_coverage_flights", compare)
    output = suite.run_validation_suite(source, tmp_path / "batch")
    attempts = json.loads((output / "attempts.json").read_text(encoding="utf-8"))
    assert len(attempts) == len(calls) == 4
    assert [a["status"] for a in attempts] == ["recorded", "failed", "recorded", "recorded"]
    assert attempts[1]["error"] == "falha preservada"
    assert all(call[2]["ablation"] for call in calls)
    with (output / "all_flights.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3 and all(r["energy_comparison_eligible"] == "False" for r in rows)


def test_partial_attempt_keeps_collected_flights_even_after_error(tmp_path, monkeypatch):
    manifest = json.loads(Path("configs/validation_suite.json").read_text(encoding="utf-8"))
    manifest.update(base_scenario=str(Path("configs/demo_coverage.yaml").resolve()),
                    energy_model=str(Path("configs/energy_reference.json").resolve()),
                    repetitions=1, locations=manifest["locations"][:1])
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    def compare(path, folder, **kwargs):
        folder.mkdir()
        (folder / "comparison.csv").write_text("method,energy_comparison_eligible\nreferencia_2d,False\n", encoding="utf-8")
        raise RuntimeError("falha depois do primeiro voo")
    monkeypatch.setattr(suite, "compare_coverage_flights", compare)
    output = suite.run_validation_suite(source, tmp_path / "batch")
    with (output / "all_flights.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["method"] == "referencia_2d"
    attempts = json.loads((output / "attempts.json").read_text(encoding="utf-8"))
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["expected_flights"] == 5


def test_relief_manifest_applies_height_factor_and_compares_two_methods(tmp_path, monkeypatch):
    import yaml
    manifest = json.loads(Path("configs/relief_suite.json").read_text(encoding="utf-8"))
    manifest.update(base_scenario=str(Path("configs/demo_relief.yaml").resolve()),
                    energy_model=str(Path("configs/energy_reference.json").resolve()))
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []
    def compare(path, folder, **kwargs):
        calls.append((yaml.safe_load(path.read_text(encoding="utf-8")), kwargs))
    monkeypatch.setattr(suite, "compare_coverage_flights", compare)
    output = suite.run_validation_suite(source, tmp_path / "batch", dry_run=True)
    assert len(calls) == 9
    assert [c[0]["terrain"]["height_scale"] for c in calls] == [1, 1, 1, 5, 5, 5, 10, 10, 10]
    assert all(c[0]["simulation"]["speed_mps"] == 4 for c in calls)
    assert all(c[1]["ablation"] is False and len(c[1]["method_order"]) == 2 for c in calls)
    assert calls[0][1]["method_order"] == list(reversed(calls[1][1]["method_order"]))
    attempts = json.loads((output / "attempts.json").read_text(encoding="utf-8"))
    assert all(a["expected_flights"] == 2 and a["status"] == "planned" for a in attempts)
