import csv
import json

import src.time_step_check as check


def test_time_step_check_preserves_plans_and_all_geographic_cases(tmp_path, monkeypatch):
    source = tmp_path / "benchmark"
    flights = source / "flights"
    flights.mkdir(parents=True)
    (source / "implementation/configs").mkdir(parents=True)
    (source / "implementation/configs/energy_reference.json").write_text('{}')
    (flights / "manifest.json").write_text(json.dumps({"definition": {"locations": [{"id": "a"}, {"id": "b"}]}}))
    attempts = []
    for index, case in enumerate(("a", "b")):
        run = flights / f"case_{index}_repeat_01"
        run.mkdir()
        plans = [{"method": name, "path": [[0, 0], [0, 1], [0, 0]]} for name in ("referencia_2d", "proposta_completa")]
        (run / "protocol.json").write_text(json.dumps({"plans": plans}))
        with (run / "comparison.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["method", "mission_completed", "energy_comparison_eligible", "estimated_energy_wh"])
            writer.writerows([["referencia_2d", True, True, 100], ["proposta_completa", True, True, 99]])
        attempts.append({"case": case, "output": str(run)})
    (flights / "attempts.json").write_text(json.dumps(attempts))
    calls = []
    def compare(scenario, output, **kwargs):
        calls.append((scenario, kwargs))
        output.mkdir()
        plans = [{"method": name, "path": [[0, 0], [0, 1], [0, 0]]} for name in ("horizontal_2d", "climb_orientation")]
        (output / "protocol.json").write_text(json.dumps({"plans": plans}))
        with (output / "comparison.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["method", "energy_comparison_eligible", "estimated_energy_wh"])
            writer.writerows([["referencia_2d", True, 100], ["proposta_subida_orientacao", True, 98.5]])
    monkeypatch.setattr(check, "compare_coverage_flights", compare)
    output = check.run_time_step_check(source, tmp_path / "resolution")
    assert len(calls) == 2 and all(c[1]["time_step_s"] == .025 for c in calls)
    assert all(c[1]["executor"] == "lua" for c in calls)
    with (output / "time_step_comparison.csv").open(encoding="utf-8-sig") as stream:
        results = list(csv.DictReader(stream))
    assert [r["case"] for r in results] == ["a", "b"]
    assert all(r["identical_plans"] == r["comparable"] == "True" for r in results)
    assert all(abs(float(r["change_percentage_points"]) - .5) < 1e-9 for r in results)
    # A reanálise usa os logs já coletados, sem executar novos voos.
    monkeypatch.setattr(check, "compare_coverage_flights", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Não conectar")))
    repeated = check.analyze_time_step_check(output, tmp_path / "reanalyzed")
    with (repeated / "time_step_comparison.csv").open(encoding="utf-8-sig") as stream:
        assert list(csv.DictReader(stream)) == results
