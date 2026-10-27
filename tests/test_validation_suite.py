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
