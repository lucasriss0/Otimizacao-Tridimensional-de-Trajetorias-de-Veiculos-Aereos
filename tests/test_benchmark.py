import json
from pathlib import Path

import pytest

import src.benchmark as benchmark


def test_dry_benchmark_records_protocol_and_implementation_without_simulator(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "check_simulator", lambda *args: pytest.fail("Não conectar"))
    def suite(manifest, output, **kwargs):
        assert kwargs["dry_run"] is True
        output.mkdir()
        (output / "manifest.json").write_text('{}')
    monkeypatch.setattr(benchmark, "run_validation_suite", suite)
    result = benchmark.run_benchmark(tmp_path / "benchmark", dry_run=True)
    session = json.loads((result / "session.json").read_text(encoding="utf-8"))
    assert session["status"] == "planned"
    assert session["real_battery_saving_proven"] is False
    assert (result / "implementation/src/coppeliasim.py").is_file()
    assert session["source_sha256"]["configs/validation_suite.json"]
    assert not (result / "report").exists()


def test_partial_benchmark_gets_report_and_keeps_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "check_simulator", lambda *args: None)
    def suite(manifest, output, **kwargs):
        output.mkdir()
        (output / "manifest.json").write_text('{}')
        raise RuntimeError("voo interrompido")
    monkeypatch.setattr(benchmark, "run_validation_suite", suite)
    calls = []
    monkeypatch.setattr(benchmark, "generate_benchmark_report", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(benchmark, "analyze_energy_sensitivity", lambda *args: None)
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
    monkeypatch.setattr(benchmark, "analyze_energy_sensitivity", lambda *args: None)
    monkeypatch.setattr(benchmark, "create_comparison_scene", lambda *args, **kwargs: calls.append(("scene", args, kwargs)) or Path("scene.ttt"))
    result = benchmark.run_benchmark(tmp_path / "benchmark", scenario=Path("scenario.yaml"))
    session = json.loads((result / "session.json").read_text(encoding="utf-8"))
    assert session["status"] == "finished"
    assert [c[0] for c in calls] == ["report", "scene"]
    assert calls[0][2]["proposed_method"] == calls[1][2]["proposed_method"] == "proposta_subida_orientacao"
