"""Executa referência e proposta no mesmo cenário, sem vento."""

import argparse
import csv
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

import numpy as np

import src.coppelia_scene as scene
from src.coppeliasim import run_wind_mission
from src.energy import analyze_telemetry, load_energy_model, model_manifest
from src.planning_experiments import case_from_scenario, compare_planners
from src.scenario import load_scenario
from src.waypoints import export_waypoints_csv, grid_path_to_waypoints_3d
from src.wind import WindEvent, WindScenario, WindVector
from src.ablation import select_ablation_plans


def _wait_stopped(sim) -> None:
    deadline = monotonic() + 10
    while sim.getSimulationState() != sim.simulation_stopped:
        if monotonic() >= deadline:
            raise RuntimeError("O CoppeliaSim não confirmou a parada em 10 segundos.")
        sleep(.1)


def compare_coverage_flights(
    scenario_path: Path, output: Path, scene_path: Path | None = None,
    host: str = "127.0.0.1", port: int = 23000,
    dry_run: bool = False, client_factory=None,
    energy_model_path: Path = Path("configs/energy_reference.json"),
    ablation: bool = False,
) -> Path:
    """A proposta usa subida e seleção horizontal/vertical; não mede bateria.

    Cada voo visita todas as células do plano em ordem, inclusive retorno à
    origem. A cobertura exportada é a planejada, não a efetivamente aplicada.
    """
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    if scene_path is not None:
        scene_path = scene_path.resolve()
        if not scene_path.is_file():
            raise FileNotFoundError(f"Cena não encontrada: {scene_path}")
    scenario = load_scenario(scenario_path)
    energy_model = load_energy_model(energy_model_path)
    scenario = replace(
        scenario, scenario_id=f"{scenario.scenario_id}_sem_vento",
        wind=WindScenario((WindEvent("sem_vento", 0., WindVector()),)),
        simulation=replace(scenario.simulation, apply_visual_force=False),
        output_root=output / "runs",
    )
    case = case_from_scenario(scenario_path)
    trials = compare_planners(case, (scenario.coverage.climb_weight,),
                              evaluation_weight=scenario.coverage.climb_weight)
    plans = [next(t for t in trials if t.method == method)
             for method in ("horizontal_2d", "climb_orientation")]
    if ablation:
        plans = select_ablation_plans(case, scenario.coverage.climb_weight)
    if not all(t.eligible for t in plans):
        raise RuntimeError("Ambas as rotas precisam atender à cobertura planejada de 100%.")
    if any(t.path[0] != case.launch or t.path[-1] != case.launch for t in plans):
        raise RuntimeError("As duas rotas precisam começar e terminar na mesma origem.")
    output.mkdir(parents=True, exist_ok=False)
    effective_path = output / "scenario_no_wind.json"
    effective_path.write_text(json.dumps(asdict(scenario), default=str,
                                         ensure_ascii=False, indent=2), encoding="utf-8")
    np.savez_compressed(output / "terrain.npz", terrain=case.terrain,
                        obstacle_mask=case.obstacle_mask)
    for plan in plans:
        waypoints = grid_path_to_waypoints_3d(
            case.terrain, plan.path, case.cell_x_m, case.cell_y_m,
            scenario.coverage.clearance_m,
        )
        export_waypoints_csv(waypoints, output / f"planned_{plan.method}.csv")
    (output / "protocol.json").write_text(json.dumps({
        "source_scenario_yaml": scenario_path.read_text(encoding="utf-8"),
        "effective_scenario": asdict(scenario), "launch": case.launch,
        "plans": [asdict(plan) for plan in plans],
        "energy_model": model_manifest(energy_model),
        "dry_run": dry_run, "scene": str(scene_path) if scene_path else "prepared_automatically",
        "limitations": "Energia estimada por referência teórica sem calibração; não mede bateria. Cobertura planejada discreta, sem medição de aplicação executada. Proposta combina subida e orientação.",
    }, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    if dry_run:
        return output
    if client_factory is None:
        from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        client_factory = RemoteAPIClient
    sim = client_factory(host=host, port=port).require("sim")
    if sim.getSimulationState() != sim.simulation_stopped:
        raise RuntimeError("Pare a simulação antes da comparação.")
    # Preserva inclusive a cena aberta quando o usuário fornece outra cena.
    sim.saveScene((output / "scene_before.ttt").resolve().as_posix())
    if scene_path is None:
        app = Path(sim.getStringParam(sim.stringparam_application_path))
        previous_tree_model = scene.DEFAULT_TREE_MODEL
        try:
            scene.DEFAULT_TREE_MODEL = app / "models/nature/Tree.ttm"
            prepared = scene.setup_scene(
                scenario, output / "comparison_scene.ttt",
                model_path=app / "models/robots/mobile/Quadcopter.ttm",
                host=host, port=port, client_factory=client_factory,
            )
        finally:
            scene.DEFAULT_TREE_MODEL = previous_tree_model
        if not prepared.success:
            raise RuntimeError(prepared.error)
        scene_path = prepared.scene_path.resolve()
    rows = []
    labels = [p.method for p in plans] if ablation else ["referencia_2d", "proposta_subida_orientacao"]
    for plan, label in zip(plans, labels):
        _wait_stopped(sim)
        sim.loadScene(scene_path.as_posix())
        sim.adjustView(0, sim.getObject("/DefaultCamera"), 0)
        sim.setObjectSelection([])
        sim.setBoolParam(sim.boolparam_infotext_visible, False)
        print(f"VOO: {label} | faixas {plan.orientation} | sem vento", flush=True)
        flight_scenario = replace(scenario, scenario_id=label)
        # O executor não deve regenerar faixas: usa exatamente a rota comparada.
        log = run_wind_mission(
            flight_scenario, case.terrain, plan.path.copy(), plan.path.copy(),
            scenario_path, host, port, client_factory=client_factory,
            replanning_enabled=False,
        )
        with (log.output_directory / "metrics.csv").open(encoding="utf-8-sig") as stream:
            metrics = next(csv.DictReader(stream))
        energy = analyze_telemetry(log.output_directory / "telemetry.csv", energy_model,
                                   log.output_directory / "energy")
        rows.append({
            "method": label, "orientation": plan.orientation,
            "planned_coverage_percent": plan.coverage_percent,
            "planned_normalized_cost": plan.normalized_cost,
            "run_directory": str(log.output_directory), **metrics, **energy,
        })
        with (output / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Concluído: {log.success}; logs: {log.output_directory}", flush=True)
    _wait_stopped(sim)
    print("Comparação concluída. O custo normalizado não representa consumo de bateria.")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("configs/demo_coverage.yaml"))
    parser.add_argument("--scene", type=Path, help="Cena compatível; se omitida, prepara automaticamente.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ablation", action="store_true", help="Compara as cinco variantes para isolar contribuições.")
    parser.add_argument("--energy-model", type=Path, default=Path("configs/energy_reference.json"))
    args = parser.parse_args()
    output = args.output or Path("output/experiments") / datetime.now().strftime("coverage_%Y%m%d_%H%M%S_%f")
    result = compare_coverage_flights(args.scenario, output, args.scene, args.host,
                                     args.port, args.dry_run, energy_model_path=args.energy_model,
                                     ablation=args.ablation)
    print(f"{'Planos validados' if args.dry_run else 'Resultados'}: {result}")


if __name__ == "__main__":
    main()
