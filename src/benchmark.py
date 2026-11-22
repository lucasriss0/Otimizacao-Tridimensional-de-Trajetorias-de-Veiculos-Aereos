"""Executa voos, gera relatório e prepara a comparação visual no CoppeliaSim."""

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket

from src.benchmark_report import generate_benchmark_report
from src.comparison_scene import create_comparison_scene
from src.coverage_comparison import compare_coverage_flights


def check_simulator(host="127.0.0.1", port=23000):
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError as error:
        raise RuntimeError(f"Abra o CoppeliaSim e deixe a simulação parada. API {host}:{port}: {error}") from error


def find_recorded_pair(root: Path, scenario: Path) -> Path | None:
    source_yaml = scenario.read_text(encoding="utf-8")
    sessions = [*root.glob("*/session.json"), *root.glob("*/*/session.json")]
    for path in sorted(sessions, key=lambda path: path.stat().st_mtime, reverse=True):
        session = json.loads(path.read_text(encoding="utf-8"))
        pair = path.parent / "flights"
        protocol_path = pair / "protocol.json"
        comparison = pair / "comparison.csv"
        if session.get("status") != "finished" or not protocol_path.is_file() or not comparison.is_file():
            continue
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        if protocol.get("source_scenario_yaml") != source_yaml or protocol.get("dry_run"):
            continue
        with comparison.open(encoding="utf-8-sig", newline="") as stream:
            completed = {row["method"] for row in csv.DictReader(stream)
                         if row["mission_completed"] == "True"}
        if {"referencia_2d", "proposta_subida_orientacao"} <= completed:
            return pair
    return None


def run_benchmark(output: Path, scenario: Path = Path("configs/demo_coverage.yaml"), dry_run=False,
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
    proposed = "proposta_subida_orientacao"
    try:
        compare_coverage_flights(scenario, flights, host=host, port=port, dry_run=dry_run,
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
            except Exception as error:
                session["report_error"] = str(error)
        save()
    if not dry_run and prepare_scene:
        session["presentation_source"] = str(flights)
        try:
            path = create_comparison_scene(flights, output / "presentation",
                                           proposed_method=proposed, host=host, port=port)
            session["scene"] = str(path)
        except Exception as error:
            session["presentation_error"] = str(error)
            print(f"Voos preservados; preparação visual falhou: {error}", flush=True)
    session["status"] = "planned" if dry_run else "finished"
    save()
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("configs/demo_coverage.yaml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-scene", action="store_true")
    parser.add_argument("--reuse-replay", action="store_true",
                        help="Abre uma comparação completa já salva para o cenário; coleta novos voos se necessário.")
    parser.add_argument("--executor", choices=("python", "lua"), default="lua")
    parser.add_argument("--disable-rendering", action="store_true")
    parser.add_argument("--status", action="store_true", help="Consulta o estado atual do simulador sem iniciar voos.")
    parser.add_argument("--stop", action="store_true", help="Interrompe a execução física atual; o coletor preserva os dados como falha.")
    args = parser.parse_args(argv)
    if args.reuse_replay:
        if not args.scenario or args.dry_run or args.no_scene or args.status or args.stop:
            parser.error("--reuse-replay exige --scenario e uma execução com cena.")
        pair = find_recorded_pair(Path("output/experiments").resolve(), args.scenario)
        if pair is not None:
            check_simulator(args.host, args.port)
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
            sim = RemoteAPIClient(host=args.host, port=args.port).require("sim")
            if sim.getSimulationState() != sim.simulation_stopped:
                raise RuntimeError("Clique em Stop no CoppeliaSim antes de abrir a comparação.")
            renderer = Path(__file__).with_name("comparison_scene.py")
            version = hashlib.sha256(renderer.read_bytes()).hexdigest()[:12]
            prefix = f"presentation_{version}_"
            saved = sorted(pair.parent.glob(prefix + "*/replay_manifest.json"), reverse=True)
            scene = next((m.with_name("comparacao_lado_a_lado.ttt") for m in saved
                          if m.with_name("comparacao_lado_a_lado.ttt").is_file()), None)
            if scene is None:
                output = pair.parent / (prefix + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
                scene = create_comparison_scene(pair, output, host=args.host, port=args.port)
            else:
                sim.loadScene(scene.as_posix())
            print(f"Cena dos voos registrados: {scene}")
            print("Aperte Play para reproduzir as duas trajetórias lado a lado.")
            return
        print("Preparando a primeira comparação. Durante a coleta, aparece um terreno por vez.", flush=True)
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
    result = run_benchmark(output, args.scenario, args.dry_run,
                           args.host, args.port, not args.no_scene,
                           args.executor, args.disable_rendering)
    print(f"Resultado: {result}")
    if not args.dry_run:
        session = json.loads((result / "session.json").read_text(encoding="utf-8"))
        if session.get("report"):
            print(f"Relatório: {session['report']}")
        if session.get("scene"):
            print(f"Cena: {session['scene']}")
            print("Aperte Play na cena de comparação do CoppeliaSim para reproduzir os dois voos.")
        for key in ("report_error", "presentation_error"):
            if session.get(key):
                print(f"Pendência preservada em session.json: {session[key]}")
        if session.get("presentation_error"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
