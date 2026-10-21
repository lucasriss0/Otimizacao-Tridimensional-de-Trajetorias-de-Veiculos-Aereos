"""Experimentos de planejamento sem simulador; custo normalizado, não joules."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from dataclasses import asdict, dataclass, replace
from math import floor, isfinite
from pathlib import Path
from time import perf_counter

import numpy as np

from src.astar import DistanceMode, Position
from src.coverage import (
    CoverageWindow, calculate_coverage_percent,
    generate_boustrophedon_targets, plan_targets,
)
from src.metrics import calculate_path_metrics
from src.obstacles import create_obstacle_mask
from src.scenario import load_scenario
from src.terrain import load_topodata


@dataclass(frozen=True)
class PlanningCase:
    name: str
    terrain: np.ndarray
    cell_x_m: float
    cell_y_m: float
    swath_m: float
    window: CoverageWindow
    obstacle_mask: np.ndarray
    launch: Position

    def validate(self) -> None:
        if self.terrain.ndim != 2 or not np.isfinite(self.terrain).all():
            raise ValueError("Terreno deve ser uma matriz 2D finita.")
        self.window.validate(self.terrain.shape)
        if self.obstacle_mask.shape != self.terrain.shape:
            raise ValueError("Máscara incompatível com o terreno.")
        if not all(isfinite(v) and v > 0 for v in (
            self.cell_x_m, self.cell_y_m, self.swath_m
        )):
            raise ValueError("Células e faixa devem ter dimensões positivas e finitas.")
        row, col = self.launch
        if not (0 <= row < self.terrain.shape[0] and 0 <= col < self.terrain.shape[1]):
            raise ValueError("Origem fora do terreno.")
        if self.obstacle_mask[self.launch]:
            raise ValueError("Origem bloqueada.")


@dataclass
class PlanningTrial:
    case: str
    method: str
    orientation: str
    planning_climb_weight: float
    evaluation_climb_weight: float
    success: bool
    eligible: bool
    selected: bool
    error: str | None
    coverage_percent: float
    horizontal_distance_m: float | None
    distance_3d_m: float | None
    elevation_gain_m: float | None
    normalized_cost: float | None
    planning_time_s: float
    expanded_nodes: int
    path: list[Position]


def _trial(
    case: PlanningCase, method: str, orientation: str, distance_mode: DistanceMode,
    planning_weight: float, evaluation_weight: float, minimum_coverage: float,
) -> PlanningTrial:
    started = perf_counter()
    perpendicular_cell = case.cell_y_m if orientation == "horizontal" else case.cell_x_m
    # Arredondar para cima pode deixar lacunas entre faixas.
    spacing = max(1, floor(case.swath_m / perpendicular_cell))
    targets = generate_boustrophedon_targets(
        case.terrain, spacing, case.window, orientation
    )
    targets = [target for target in targets if not case.obstacle_mask[target]]
    mission = [case.launch, *targets, case.launch]
    # Evita segmentos vazios, mantendo todos os alvos de aplicação obrigatórios.
    mission = [cell for i, cell in enumerate(mission) if i == 0 or cell != mission[i - 1]]
    result = plan_targets(
        case.terrain, mission, planning_weight, case.cell_x_m, case.cell_y_m,
        case.obstacle_mask, distance_mode=distance_mode,
    )
    elapsed = perf_counter() - started
    coverage = calculate_coverage_percent(
        case.terrain.shape, result.path, case.swath_m, case.cell_x_m,
        case.cell_y_m, case.obstacle_mask, case.window,
    )
    metrics = calculate_path_metrics(
        method, case.terrain, result.path, case.cell_x_m, case.cell_y_m,
        evaluation_weight, elapsed, result.expanded_nodes,
    ) if result.success else None
    eligible = result.success and bool(targets) and coverage + 1e-9 >= minimum_coverage
    error = result.error
    if result.success and not eligible:
        error = "Área sem alvos livres ou cobertura abaixo do mínimo exigido."
    return PlanningTrial(
        case.name, method, orientation, planning_weight, evaluation_weight,
        result.success, eligible, False, error, coverage,
        metrics.horizontal_distance_m if metrics else None,
        metrics.distance_3d_m if metrics else None,
        metrics.elevation_gain_m if metrics else None,
        metrics.normalized_energy_cost if metrics else None,
        elapsed, result.expanded_nodes, result.path,
    )


def compare_planners(
    case: PlanningCase, weights: tuple[float, ...] = (0, 3, 10, 20),
    evaluation_weight: float = 10, minimum_coverage: float = 100,
) -> list[PlanningTrial]:
    """Retorna candidatos e escolhas. Empates favorecem faixas horizontais.

    As referências têm orientação horizontal fixa. O método de seleção avalia
    horizontal e vertical pelo mesmo custo de avaliação e requisito de cobertura.
    Tempo e nós da linha selecionada incluem ambos os candidatos.
    """
    case.validate()
    if not weights or any(not isfinite(w) or w < 0 for w in weights):
        raise ValueError("Informe pesos de planejamento finitos e não negativos.")
    if not isfinite(evaluation_weight) or evaluation_weight < 0:
        raise ValueError("Peso de avaliação deve ser finito e não negativo.")
    if not isfinite(minimum_coverage) or not 0 < minimum_coverage <= 100:
        raise ValueError("Cobertura mínima deve estar em (0, 100].")
    trials = []
    for method, mode in (("horizontal_2d", "horizontal"), ("distance_3d", "3d")):
        trial = _trial(case, method, "horizontal", mode, 0, evaluation_weight, minimum_coverage)
        trial.selected = trial.eligible
        trials.append(trial)
    for weight in dict.fromkeys(weights):
        candidates = [
            _trial(case, "climb_candidate", orientation, "3d", weight,
                   evaluation_weight, minimum_coverage)
            for orientation in ("horizontal", "vertical")
        ]
        trials.extend(candidates)
        fixed = replace(candidates[0], method="climb_fixed", selected=candidates[0].eligible)
        trials.append(fixed)
        eligible = [trial for trial in candidates if trial.eligible]
        if eligible:
            winner = min(eligible, key=lambda trial: trial.normalized_cost)
            trials.append(replace(
                winner, method="climb_orientation", selected=True,
                planning_time_s=sum(t.planning_time_s for t in candidates),
                expanded_nodes=sum(t.expanded_nodes for t in candidates),
            ))
        else:
            trials.append(replace(
                candidates[0], method="climb_orientation", orientation="none",
                success=False, eligible=False, selected=False,
                error="Nenhuma orientação atende aos requisitos.", path=[],
                horizontal_distance_m=None, distance_3d_m=None,
                elevation_gain_m=None, normalized_cost=None,
                planning_time_s=sum(t.planning_time_s for t in candidates),
                expanded_nodes=sum(t.expanded_nodes for t in candidates),
            ))
    return trials


def synthetic_cases() -> list[PlanningCase]:
    """Conjunto fixo, incluindo terreno plano e os mesmos relevos com obstáculo."""
    rows, cols = np.indices((25, 25))
    surfaces = {
        "flat": np.zeros((25, 25)),
        "hill": 80 * np.exp(-((rows - 12) ** 2 + (cols - 12) ** 2) / 32),
        "ridge": np.broadcast_to(80 * np.exp(-((cols - 12) ** 2) / 8), (25, 25)).copy(),
    }
    cases = []
    for name, terrain in surfaces.items():
        for blocked in (False, True):
            mask = np.zeros(terrain.shape, dtype=bool)
            if blocked:
                mask[10:15, 10:15] = True
            cases.append(PlanningCase(
                f"{name}_{'obstacle' if blocked else 'clear'}", terrain,
                10, 10, 40, CoverageWindow(0, 0, 24, 24), mask, (0, 0),
            ))
    return cases


def case_from_scenario(path: Path) -> PlanningCase:
    scenario = load_scenario(path)
    spec = scenario.terrain
    terrain = load_topodata(
        spec.topodata, spec.size, spec.center_lat, spec.center_lon, spec.area_m
    ).elevation
    cell_x, cell_y = spec.area_m / terrain.shape[1], spec.area_m / terrain.shape[0]
    window = scenario.coverage.window or CoverageWindow(0, 0, *(
        dimension - 1 for dimension in terrain.shape
    ))
    mask = create_obstacle_mask(terrain.shape, list(scenario.obstacles), cell_x, cell_y)
    # Origem comum: primeira célula cultivável livre em ordem de linha/coluna.
    free = [
        (r, c) for r in range(window.row_start, window.row_end + 1)
        for c in range(window.col_start, window.col_end + 1) if not mask[r, c]
    ]
    if not free:
        raise ValueError("Cenário sem célula cultivável livre para origem.")
    return PlanningCase(scenario.scenario_id, terrain, cell_x, cell_y,
                        scenario.coverage.swath_m, window, mask, free[0])


def export_results(
    trials: list[PlanningTrial], cases: list[PlanningCase], destination: Path,
    configuration: dict,
) -> None:
    # Evita substituir evidências de uma execução anterior.
    destination.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, trial in enumerate(trials):
        row = asdict(trial)
        path = row.pop("path")
        route_file = f"route_{index:03d}.csv"
        row["route_file"] = route_file
        row["path_points"] = len(path)
        rows.append(row)
        with (destination / route_file).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["grid_row", "grid_column"])
            writer.writerows(path)
    with (destination / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _export_summary(trials, destination)
    _plot_results(trials, cases, destination)
    summaries = []
    for index, case in enumerate(cases):
        filename = f"case_{index:03d}.npz"
        np.savez_compressed(destination / filename, terrain=case.terrain, obstacle_mask=case.obstacle_mask)
        summaries.append({
            "name": case.name, "data_file": filename,
            "sha256": hashlib.sha256((destination / filename).read_bytes()).hexdigest(),
            "cell_x_m": case.cell_x_m, "cell_y_m": case.cell_y_m,
            "swath_m": case.swath_m, "window": asdict(case.window), "launch": case.launch,
        })
    repo = Path(__file__).resolve().parents[1]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
    manifest = {
        "configuration": configuration, "cases": summaries,
        "git_commit": revision.stdout.strip(), "git_dirty": bool(status.stdout.strip()),
        "python": platform.python_version(), "numpy": np.__version__,
        "dependencies": {name: version(name) for name in ("numpy", "rasterio", "PyYAML", "matplotlib")},
        "scope": "Planejamento sem vento, com retorno à origem e aplicação ao longo de toda a rota; custo não representa joules.",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _export_summary(trials: list[PlanningTrial], destination: Path) -> None:
    """Compara apenas missões viáveis; preserva empates e reduções negativas."""
    rows = []
    for trial in trials:
        if trial.method != "climb_orientation":
            continue
        for reference in ("horizontal_2d", "distance_3d", "climb_fixed"):
            baseline = next(t for t in trials if t.case == trial.case and t.method == reference
                            and (reference != "climb_fixed" or t.planning_climb_weight == trial.planning_climb_weight))
            comparable = trial.eligible and baseline.eligible
            reduction = None
            if comparable and baseline.normalized_cost > 0:
                reduction = 100 * (baseline.normalized_cost - trial.normalized_cost) / baseline.normalized_cost
            rows.append({
                "case": trial.case, "planning_climb_weight": trial.planning_climb_weight,
                "reference": reference, "comparable": comparable,
                "selected_orientation": trial.orientation,
                "reference_cost": baseline.normalized_cost,
                "selected_cost": trial.normalized_cost,
                "cost_reduction_percent": reduction,
            })
    with (destination / "summary.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_results(trials: list[PlanningTrial], cases: list[PlanningCase], destination: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    for metric, label in (("normalized_cost", "Custo normalizado (não joules)"),
                          ("elevation_gain_m", "Ganho de altitude (m)"),
                          ("distance_3d_m", "Distância 3D (m)")):
        figure, axes = plt.subplots(len(cases), 1, figsize=(8, 2.5 * len(cases)), squeeze=False)
        for axis, case in zip(axes[:, 0], cases):
            case_trials = [t for t in trials if t.case == case.name]
            for method, title in (("climb_fixed", "Faixas horizontais"),
                                  ("climb_orientation", "Escolha horizontal/vertical")):
                points = [t for t in case_trials if t.method == method]
                points.sort(key=lambda t: t.planning_climb_weight)
                axis.plot([t.planning_climb_weight for t in points],
                          [getattr(t, metric) if t.eligible else float("nan") for t in points],
                          marker="o", label=title)
            for method, title, style in (("horizontal_2d", "Referência 2D", "--"),
                                         ("distance_3d", "Referência 3D", ":")):
                reference = next(t for t in case_trials if t.method == method)
                if reference.eligible:
                    axis.axhline(getattr(reference, metric), linestyle=style, label=title)
            axis.set_title(case.name)
            axis.set_xlabel("Peso de subida no planejamento")
            axis.set_ylabel(label)
            axis.grid(alpha=0.2)
        axes[0, 0].legend(fontsize=8)
        figure.tight_layout()
        figure.savefig(destination / f"{metric}.png", dpi=140)
        plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, help="Acrescenta um cenário TOPODATA à suíte sintética.")
    parser.add_argument("--weights", type=float, nargs="+", default=[0, 3, 10, 20])
    parser.add_argument("--evaluation-weight", type=float, default=10)
    parser.add_argument("--minimum-coverage", type=float, default=100)
    parser.add_argument("--output", type=Path, required=True, help="Pasta nova para os resultados.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("A pasta de saída já existe; escolha outra para preservar os resultados.")
    cases = synthetic_cases()
    if args.scenario:
        cases.append(case_from_scenario(args.scenario))
    trials = []
    for case in cases:
        trials.extend(compare_planners(case, tuple(args.weights), args.evaluation_weight, args.minimum_coverage))
    export_results(trials, cases, args.output, {
        "weights": args.weights, "evaluation_weight": args.evaluation_weight,
        "minimum_coverage": args.minimum_coverage,
        "scenario": str(args.scenario) if args.scenario else None,
        "scenario_yaml": args.scenario.read_text(encoding="utf-8") if args.scenario else None,
        "orientations": ["horizontal", "vertical"],
    })
    for case in cases:
        selected = [t for t in trials if t.case == case.name and t.method == "climb_orientation"]
        print(f"{case.name}: {sum(t.eligible for t in selected)}/{len(selected)} escolhas viáveis")
    print(f"Resultados: {args.output}")


if __name__ == "__main__":
    main()
