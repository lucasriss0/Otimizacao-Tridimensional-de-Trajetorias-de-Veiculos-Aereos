"""Executa referência e proposta no mesmo cenário, sem vento."""

import argparse
import csv
import json
import hashlib
import socket
import subprocess
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from math import isfinite
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
from src.conventional import plan_conventional, BASELINE_DESCRIPTION, BASELINE_VERSION
from src.executed_coverage import (
    analyze_executed_coverage, assess_flight, export_energy_contrasts,
    measure_executed_coverage,
)


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
    minimum_executed_coverage: float = 100.,
    maximum_telemetry_gap_s: float = 1.,
    method_order: list[str] | None = None,
    executor: str = "python",
    disable_rendering: bool = False,
    time_step_s: float | None = None,
    energy_planning: bool = False,
) -> Path:
    """A proposta usa subida e seleção horizontal/vertical; não mede bateria.

    Cada voo visita todas as células do plano em ordem, inclusive retorno à
    origem. Cobertura executada é geométrica e não mede deposição de produto.
    """
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    if energy_planning and ablation:
        raise ValueError("Seleção energética e ablação histórica são experimentos separados.")
    if executor not in ("python", "lua"):
        raise ValueError("Executor deve ser python ou lua.")
    if time_step_s is not None and (not isfinite(time_step_s) or not 0 < time_step_s <= .2):
        raise ValueError("Passo temporal deve ser finito e estar em (0, 0,2] segundos.")
    if scene_path is not None:
        scene_path = scene_path.resolve()
        if not scene_path.is_file():
            raise FileNotFoundError(f"Cena não encontrada: {scene_path}")
    scenario = load_scenario(scenario_path)
    energy_model = load_energy_model(energy_model_path)
    energy_fingerprint = hashlib.sha256(json.dumps(model_manifest(energy_model),
        sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    scenario = replace(
        scenario, scenario_id=f"{scenario.scenario_id}_sem_vento",
        wind=WindScenario((WindEvent("sem_vento", 0., WindVector()),)),
        simulation=replace(scenario.simulation, apply_visual_force=False),
        output_root=output / "runs",
    )
    case = case_from_scenario(scenario_path)
    assess_flight({}, {}, {}, minimum_executed_coverage)
    measure_executed_coverage([], case, maximum_telemetry_gap_s)
    trials = compare_planners(case, (scenario.coverage.climb_weight,),
                              evaluation_weight=scenario.coverage.climb_weight)
    plans = [plan_conventional(case, scenario.coverage.climb_weight),
             next(t for t in trials if t.method == "climb_orientation")]
    if ablation:
        plans = select_ablation_plans(case, scenario.coverage.climb_weight)
    labels = [p.method for p in plans] if ablation else ["referencia_2d", "proposta_subida_orientacao"]
    physical_window = case.window.expanded(scenario.simulation.terrain_padding_cells, case.terrain.shape)
    energy_selection = None
    if energy_planning:
        from src.energy_planning import select_energy_plan
        energy_selection = select_energy_plan(case, energy_model,
            scenario.simulation.speed_mps, scenario.coverage.climb_weight, physical_window,
            scenario.coverage.clearance_m, scenario.simulation.minimum_clearance_m)
        plans.append(energy_selection.plan)
        labels.append("proposta_energia")
    if method_order is not None and (len(method_order) != len(labels) or set(method_order) != set(labels)):
        raise ValueError("A ordem dos métodos deve ser uma permutação exata dos métodos comparados.")
    execution_order = list(method_order or labels)
    if not all(t.eligible for t in plans):
        raise RuntimeError("Ambas as rotas precisam atender à cobertura planejada de 100%.")
    if any(t.path[0] != case.launch or t.path[-1] != case.launch for t in plans):
        raise RuntimeError("As duas rotas precisam começar e terminar na mesma origem.")
    if any(not (physical_window.row_start <= r <= physical_window.row_end
                and physical_window.col_start <= c <= physical_window.col_end)
           for plan in plans for r, c in plan.path):
        raise RuntimeError("A rota sai do terreno físico. Aumente terrain_padding_cells antes da coleta.")
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
        "physical_terrain_window": asdict(physical_window),
        "terrain_interpretation": "TOPODATA original" if scenario.terrain.height_scale == 1 else "Terreno sintético: exagero vertical do TOPODATA, não representa novas altitudes reais.",
        "method_order": execution_order,
        "executor": "lua_physics_v1" if executor == "lua" else "python_rpc",
        "rendering_disabled_during_run": disable_rendering,
        "requested_time_step_s": time_step_s,
        "baseline_planner": BASELINE_VERSION,
        "baseline_description": BASELINE_DESCRIPTION,
        "energy_planning": energy_selection.manifest() if energy_selection else None,
        "method_plan_mapping": dict(zip(labels,[p.method for p in plans])),
        "comparison_scope": "Referência operacional geométrica sem A* versus proposta A*. Não reproduz o algoritmo interno de um fabricante.",
        "collision_monitoring": "Obrigatório, coleção de todas as shapes do drone contra terreno e obstáculos; falha de leitura invalida o voo.",
        "git_revision": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")},
        "energy_model": model_manifest(energy_model),
        "energy_model_sha256": energy_fingerprint,
        "minimum_executed_coverage_percent": minimum_executed_coverage,
        "maximum_telemetry_gap_s": maximum_telemetry_gap_s,
        "application_policy": "Desligada durante estabilização; ativa na missão, conexões e retorno. Modelo geométrico de faixa, sem bomba física.",
        "dry_run": dry_run, "scene": str(scene_path) if scene_path else "prepared_automatically",
        "limitations": "Energia estimada por referência teórica sem calibração; não mede bateria. Cobertura geométrica dos centros de células, sem medição de deposição. Proposta combina subida e orientação.",
    }, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    if dry_run:
        return output
    managed_connection = client_factory is None
    if client_factory is None:
        from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        try:
            with socket.create_connection((host, port), timeout=3):
                pass
        except OSError as error:
            raise RuntimeError(f"CoppeliaSim indisponível em {host}:{port}. Abra o aplicativo e deixe a simulação parada. {error}") from error
        client_factory = RemoteAPIClient
    client = client_factory(host=host, port=port)
    if managed_connection:
        import zmq
        client.timeout = 600
        client.socket.setsockopt(zmq.RCVTIMEO, 15000)
        client.socket.setsockopt(zmq.SNDTIMEO, 15000)
        client.socket.setsockopt(zmq.LINGER, 0)
    sim = client.require("sim")
    headless = bool(sim.getBoolParam(sim.boolparam_headless)) if hasattr(sim, "boolparam_headless") else False
    # Preparação e os dois voos compartilham a conexão; evita clientes
    # abandonados e nova introspecção da API durante a física.
    mission_client_factory = lambda **kwargs: client
    if sim.getSimulationState() != sim.simulation_stopped:
        raise RuntimeError("Pare a simulação antes da comparação.")
    # Preserva inclusive a cena aberta quando o usuário fornece outra cena.
    sim.saveScene((output / "scene_before.ttt").resolve().as_posix())
    if scene_path is None:
        app = Path(sim.getStringParam(sim.stringparam_application_path))
        # O replay também é uma cena com scripts. Prepara a coleta a partir
        # do template limpo, após preservar a cena que estava aberta.
        sim.loadScene((app / "system/dfltscn.ttt").as_posix())
        previous_tree_model = scene.DEFAULT_TREE_MODEL
        try:
            scene.DEFAULT_TREE_MODEL = app / "models/nature/Tree.ttm"
            prepared = scene.setup_scene(
                scenario, output / "comparison_scene.ttt",
                model_path=app / "models/robots/mobile/Quadcopter.ttm",
                host=host, port=port, client_factory=mission_client_factory,
            )
        finally:
            scene.DEFAULT_TREE_MODEL = previous_tree_model
        if not prepared.success:
            raise RuntimeError(prepared.error)
        scene_path = prepared.scene_path.resolve()
    rows = []
    by_label = dict(zip(labels, plans))
    for flight_index, label in enumerate(execution_order, 1):
        plan = by_label[label]
        _wait_stopped(sim)
        sim.loadScene(scene_path.as_posix())
        if time_step_s is not None:
            sim.setFloatParam(sim.floatparam_simulation_time_step, time_step_s)
            if abs(float(sim.getSimulationTimeStep()) - time_step_s) > 1e-8:
                raise RuntimeError("O simulador não aplicou o passo temporal solicitado.")
        if not headless:
            sim.adjustView(0, sim.getObject("/DefaultCamera"), 0)
        sim.setObjectSelection([])
        if not headless:
            sim.setBoolParam(sim.boolparam_infotext_visible, False)
        if executor == "lua":
            sim.setBoolParam(sim.boolparam_realtime_simulation, False)
        actual_time_step_s = float(sim.getSimulationTimeStep())
        print(f"VOO: {label} | faixas {plan.orientation} | sem vento", flush=True)
        flight_scenario = replace(scenario, scenario_id=label)
        # O executor não deve regenerar faixas: usa exatamente a rota comparada.
        run = run_wind_mission
        executor_options = {}
        if executor == "lua":
            from src.coppelia_benchmark import run_coverage_mission
            run = run_coverage_mission
            executor_options["disable_rendering"] = disable_rendering
        log = run(
            flight_scenario, case.terrain, plan.path.copy(), plan.path.copy(),
            scenario_path, host, port, client_factory=mission_client_factory,
            replanning_enabled=False,
            strict_safety=True,
            **executor_options,
        )
        with (log.output_directory / "metrics.csv").open(encoding="utf-8-sig") as stream:
            metrics = next(csv.DictReader(stream))
        energy = analyze_telemetry(log.output_directory / "telemetry.csv", energy_model,
                                   log.output_directory / "energy")
        try:
            coverage = analyze_executed_coverage(
                log.output_directory / "telemetry.csv", case,
                log.output_directory / "coverage", maximum_telemetry_gap_s,
            )
        except (ValueError, KeyError) as error:
            # Não transforma dados ausentes/corrompidos em uma missão coberta.
            coverage = measure_executed_coverage([], case, maximum_telemetry_gap_s)[0]
            coverage["coverage_error"] = str(error)
        eligibility = assess_flight(metrics, energy, coverage, minimum_executed_coverage)
        area_ha = coverage["executed_covered_area_m2"] / 10000
        rows.append({
            "method": label, "orientation": plan.orientation,
            "baseline_planner": BASELINE_VERSION,
            "planned_coverage_percent": plan.coverage_percent,
            "planned_normalized_cost": plan.normalized_cost,
            "planning_time_s": plan.planning_time_s,
            "planning_expanded_nodes": plan.expanded_nodes,
            "execution_order": flight_index,
            "collision_monitoring_required": True,
            "executor": "lua_physics_v1" if executor == "lua" else "python_rpc",
            "headless_collection": headless,
            "simulation_time_step_s": actual_time_step_s,
            "energy_model_sha256": energy_fingerprint,
            "run_directory": str(log.output_directory), **metrics, **energy,
            **coverage, **eligibility,
            "estimated_energy_wh_per_covered_ha": (
                energy["estimated_energy_wh"] / area_ha
                if area_ha > 0 and energy["energy_estimate_available"] else None),
        })
        with (output / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
            writer.writeheader()
            writer.writerows(rows)
        canonical_rows = sorted(rows, key=lambda row: labels.index(row["method"]))
        if canonical_rows[0]["method"] == labels[0]:
            export_energy_contrasts(canonical_rows, output / "energy_contrasts.csv")
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
    parser.add_argument("--energy-planning", action="store_true", help="Acrescenta seleção por Wh previstos e conexões refinadas; teste de desenvolvimento.")
    parser.add_argument("--minimum-executed-coverage", type=float, default=100.)
    parser.add_argument("--maximum-telemetry-gap", type=float, default=1.)
    parser.add_argument("--energy-model", type=Path, default=Path("configs/energy_reference.json"))
    parser.add_argument("--executor", choices=("python", "lua"), default="python")
    parser.add_argument("--disable-rendering", action="store_true", help="Acelera somente os voos; restaura a exibição ao final.")
    parser.add_argument("--time-step", type=float, help="Passo temporal do simulador; para estudo de resolução numérica.")
    args = parser.parse_args()
    output = args.output or Path("output/experiments") / datetime.now().strftime("coverage_%Y%m%d_%H%M%S_%f")
    result = compare_coverage_flights(args.scenario, output, args.scene, args.host,
                                     args.port, args.dry_run, energy_model_path=args.energy_model,
                                     ablation=args.ablation,
                                     energy_planning=args.energy_planning,
                                     minimum_executed_coverage=args.minimum_executed_coverage,
                                     maximum_telemetry_gap_s=args.maximum_telemetry_gap,
                                     executor=args.executor, disable_rendering=args.disable_rendering,
                                     time_step_s=args.time_step)
    print(f"{'Planos validados' if args.dry_run else 'Resultados'}: {result}")


if __name__ == "__main__":
    main()
