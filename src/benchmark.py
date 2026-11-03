"""Executa voos, gera relatório e prepara a comparação visual no CoppeliaSim."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket

from src.benchmark_report import generate_benchmark_report
from src.comparison_scene import create_comparison_scene
from src.coverage_comparison import compare_coverage_flights
from src.validation_suite import run_validation_suite
from src.energy_sensitivity import analyze_energy_sensitivity


def check_simulator(host="127.0.0.1", port=23000):
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError as error:
        raise RuntimeError(f"Abra o CoppeliaSim e deixe a simulação parada. API {host}:{port}: {error}") from error


def run_benchmark(output: Path, manifest: Path | None = Path("configs/validation_suite.json"),
                  scenario: Path | None = None, dry_run=False,
                  host="127.0.0.1", port=23000, prepare_scene=True,
                  executor="lua", disable_rendering=False):
    """Mantém os voos originais; visualização é replay, sem gerar outra medição."""
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    if not dry_run:
        check_simulator(host, port)
    output.mkdir(parents=True)
    # Guarda a implementação exata, inclusive mudanças ainda não commitadas.
    source_hashes = {}
    root = Path(__file__).resolve().parents[1]
    for directory in ("src", "configs"):
        for source in sorted((root / directory).iterdir()):
            if source.is_file() and source.suffix in (".py", ".json", ".yaml"):
                destination = output / "implementation" / directory / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
                source_hashes[source.relative_to(root).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    session = {"dry_run": dry_run, "source_sha256": source_hashes, "executor": executor,
               "scope": "Trajetórias executadas pelo simulador e energia estimada. A cena lado a lado reproduz as telemetrias, sem física simultânea nova.",
               "real_battery_saving_proven": False, "status": "started"}
    session_path = output / "session.json"

    def save():
        session_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    flights = output / "flights"
    paired = bool(scenario)
    manifest_definition = {}
    if not scenario:
        manifest_definition = json.loads(Path(manifest).read_text(encoding="utf-8"))
        paired = not manifest_definition.get("ablation", True)
    relief_study = any("height_scale" in entry for entry in manifest_definition.get("locations", []))
    proposed = "proposta_subida_orientacao" if paired else "proposta_completa"
    try:
        if scenario:
            compare_coverage_flights(scenario, flights, host=host, port=port, dry_run=dry_run,
                                     executor=executor, disable_rendering=disable_rendering)
        else:
            run_validation_suite(Path(manifest), flights, dry_run=dry_run, host=host, port=port,
                                  executor=executor, disable_rendering=disable_rendering)
        session["status"] = "planned" if dry_run else "flights_finished"
    except Exception as error:
        session.update(status="failed", error=str(error))
        raise
    finally:
        # Um lote interrompido continua tendo relatório dos pares previstos.
        if not dry_run and flights.is_dir() and any((flights / name).exists() for name in ("manifest.json", "protocol.json")):
            try:
                generate_benchmark_report(flights, output / "report", proposed_method=proposed)
                session["report"] = str(output / "report/index.html")
                analyze_energy_sensitivity(output / "report", output / "sensitivity")
                session["sensitivity"] = str(output / "sensitivity/sensitivity_summary.json")
                if relief_study:
                    from src.relief_report import generate_relief_report
                    generate_relief_report(output, output / "relief_report")
                    session["relief_report"] = str(output / "relief_report/index.html")
            except Exception as error:
                session["report_error"] = str(error)
        save()
    if not dry_run and prepare_scene:
        # Seleção visual por ordem de coleta e disponibilidade, nunca por economia.
        pair = flights
        if not scenario:
            import csv
            attempts = json.loads((flights / "attempts.json").read_text(encoding="utf-8"))
            if relief_study:
                factors = {entry["id"]: float(entry.get("height_scale", 1.))
                           for entry in manifest_definition["locations"]}
                # Relevo maior é um critério visual declarado, sem consultar energia.
                attempts = sorted(attempts, key=lambda entry: -factors[entry["case"]])
            pair = flights / "case_00_repeat_01"
            for attempt in attempts:
                candidate = Path(attempt["output"])
                comparison = candidate / "comparison.csv"
                if comparison.is_file():
                    with comparison.open(encoding="utf-8-sig") as stream:
                        rows = {row["method"]: row for row in csv.DictReader(stream)}
                    if all(rows.get(method, {}).get("mission_completed") == "True"
                           for method in ("referencia_2d", proposed)):
                        pair = candidate
                        break
        session["presentation_source"] = str(pair)
        session["presentation_selection_rule"] = "Primeiro par em ordem de coleta com ambas missões completas; sem consultar ganho energético."
        if relief_study:
            session["presentation_selection_rule"] = "Maior fator de relevo com duas missões completas, desempate pela ordem do manifesto; sem consultar ganho energético."
        try:
            path = create_comparison_scene(pair, output / "presentation", proposed_method=proposed,
                                           host=host, port=port)
            session["scene"] = str(path)
        except Exception as error:
            session["presentation_error"] = str(error)
            print(f"Voos preservados; preparação visual falhou: {error}", flush=True)
    session["status"] = "planned" if dry_run else "finished"
    save()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--manifest", type=Path, default=Path("configs/validation_suite.json"))
    source.add_argument("--scenario", type=Path, help="Somente um par, para demonstração rápida.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-scene", action="store_true")
    parser.add_argument("--executor", choices=("python", "lua"), default="lua")
    parser.add_argument("--disable-rendering", action="store_true")
    parser.add_argument("--status", action="store_true", help="Consulta o estado atual do simulador sem iniciar voos.")
    parser.add_argument("--stop", action="store_true", help="Interrompe a execução física atual; o coletor preserva os dados como falha.")
    args = parser.parse_args()
    if args.status or args.stop:
        check_simulator(args.host, args.port)
        from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        sim = RemoteAPIClient(host=args.host, port=args.port).require("sim")
        if args.stop:
            sim.stopSimulation()
        print(json.dumps({"simulation_state": sim.getSimulationState(),
                          "simulation_time_s": sim.getSimulationTime(),
                          "realtime": sim.getBoolParam(sim.boolparam_realtime_simulation),
                          "time_step_s": sim.getSimulationTimeStep()}, ensure_ascii=False))
        return
    output = args.output or Path("output/experiments") / datetime.now().strftime("benchmark_%Y%m%d_%H%M%S_%f")
    result = run_benchmark(output, args.manifest, args.scenario, args.dry_run,
                           args.host, args.port, not args.no_scene,
                           args.executor, args.disable_rendering)
    print(f"Resultado: {result}")
    if not args.dry_run:
        session = json.loads((result / "session.json").read_text(encoding="utf-8"))
        if session.get("report"):
            print(f"Relatório: {session['report']}")
        if session.get("scene"):
            print("Aperte Play na cena de comparação do CoppeliaSim para reproduzir os dois voos.")
        for key in ("report_error", "presentation_error"):
            if session.get(key):
                print(f"Pendência preservada em session.json: {session[key]}")


if __name__ == "__main__":
    main()
