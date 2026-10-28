"""Energia estimada de referência; não é telemetria elétrica de bateria.

Voo horizontal: Zeng, Xu e Zhang, arXiv:1804.02238, equações (6) e (61).
Subida: extensão simplificada W * ganho de altura / eficiência, deste projeto.
"""

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from math import hypot, isfinite, pi, sqrt
from pathlib import Path
from typing import Iterable, Mapping


SOURCE = "https://arxiv.org/abs/1804.02238"


@dataclass(frozen=True)
class EnergyModel:
    weight_n: float = 100.
    air_density_kg_m3: float = 1.225
    rotor_radius_m: float = .5
    tip_speed_mps: float = 200.
    rotor_solidity: float = .05
    fuselage_drag_ratio: float = .3
    blade_profile_drag: float = .012
    induced_correction: float = .1
    electrical_efficiency: float = .8
    climb_efficiency: float = .8
    auxiliary_power_w: float = 0.
    maximum_horizontal_speed_mps: float = 60.
    maximum_vertical_speed_mps: float = 5.
    calibration: dict | None = None

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "calibration":
                continue
            if isinstance(value, bool) or not isfinite(value):
                raise ValueError(f"Parâmetro energético inválido: {name}")
            if value < 0:
                raise ValueError(f"Parâmetro energético negativo: {name}")
            if value == 0 and name not in ("auxiliary_power_w", "induced_correction", "fuselage_drag_ratio"):
                raise ValueError(f"Parâmetro energético deve ser positivo: {name}")
        if self.electrical_efficiency > 1 or self.climb_efficiency > 1 or self.rotor_solidity > 1:
            raise ValueError("Eficiências e solidez devem estar em (0, 1].")

    def horizontal_power_w(self, speed_mps: float) -> float:
        """Potência mecânica do modelo de voo horizontal estacionário."""
        if not isfinite(speed_mps) or speed_mps < 0:
            raise ValueError("Velocidade deve ser finita e não negativa.")
        area = pi * self.rotor_radius_m ** 2
        p0 = self.blade_profile_drag / 8 * self.air_density_kg_m3 * self.rotor_solidity * area * self.tip_speed_mps ** 3
        induced = (1 + self.induced_correction) * self.weight_n ** 1.5 / sqrt(2 * self.air_density_kg_m3 * area)
        v0 = sqrt(self.weight_n / (2 * self.air_density_kg_m3 * area))
        x = speed_mps ** 2 / (2 * v0 ** 2)
        # Forma equivalente estável de sqrt(sqrt(1 + x²) - x).
        induced_factor = sqrt(1 / (hypot(1, x) + x))
        return (p0 * (1 + 3 * speed_mps ** 2 / self.tip_speed_mps ** 2)
                + induced * induced_factor
                + .5 * self.fuselage_drag_ratio * self.air_density_kg_m3
                * self.rotor_solidity * area * speed_mps ** 3)


def load_energy_model(path: Path) -> EnergyModel:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("model") != "zeng_level_plus_climb_v1":
        raise ValueError("Modelo energético desconhecido.")
    calibration = raw.get("calibration")
    if calibration is not None and not isinstance(calibration, dict):
        raise ValueError("Metadados de calibração inválidos.")
    if calibration is not None and calibration.get("held_out_criterion_passed") is not True:
        raise ValueError("O candidato energético não passou no critério de validação separado.")
    return EnergyModel(**raw["parameters"], calibration=calibration)


def model_manifest(model: EnergyModel) -> dict:
    parameters = asdict(model)
    calibration = parameters.pop("calibration")
    return {
        "model": "zeng_level_plus_climb_v1", "parameters": parameters,
        "source": SOURCE, "calibrated_for_project_drone": False,
        "parameter_fit_available": calibration is not None,
        "calibration": calibration,
        "scope": "Referência teórica de voo horizontal; extensão de subida e eficiências são hipóteses do projeto. Não é bateria medida nem modelo 3D calibrado.",
    }


