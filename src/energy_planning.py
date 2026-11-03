"""Protótipo de desenvolvimento: conexões contínuas e seleção por Wh previstos.

O avaliador e os parâmetros de voo permanecem externos ao planejador. A previsão
usa velocidade 3D constante; não antecipa erros do controlador nem mede bateria.
"""

from dataclasses import dataclass, replace
from math import ceil, hypot
from time import perf_counter

from src.ablation import ideal_samples
from src.conventional import GeometricConnections, plan_conventional
from src.coverage import generate_boustrophedon_targets
from src.energy import estimate_energy
from src.executed_coverage import measure_executed_coverage
from src.metrics import calculate_path_metrics
from src.planning_experiments import compare_planners
from src.terrain import elevation_at


ENERGY_PLANNER_VERSION = "energy_candidates_v1"


@dataclass
class EnergySelection:
    plan: object
    selected_candidate: str
    candidates: list[dict]

    def manifest(self):
        return {
            "version": ENERGY_PLANNER_VERSION,
            "selected_candidate": self.selected_candidate,
            "fallback_selected": self.selected_candidate == "convencional",
            "selection_metric": "estimated_energy_wh_on_ideal_3d_constant_speed_path",
            "candidates": self.candidates,
            "scope": "Desenvolvimento nos recortes conhecidos; não é teste independente nem bateria medida. Refinamento geométrico e orientação não são ganhos exclusivos do A*.",
        }


def _energy(case, path, model, speed):
    return estimate_energy(ideal_samples(case, path, speed), model)[0]


def _mission(case, orientation):
    from math import floor
    cell = case.cell_y_m if orientation == "horizontal" else case.cell_x_m
    spacing = max(1, floor((case.stripe_spacing_m or case.swath_m) / cell))
    targets = generate_boustrophedon_targets(case.terrain, spacing, case.window, orientation)
    targets = [p for p in targets if not case.obstacle_mask[p]]
    mission = [case.launch, *targets, case.launch]
    return [p for i, p in enumerate(mission) if i == 0 or p != mission[i-1]]


def _sample_line(case, a, b):
    length = hypot((b[0]-a[0])*case.cell_y_m, (b[1]-a[1])*case.cell_x_m)
    steps = max(1, ceil(length/min(case.cell_x_m, case.cell_y_m)))
    return [tuple(float(x+(y-x)*i/steps) for x, y in zip(a, b))
            for i in range(steps)] + [tuple(b)]


def refine_connections(case, plan, model, speed, connector, geometric=False):
    """Preserva todos os alvos obrigatórios, na ordem, inclusive ida e retorno.

    Atalhos só substituem uma conexão se forem visíveis e não aumentarem seus
    Wh ideais. Opcionalmente testa também o desvio contínuo de menor distância
    XY, usando a mesma geometria de exclusão da referência.
    """
    mission = _mission(case, plan.orientation)
    indices, cursor = [], 0
    for i, target in enumerate(mission):
        cursor = len(plan.path)-1 if i == len(mission)-1 else plan.path.index(target, cursor)
        indices.append(cursor)
    result = [plan.path[0]]
    for first, last in zip(indices, indices[1:]):
        original = plan.path[first:last+1]
        shortened, current = [original[0]], 0
        while current < len(original)-1:
            chosen, following = [original[current], original[current+1]], current+1
            for end in range(len(original)-1, current+1, -1):
                if not connector.visible(original[current], original[end]):
                    continue
                candidate = _sample_line(case, original[current], original[end])
                if (_energy(case, candidate, model, speed)["estimated_energy_wh"]
                        <= _energy(case, original[current:end+1], model, speed)["estimated_energy_wh"] + 1e-10):
                    chosen, following = candidate, end
                    break
            shortened.extend(chosen[1:])
            current = following
        options = [original, shortened]
        if geometric:
            vertices, _ = connector.connect(original[0], original[-1])
            continuous = [vertices[0]]
            for a, b in zip(vertices, vertices[1:]):
                continuous.extend(_sample_line(case, a, b)[1:])
            options.append(continuous)
        selected = min(options, key=lambda p: _energy(case, p, model, speed)["estimated_energy_wh"])
        result.extend(selected[1:])
    return result


