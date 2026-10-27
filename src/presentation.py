"""Prepara a cena e executa uma demonstração no CoppeliaSim aberto."""

import argparse
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

import src.coppelia_scene as scene
from src.coppeliasim import prepare_scenario_route, run_wind_mission
from src.scenario import load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("configs/demo_wind.yaml"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    args = parser.parse_args()
    scenario = load_scenario(args.scenario)
    client = RemoteAPIClient(host=args.host, port=args.port)
    sim = client.require("sim")
    if sim.getSimulationState() != sim.simulation_stopped:
        raise RuntimeError("Pare a simulação no CoppeliaSim antes de iniciar a demonstração.")
    folder = Path("output/runs") / datetime.now().strftime("presentation_%Y%m%d_%H%M%S_%f")
    folder.mkdir(parents=True, exist_ok=False)
    sim.saveScene((folder / "scene_before.ttt").resolve().as_posix())
    app = Path(sim.getStringParam(sim.stringparam_application_path))
    scene.DEFAULT_TREE_MODEL = app / "models/nature/Tree.ttm"
    prepared = scene.setup_scene(
        scenario, folder / "presentation.ttt",
        model_path=app / "models/robots/mobile/Quadcopter.ttm",
        host=args.host, port=args.port,
    )
    if not prepared.success:
        raise RuntimeError(prepared.error)
    sim.adjustView(0, sim.getObject("/DefaultCamera"), 0)
    sim.setObjectSelection([])
    sim.setBoolParam(sim.boolparam_infotext_visible, False)
    sim.saveScene(prepared.scene_path.resolve().as_posix())
    print("Cena preparada. Acompanhe a janela do CoppeliaSim.", flush=True)
    print("Rota laranja: plano atual; cinza: plano anterior; seta azul: vento.", flush=True)
    terrain, targets, route = prepare_scenario_route(scenario)
    scenario = replace(scenario, output_root=folder)
    result = run_wind_mission(scenario, terrain, targets, route, args.scenario,
                             args.host, args.port)
    print(f"Alvos concluídos: {result.targets_completed}/{len(targets)}")
    print(f"Replanejamentos: {result.route_revisions}")
    print(f"Resultados: {result.output_directory}")
    print(f"Cena para reabrir: {prepared.scene_path}")
    if not result.success or result.error:
        raise RuntimeError(result.error or "Missão incompleta.")


if __name__ == "__main__":
    main()