def estimate_energy(samples: Iterable[Mapping], model: EnergyModel) -> tuple[dict, list[dict]]:
    positions, times = [], []
    for sample in samples:
        t = float(sample["simulation_time_s"])
        position = tuple(float(sample[f"drone_{axis}_m"]) for axis in "xyz")
        if not all(isfinite(value) for value in (t, *position)):
            raise ValueError("Posição ou tempo não finito na telemetria.")
        if times and t <= times[-1]:
            raise ValueError("Tempos devem ser estritamente crescentes.")
        times.append(t)
        positions.append(position)
    intervals = []
    horizontal_j = climb_j = auxiliary_j = 0.
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        start, end = positions[index - 1], positions[index]
        horizontal_speed = hypot(end[0] - start[0], end[1] - start[1]) / dt
        vertical_speed = (end[2] - start[2]) / dt
        level_power = model.horizontal_power_w(horizontal_speed) / model.electrical_efficiency
        climb_power = model.weight_n * max(0., vertical_speed) / model.climb_efficiency
        power = level_power + climb_power + model.auxiliary_power_w
        outside_calibration = False
        if model.calibration is not None:
            horizontal_range = model.calibration["training_horizontal_speed_range_mps"]
            vertical_range = model.calibration["training_vertical_speed_range_mps"]
            outside_calibration = not (
                horizontal_range[0] - 1e-9 <= horizontal_speed <= horizontal_range[1] + 1e-9
                and vertical_range[0] - 1e-9 <= vertical_speed <= vertical_range[1] + 1e-9
            )
        horizontal_j += level_power * dt
        climb_j += climb_power * dt
        auxiliary_j += model.auxiliary_power_w * dt
        intervals.append({
            "start_time_s": times[index - 1], "end_time_s": times[index],
            "horizontal_speed_mps": horizontal_speed, "vertical_speed_mps": vertical_speed,
            "estimated_power_w": power,
            "cumulative_estimated_energy_wh": (horizontal_j + climb_j + auxiliary_j) / 3600,
            "outside_reference_envelope": (
                horizontal_speed > model.maximum_horizontal_speed_mps
                or abs(vertical_speed) > model.maximum_vertical_speed_mps
                or outside_calibration
            ),
            "outside_calibration_envelope": outside_calibration,
        })
    available = bool(intervals)
    duration = times[-1] - times[0] if available else 0.
    total = horizontal_j + climb_j + auxiliary_j
    summary = {
        "energy_estimate_available": available,
        "estimated_energy_wh": total / 3600 if available else None,
        "estimated_level_energy_wh": horizontal_j / 3600 if available else None,
        "estimated_climb_energy_wh": climb_j / 3600 if available else None,
        "estimated_auxiliary_energy_wh": auxiliary_j / 3600 if available else None,
        "estimated_mean_power_w": total / duration if available else None,
        "energy_observed_duration_s": duration,
        "energy_samples": len(times),
        "energy_outside_envelope_intervals": sum(row["outside_reference_envelope"] for row in intervals),
        "energy_outside_calibration_envelope_intervals": sum(row["outside_calibration_envelope"] for row in intervals),
        "energy_model": "zeng_level_plus_climb_v1",
        "energy_calibrated": False,
        "energy_parameter_fit_available": model.calibration is not None,
    }
    return summary, intervals


def analyze_telemetry(path: Path, model: EnergyModel, output: Path) -> dict:
    """Exporta estimativa e série temporal sem alterar a telemetria original."""
    rows = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    summary, intervals = estimate_energy(rows, model)
    output.mkdir(parents=True, exist_ok=False)
    (output / "energy_model.json").write_text(json.dumps(model_manifest(model), ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "energy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if intervals:
        with (output / "energy_timeseries.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(intervals[0]))
            writer.writeheader()
            writer.writerows(intervals)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--model", type=Path, default=Path("configs/energy_reference.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.telemetry.is_file():
        parser.error("Arquivo de telemetria não encontrado.")
    summary = analyze_telemetry(args.telemetry, load_energy_model(args.model), args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
