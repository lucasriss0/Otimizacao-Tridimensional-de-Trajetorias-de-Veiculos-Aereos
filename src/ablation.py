"""Separa as contribuições do relevo, da subida e da orientação."""

import argparse
import csv
import json
from dataclasses import asdict, replace
from math import dist, isfinite
from pathlib import Path
import subprocess

import numpy as np

from src.energy import estimate_energy, load_energy_model, model_manifest
from src.planning_experiments import case_from_scenario, compare_planners, synthetic_cases
from src.waypoints import grid_path_to_waypoints_3d


METHODS = (
    "referencia_2d", "distancia_3d", "somente_subida",
    "somente_orientacao", "proposta_completa",
)


def select_ablation_plans(case, climb_weight=10.):
    if not isfinite(climb_weight) or climb_weight <= 0:
        raise ValueError("Peso de subida deve ser finito e positivo para isolar seu efeito.")
    trials = compare_planners(case, (0., climb_weight), evaluation_weight=climb_weight)
    selectors = (
        ("horizontal_2d", 0.), ("distance_3d", 0.),
        ("climb_fixed", climb_weight), ("climb_orientation", 0.),
        ("climb_orientation", climb_weight),
    )
    return [replace(next(t for t in trials if t.method == method and
                         t.planning_climb_weight == weight), method=label)
            for label, (method, weight) in zip(METHODS, selectors)]


def ideal_samples(case, path, speed_mps):
    """Percurso ideal a velocidade 3D constante, sem controlador ou estabilização."""
    if not isfinite(speed_mps) or speed_mps <= 0:
        raise ValueError("Velocidade deve ser finita e positiva.")
    if not path:
        return []
    waypoints = grid_path_to_waypoints_3d(case.terrain, path, case.cell_x_m, case.cell_y_m, 60.)
    points = [(p.x_m, p.y_m, p.z_m) for p in waypoints]
    samples, time = [], 0.
    for index, point in enumerate(points):
        if index:
            length = dist(points[index - 1], point)
            if length == 0:
                continue
            time += length / speed_mps
        samples.append(dict(simulation_time_s=time, drone_x_m=point[0],
                            drone_y_m=point[1], drone_z_m=point[2]))
    return samples


def run_ablation(output, scenario_path=None, climb_weight=10., speed_mps=8.,
                 energy_model_path=Path("configs/energy_reference.json")):
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    if not isfinite(speed_mps) or speed_mps <= 0:
        raise ValueError("Velocidade deve ser finita e positiva.")
    cases = synthetic_cases()
    if scenario_path:
        cases.append(case_from_scenario(scenario_path))
    model = load_energy_model(energy_model_path)
    planned = [(case, select_ablation_plans(case, climb_weight)) for case in cases]
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for case_index, (case, plans) in enumerate(planned):
        np.savez_compressed(output / f"terrain_{case_index}.npz", terrain=case.terrain,
                            obstacle_mask=case.obstacle_mask)
        for plan in plans:
            samples = ideal_samples(case, plan.path, speed_mps) if plan.success else []
            energy, _ = estimate_energy(samples, model)
            row = asdict(plan)
            path = row.pop("path")
            row.update(energy)
            row["trajectory_kind"] = "ideal_constant_3d_speed"
            row["ideal_duration_s"] = samples[-1]["simulation_time_s"] if samples else None
            row["route_file"] = f"route_{case_index}_{plan.method}.csv"
            rows.append(row)
            with (output / row["route_file"]).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["grid_row", "grid_column"])
                writer.writerows(path)
    with (output / "ablation.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    contrasts = []
    for case in cases:
        subset = {r["method"]: r for r in rows if r["case"] == case.name}
        for reference, proposed, effect in (
            ("referencia_2d", "distancia_3d", "distancia_3d"),
            ("distancia_3d", "somente_subida", "subida_faixas_fixas"),
            ("distancia_3d", "somente_orientacao", "orientacao_sem_subida"),
            ("somente_subida", "proposta_completa", "orientacao_com_subida"),
            ("somente_orientacao", "proposta_completa", "subida_com_orientacao"),
            ("referencia_2d", "proposta_completa", "efeito_total"),
        ):
            a, b = subset[reference], subset[proposed]
            comparable = a["eligible"] and b["eligible"] and a["energy_estimate_available"] and b["energy_estimate_available"]
            contrasts.append({"case": case.name, "effect": effect,
                "reference": reference, "proposed": proposed, "comparable": comparable,
                "estimated_energy_reduction_percent": (
                    100 * (a["estimated_energy_wh"] - b["estimated_energy_wh"]) / a["estimated_energy_wh"]
                    if comparable else None),
                "outside_energy_envelope": bool(a["energy_outside_envelope_intervals"] or b["energy_outside_envelope_intervals"]),
            })
    with (output / "effects.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(contrasts[0]))
        writer.writeheader()
        writer.writerows(contrasts)
    (output / "protocol.json").write_text(json.dumps({
        "climb_weight": climb_weight, "speed_mps": speed_mps,
        "energy_model": model_manifest(model), "methods": METHODS,
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
                                     capture_output=True, text=True).stdout.strip(),
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=Path(__file__).resolve().parents[1],
                                         capture_output=True, text=True).stdout.strip()),
        "cases": [{"name": c.name, "terrain_file": f"terrain_{i}.npz",
                   "cell_x_m": c.cell_x_m, "cell_y_m": c.cell_y_m,
                   "swath_m": c.swath_m, "launch": c.launch, "window": asdict(c.window)}
                  for i, c in enumerate(cases)],
        "source_scenario_yaml": scenario_path.read_text(encoding="utf-8") if scenario_path else None,
        "scope": "Trajetórias ideais, sem vento, controlador, curvas ou acelerações. Não é resultado de voo ou bateria medida.",
        "orientation_selection": "Mesmo custo normalizado de avaliação para os candidatos com peso 0 e com subida; energia usada somente após seleção.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--climb-weight", type=float, default=10.)
    parser.add_argument("--speed", type=float, default=8.)
    parser.add_argument("--energy-model", type=Path, default=Path("configs/energy_reference.json"))
    args = parser.parse_args()
    print(run_ablation(args.output, args.scenario, args.climb_weight, args.speed, args.energy_model))


if __name__ == "__main__":
    main()
