import json
from pathlib import Path

import pytest

import src.benchmark as benchmark


def test_replay_uses_recorded_scenario_in_nested_batch(tmp_path):
    scenario = tmp_path / "monte_verde.yaml"
    scenario.write_text("id: monte_verde\n", encoding="utf-8")
    run = tmp_path / "batch" / "case_1"
    flights = run / "flights"
    flights.mkdir(parents=True)
    (run / "session.json").write_text('{"status":"finished"}')
    (flights / "comparison.csv").write_text(
        "method,mission_completed\nreferencia_2d,True\nproposta_subida_orientacao,True\n"
    )
    protocol = flights / "protocol.json"
    protocol.write_text(json.dumps({"source_scenario_yaml": "id: serra_do_cipo\n"}))
    assert benchmark.find_recorded_pair(tmp_path, scenario) is None
    protocol.write_text(json.dumps({"source_scenario_yaml": scenario.read_text()}))
    assert benchmark.find_recorded_pair(tmp_path, scenario) == flights


def test_dry_benchmark_records_protocol_and_implementation_without_simulator(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "check_simulator", lambda *args: pytest.fail("Não conectar"))
    def suite(manifest, output, **kwargs):
        assert kwargs["dry_run"] is True
        output.mkdir()
        (output / "protocol.json").write_text('{}')
    monkeypatch.setattr(benchmark, "compare_coverage_flights", suite)
    result = benchmark.run_benchmark(tmp_path / "benchmark", dry_run=True)
    session = json.loads((result / "session.json").read_text(encoding="utf-8"))
    assert session["status"] == "planned"
    assert session["real_battery_saving_proven"] is False
    assert (result / "implementation/src/coppeliasim.py").is_file()
    assert session["source_sha256"]["configs/demo_coverage.yaml"]
    assert not (result / "report").exists()


def test_partial_benchmark_gets_report_and_keeps_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "check_simulator", lambda *args: None)
    def suite(manifest, output, **kwargs):
        output.mkdir()
        (output / "protocol.json").write_text('{}')
        raise RuntimeError("voo interrompido")
    monkeypatch.setattr(benchmark, "compare_coverage_flights", suite)
    calls = []
    monkeypatch.setattr(benchmark, "generate_benchmark_report", lambda *args, **kwargs: calls.append(args))
    output = tmp_path / "benchmark"
    with pytest.raises(RuntimeError, match="interrompido"):
        benchmark.run_benchmark(output)
    session = json.loads((output / "session.json").read_text(encoding="utf-8"))
    assert session["status"] == "failed" and len(calls) == 1
    assert session["error"] == "voo interrompido"


def test_pair_benchmark_prepares_replay_of_prespecified_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "check_simulator", lambda *args: None)
    calls = []
    def compare(source, output, **kwargs):
        output.mkdir()
        (output / "protocol.json").write_text('{}')
    monkeypatch.setattr(benchmark, "compare_coverage_flights", compare)
    monkeypatch.setattr(benchmark, "generate_benchmark_report", lambda *args, **kwargs: calls.append(("report", args, kwargs)))
    monkeypatch.setattr(benchmark, "create_comparison_scene", lambda *args, **kwargs: calls.append(("scene", args, kwargs)) or Path("scene.ttt"))
    result = benchmark.run_benchmark(tmp_path / "benchmark", scenario=Path("scenario.yaml"))
    session = json.loads((result / "session.json").read_text(encoding="utf-8"))
    assert session["status"] == "finished"
    assert [c[0] for c in calls] == ["report", "scene"]
    assert calls[0][2]["proposed_method"] == calls[1][2]["proposed_method"] == "proposta_subida_orientacao"
