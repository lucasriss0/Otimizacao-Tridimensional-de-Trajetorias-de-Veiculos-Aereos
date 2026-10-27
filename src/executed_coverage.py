"""Cobertura geométrica observada por segmentos da trajetória medida."""

import argparse
import csv
import json
from math import isfinite
from pathlib import Path

import numpy as np

from src.telemetry_metrics import _flag


def measure_executed_coverage(samples, case, maximum_gap_s=1.):
    """Marca centros de células a até meia faixa de segmentos ativos.

    Não limita posições ao grid nem liga trechos separados por aplicação
    desligada ou lacunas de telemetria. Não é medição de deposição de produto.
    """
    case.validate()
    if not isfinite(maximum_gap_s) or maximum_gap_s <= 0:
        raise ValueError("Intervalo máximo deve ser finito e positivo.")
    rows, cols = np.indices(case.terrain.shape)
    x = (cols - (case.terrain.shape[1] - 1) / 2) * case.cell_x_m
    y = ((case.terrain.shape[0] - 1) / 2 - rows) * case.cell_y_m
    cultivable = np.zeros(case.terrain.shape, dtype=bool)
    w = case.window
    cultivable[w.row_start:w.row_end + 1, w.col_start:w.col_end + 1] = True
    cultivable &= ~case.obstacle_mask
    covered = np.zeros_like(cultivable)
    radius_squared = (case.swath_m / 2) ** 2

    def mark(ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        fraction = np.clip(((x - ax) * dx + (y - ay) * dy) / length_squared, 0, 1) if length_squared else 0
        covered[:] |= ((x - ax - fraction * dx) ** 2 + (y - ay - fraction * dy) ** 2
                       <= radius_squared + 1e-9)

    previous = None
    sample_count = active_count = gaps = active_segments = 0
    active_time = 0.
    for sample in samples:
        t, px, py = (float(sample[key]) for key in
                      ("simulation_time_s", "drone_x_m", "drone_y_m"))
        if not all(isfinite(v) for v in (t, px, py)):
            raise ValueError("Posição ou tempo inválido na cobertura.")
        if "application_active" not in sample:
            raise ValueError("Telemetria sem application_active: não é possível inferir aplicação.")
        active = _flag(sample["application_active"])
        sample_count += 1
        active_count += int(active)
        if active:
            mark(px, py, px, py)
        if previous is not None:
            pt, ppx, ppy, was_active = previous
            dt = t - pt
            if dt <= 0:
                raise ValueError("Tempos devem ser estritamente crescentes.")
            if dt > maximum_gap_s:
                gaps += 1
            elif active and was_active:
                mark(ppx, ppy, px, py)
                active_segments += 1
                active_time += dt
        previous = t, px, py, active
    covered &= cultivable
    total = int(cultivable.sum())
    count = int(covered.sum())
    cell_area = case.cell_x_m * case.cell_y_m
    summary = {
        "executed_coverage_available": sample_count >= 2 and total > 0,
        "executed_coverage_percent": 100 * count / total if sample_count >= 2 and total else None,
        "executed_covered_cells": count,
        "cultivable_cells": total,
        "executed_covered_area_m2": count * cell_area,
        "cultivable_area_m2": total * cell_area,
        "application_active_samples": active_count,
        "application_observed_duration_s": active_time,
        "coverage_telemetry_gaps": gaps,
        "coverage_active_segments": active_segments,
        "coverage_maximum_gap_s": maximum_gap_s,
        "coverage_error": "",
    }
    return summary, covered, cultivable


def analyze_executed_coverage(path, case, output, maximum_gap_s=1.):
    samples = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            samples = list(csv.DictReader(stream))
    summary, covered, cultivable = measure_executed_coverage(samples, case, maximum_gap_s)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "coverage_masks.npz", covered=covered, cultivable=cultivable)
    (output / "coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return summary


def assess_flight(metrics, energy, coverage, minimum_coverage=100.):
    """Elegibilidade técnica de um voo para comparação; não valida o modelo físico."""
    if not isfinite(minimum_coverage) or not 0 < minimum_coverage <= 100:
        raise ValueError("Cobertura mínima deve estar em (0, 100].")
    reasons = []
    if not _flag(metrics.get("mission_completed_safely", False)):
        reasons.append("missao_incompleta_ou_insegura")
    if not coverage.get("executed_coverage_available", False):
        reasons.append("cobertura_indisponivel")
    elif coverage["executed_coverage_percent"] + 1e-9 < minimum_coverage:
        reasons.append("cobertura_insuficiente")
    if coverage.get("coverage_telemetry_gaps", 0):
        reasons.append("lacunas_na_telemetria")
    if not energy.get("energy_estimate_available", False):
        reasons.append("energia_indisponivel")
    if energy.get("energy_outside_envelope_intervals", 0):
        reasons.append("fora_do_envelope_energetico")
    return {
        "minimum_executed_coverage_percent": minimum_coverage,
        "energy_comparison_eligible": not reasons,
        "energy_comparison_exclusion_reasons": ";".join(reasons),
    }


def export_energy_contrasts(rows, output):
    """Mantém falhas no relatório, mas deixa redução em branco quando inválida."""
    reference = rows[0]
    contrasts = []
    for row in rows[1:]:
        comparable = reference["energy_comparison_eligible"] and row["energy_comparison_eligible"]
        ref_energy = reference.get("estimated_energy_wh")
        comparable = bool(comparable and ref_energy is not None and ref_energy > 0)
        contrasts.append({
            "reference": reference["method"], "proposed": row["method"],
            "comparable": comparable,
            "estimated_energy_reduction_percent": (
                100 * (ref_energy - row["estimated_energy_wh"]) / ref_energy if comparable else None),
            "reference_exclusion_reasons": reference["energy_comparison_exclusion_reasons"],
            "proposed_exclusion_reasons": row["energy_comparison_exclusion_reasons"],
            "energy_calibrated": False,
        })
    with output.open("w", newline="", encoding="utf-8-sig") as stream:
        fields = ["reference", "proposed", "comparable", "estimated_energy_reduction_percent",
                  "reference_exclusion_reasons", "proposed_exclusion_reasons", "energy_calibrated"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(contrasts)


def main():
    from src.planning_experiments import case_from_scenario
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-gap", type=float, default=1.)
    args = parser.parse_args()
    if not args.telemetry.is_file():
        parser.error("Telemetria não encontrada.")
    result = analyze_executed_coverage(args.telemetry, case_from_scenario(args.scenario),
                                       args.output, args.maximum_gap)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
