"""Resumo da trajetória medida, sem conexão com o CoppeliaSim."""

import argparse
import csv
import json
from math import dist, isfinite, sqrt
from pathlib import Path
from typing import Iterable, Mapping


def _flag(value: object) -> bool:
    if value in (True, 1, "True", "true", "1"):
        return True
    if value in (False, 0, "False", "false", "0"):
        return False
    raise ValueError(f"Indicador booleano inválido: {value!r}")


def summarize_telemetry(
    samples: Iterable[Mapping], climb_weight: float = 10,
) -> dict:
    """Mede apenas o intervalo entre primeira e última amostra.

    Duração das violações usa o estado da amostra anterior em cada intervalo.
    Erros médios e RMSE são por amostra. Não estima cobertura ou bateria.
    """
    if not isfinite(climb_weight) or climb_weight < 0:
        raise ValueError("Peso de subida deve ser finito e não negativo.")
    rows = list(samples)
    distance = gain = loss = violation_time = collision_time = 0.0
    positions, times, errors, clearances, violations, collisions = [], [], [], [], [], []
    for row in rows:
        position = tuple(float(row[f"drone_{axis}_m"]) for axis in "xyz")
        time = float(row["simulation_time_s"])
        error = float(row["tracking_error_m"])
        clearance = float(row["clearance_m"])
        if not all(isfinite(v) for v in (*position, time, error, clearance)) or error < 0:
            raise ValueError("Telemetria contém valores inválidos.")
        if times and time <= times[-1]:
            raise ValueError("Tempos da telemetria devem ser estritamente crescentes.")
        positions.append(position)
        times.append(time)
        errors.append(error)
        clearances.append(clearance)
        violations.append(_flag(row["clearance_violation"]))
        collisions.append(_flag(row["collision"]))
    for index in range(1, len(rows)):
        distance += dist(positions[index - 1], positions[index])
        dz = positions[index][2] - positions[index - 1][2]
        gain += max(0., dz)
        loss += max(0., -dz)
        interval = times[index] - times[index - 1]
        violation_time += interval * violations[index - 1]
        collision_time += interval * collisions[index - 1]
    return {
        "telemetry_samples": len(rows),
        "observed_duration_s": times[-1] - times[0] if times else 0.,
        "executed_distance_3d_m": distance,
        "executed_elevation_gain_m": gain,
        "executed_elevation_loss_m": loss,
        "executed_normalized_cost": distance + climb_weight * gain,
        "evaluation_climb_weight": climb_weight,
        "minimum_clearance_m": min(clearances) if clearances else None,
        "maximum_tracking_error_m": max(errors) if errors else None,
        "mean_tracking_error_m": sum(errors) / len(errors) if errors else None,
        "rmse_tracking_error_m": sqrt(sum(e * e for e in errors) / len(errors)) if errors else None,
        "clearance_violation_samples": sum(violations),
        "collision_samples": sum(collisions),
        "clearance_violation_duration_s": violation_time,
        "collision_duration_s": collision_time,
        "observed_safe": bool(rows) and not any(violations) and not any(collisions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--climb-weight", type=float, default=10)
    args = parser.parse_args()
    with args.telemetry.open(encoding="utf-8-sig", newline="") as stream:
        summary = summarize_telemetry(csv.DictReader(stream), args.climb_weight)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
