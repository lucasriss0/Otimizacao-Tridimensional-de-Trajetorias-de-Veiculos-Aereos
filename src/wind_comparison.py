"""Comparação pareada de voo com vento e replanejamento ligado/desligado."""

import argparse
import csv
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic, sleep

from src.coppeliasim import prepare_scenario_route, run_wind_mission
from src.scenario import load_scenario


def compare_wind_flights(
    scenario_path: Path, scene_path: Path, output: Path,
    host: str = "localhost", port: int = 23000,
    dry_run: bool = False, client_factory=None,
) -> Path:
    """Recarrega a mesma cena parada antes de cada voo.

    Desliga somente a deriva comandada do target em ambos os casos; a força
    física aproximada, vento, controlador e rota inicial são idênticos.
    """
    scene_path = scene_path.resolve()
    if not scene_path.is_file():
        raise FileNotFoundError(f"Cena não encontrada: {scene_path}")
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    scenario = load_scenario(scenario_path)
    if not scenario.simulation.apply_visual_force:
        raise ValueError("A comparação requer apply_visual_force=true nos dois voos.")
    scenario = replace(scenario, wind=replace(scenario.wind, maximum_drift_m=0.),
                       output_root=output / "runs")
    terrain, targets, initial_path = prepare_scenario_route(scenario)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(scenario_path, output / "source_scenario.yaml")
    (output / "protocol.json").write_text(json.dumps({
        "scenario": asdict(scenario), "scene": str(scene_path),
        "cases": ["sem_replanejamento", "com_replanejamento"],
        "initial_path": initial_path, "targets": targets,
        "dry_run": dry_run,
        "limitations": "Força aproximada sem calibração aerodinâmica; sem deriva comandada do target. Não mede bateria ou cobertura executada.",
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if dry_run:
        return output
    if client_factory is None:
        from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        client_factory = RemoteAPIClient
    client = client_factory(host=host, port=port)
    sim = client.require("sim")
    if sim.getSimulationState() != sim.simulation_stopped:
        raise RuntimeError("Pare a simulação antes da comparação.")
    rows = []
    for enabled, name in ((False, "sem_replanejamento"), (True, "com_replanejamento")):
        # Uma cena recarregada evita herdar estado dinâmico do voo anterior.
        deadline = monotonic() + 10
        while sim.getSimulationState() != sim.simulation_stopped:
            if monotonic() >= deadline:
                raise RuntimeError("O simulador não confirmou a parada em 10 segundos.")
            sleep(.1)
        sim.loadScene(scene_path.as_posix())
        case = replace(scenario, scenario_id=f"{scenario.scenario_id}_{name}")
        log = run_wind_mission(
            case, terrain, targets.copy(), initial_path.copy(), scenario_path,
            host, port, client_factory=client_factory, replanning_enabled=enabled,
        )
        with (log.output_directory / "metrics.csv").open(encoding="utf-8-sig") as stream:
            metrics = next(csv.DictReader(stream))
        rows.append({"case": name, "run_directory": str(log.output_directory), **metrics})
        # Preserva o primeiro resultado mesmo se o segundo voo não puder iniciar.
        with (output / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("configs/demo_wind.yaml"))
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = compare_wind_flights(args.scenario, args.scene, args.output,
                                 args.host, args.port, args.dry_run)
    print(f"{'Protocolo validado' if args.dry_run else 'Comparação salva'}: {result}")


if __name__ == "__main__":
    main()