def _sampled_clearance(case, path, clearance):
    minimum = clearance
    for a, b in zip(path, path[1:]):
        za, zb = elevation_at(case.terrain, a), elevation_at(case.terrain, b)
        steps = max(1, ceil(hypot(b[0]-a[0], b[1]-a[1])*4))
        for i in range(steps+1):
            t = i/steps
            point = tuple(x+(y-x)*t for x, y in zip(a, b))
            minimum = min(minimum, za+(zb-za)*t+clearance-elevation_at(case.terrain, point))
    return minimum


def select_energy_plan(case, model, speed_mps, climb_weight=10., physical_window=None,
                       clearance_m=100., minimum_clearance_m=55.):
    """Avalia o conjunto fixo de candidatos; empates preservam a referência."""
    started = perf_counter()
    reference = plan_conventional(case, climb_weight)
    trials = compare_planners(case, (0., climb_weight), evaluation_weight=climb_weight)
    connector = GeometricConnections(case.obstacle_mask, case.cell_x_m, case.cell_y_m)
    candidates = [("convencional", "convencional", reference)]
    expanded = reference.expanded_nodes
    for trial in trials:
        if trial.method != "climb_candidate" or not trial.eligible:
            continue
        expanded += trial.expanded_nodes
        name = f"astar_peso_{trial.planning_climb_weight:g}_{trial.orientation}"
        candidates.append((name, "astar", trial))
        for suffix, geometric in (("atalhos", False), ("geometria", True)):
            path = refine_connections(case, trial, model, speed_mps, connector, geometric)
            candidates.append((f"{name}_{suffix}", f"astar_{suffix}", replace(trial, path=path)))
    scored, eligible = [], []
    for name, family, trial in candidates:
        summary = _energy(case, trial.path, model, speed_mps) if trial.eligible else {}
        samples = [dict(simulation_time_s=i, drone_x_m=(p[1]-(case.terrain.shape[1]-1)/2)*case.cell_x_m,
                        drone_y_m=((case.terrain.shape[0]-1)/2-p[0])*case.cell_y_m,
                        application_active=True) for i, p in enumerate(trial.path)]
        coverage = measure_executed_coverage(samples, case)[0]["executed_coverage_percent"] or 0.
        within = physical_window is None or all(
            physical_window.row_start <= r <= physical_window.row_end
            and physical_window.col_start <= c <= physical_window.col_end for r, c in trial.path)
        visible = all(connector.visible(a, b) for a, b in zip(trial.path, trial.path[1:]))
        clearance = _sampled_clearance(case, trial.path, clearance_m)
        valid = (trial.eligible and coverage+1e-9 >= 100 and within and visible
                 and clearance >= minimum_clearance_m
                 and summary.get("energy_estimate_available", False)
                 and summary.get("energy_outside_envelope_intervals", 1) == 0)
        scored.append({"candidate": name, "family": family, "orientation": trial.orientation,
                       "eligible": bool(valid), "planned_coverage_percent": coverage,
                       "within_physical_terrain": within, "obstacle_segments_visible": visible,
                       "minimum_sampled_planned_clearance_m": clearance,
                       **summary})
        if valid:
            eligible.append((summary["estimated_energy_wh"], len(scored)-1, trial))
    if not eligible:
        raise ValueError("Nenhum candidato energético seguro cobre a missão no envelope previsto.")
    _, index, winner = min(eligible, key=lambda item: (item[0], item[1]))
    metrics = calculate_path_metrics("energy_selected", case.terrain, winner.path,
        case.cell_x_m, case.cell_y_m, climb_weight, perf_counter()-started, expanded)
    plan = replace(winner, method="energy_selected", selected=True,
        coverage_percent=scored[index]["planned_coverage_percent"],
        horizontal_distance_m=metrics.horizontal_distance_m,
        distance_3d_m=metrics.distance_3d_m, elevation_gain_m=metrics.elevation_gain_m,
        normalized_cost=metrics.normalized_energy_cost, planning_time_s=perf_counter()-started,
        expanded_nodes=expanded)
    return EnergySelection(plan, scored[index]["candidate"], scored)
