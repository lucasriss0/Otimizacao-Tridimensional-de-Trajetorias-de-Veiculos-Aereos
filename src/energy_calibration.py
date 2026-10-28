"""Ajusta eficiências e potência auxiliar com medições e voos de validação separados."""

import argparse
import csv
import hashlib
import itertools
import json
from dataclasses import replace
from math import isfinite
from pathlib import Path

import numpy as np

from src.energy import load_energy_model, model_manifest


FIELDS = ("flight_id", "split", "duration_s", "horizontal_speed_mps",
          "vertical_speed_mps", "voltage_v", "current_a")


def read_measurements(path, model):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Colunas obrigatórias: {', '.join(FIELDS)}")
        rows = []
        for number, raw in enumerate(reader, start=2):
            row = {"flight_id": raw["flight_id"].strip(), "split": raw["split"].strip()}
            if not row["flight_id"] or row["split"] not in ("train", "validation"):
                raise ValueError(f"Voo ou divisão inválida na linha {number}.")
            for name in FIELDS[2:]:
                try:
                    row[name] = float(raw[name])
                except (ValueError, TypeError) as error:
                    raise ValueError(f"Valor inválido na linha {number}: {name}") from error
                if not isfinite(row[name]):
                    raise ValueError(f"Valor não finito na linha {number}: {name}")
            if (row["duration_s"] <= 0 or row["voltage_v"] <= 0 or row["current_a"] <= 0
                    or row["horizontal_speed_mps"] < 0):
                raise ValueError(f"Duração, tensão, corrente ou velocidade inválida na linha {number}.")
            if (row["horizontal_speed_mps"] > model.maximum_horizontal_speed_mps
                    or abs(row["vertical_speed_mps"]) > model.maximum_vertical_speed_mps):
                raise ValueError(f"Medição fora do envelope do modelo na linha {number}.")
            if row["split"] == "train" and row["vertical_speed_mps"] < 0:
                raise ValueError("O ajuste de subida não aceita descidas no treino.")
            row["measured_power_w"] = row["voltage_v"] * row["current_a"]
            if not isfinite(row["measured_power_w"]):
                raise ValueError(f"Potência elétrica não finita na linha {number}.")
            rows.append(row)
    train = {row["flight_id"] for row in rows if row["split"] == "train"}
    validation = {row["flight_id"] for row in rows if row["split"] == "validation"}
    if not train or not validation:
        raise ValueError("Informe voos de treino e validação separados.")
    if train & validation:
        raise ValueError("Um mesmo flight_id não pode aparecer em treino e validação.")
    return rows


def _features(rows, model):
    return np.array([[model.horizontal_power_w(row["horizontal_speed_mps"]),
                      model.weight_n * max(0., row["vertical_speed_mps"]), 1.]
                     for row in rows], dtype=float)


def fit_parameters(rows, model):
    """Mínimos quadrados ponderados por duração, com limites físicos simples.

    P = a * P_horizontal + b * W * vz_positiva + c.
    a,b >= 1; c >= 0. Eficiências = 1/a e 1/b.
    Enumeração das faces do problema convexo com apenas três coeficientes.
    """
    if len(rows) < 3:
        raise ValueError("Faltam medições de treino para ajustar três parâmetros.")
    features = _features(rows, model)
    weights = np.sqrt(np.array([r["duration_s"] for r in rows]))
    design = features * weights[:, None]
    target = np.array([r["measured_power_w"] for r in rows]) * weights
    scales = np.linalg.norm(design, axis=0)
    if np.any(scales == 0):
        raise ValueError("Inclua voo horizontal em diferentes velocidades e subida no treino.")
    normalized = design / scales
    if np.linalg.matrix_rank(normalized) < 3:
        raise ValueError("Manobras insuficientes para identificar os parâmetros de forma independente.")
    condition = float(np.linalg.cond(normalized))
    if condition > 1e6:
        raise ValueError("Ajuste mal condicionado; amplie a diversidade das manobras.")
    lower = np.array([1., 1., 0.])
    residual_target = target - design @ lower
    candidates = []
    for free in itertools.product((False, True), repeat=3):
        indices = np.flatnonzero(free)
        extra = np.zeros(3)
        if len(indices):
            values = np.linalg.lstsq(normalized[:, indices], residual_target, rcond=None)[0]
            if np.any(values < -1e-8):
                continue
            extra[indices] = np.maximum(values, 0) / scales[indices]
        coefficients = lower + extra
        objective = float(np.sum((design @ coefficients - target) ** 2))
        candidates.append((objective, coefficients))
    _, coefficients = min(candidates, key=lambda pair: pair[0])
    fitted = replace(model, electrical_efficiency=float(1 / coefficients[0]),
                     climb_efficiency=float(1 / coefficients[1]),
                     auxiliary_power_w=float(coefficients[2]), calibration=None)
    return fitted, condition


def _evaluate(rows, model):
    features = _features(rows, model)
    predictions = features @ np.array([1 / model.electrical_efficiency,
                                       1 / model.climb_efficiency, model.auxiliary_power_w])
    errors = predictions - np.array([r["measured_power_w"] for r in rows])
    durations = np.array([r["duration_s"] for r in rows])
    measured = np.array([r["measured_power_w"] for r in rows])
    return predictions, {
        "duration_weighted_mae_w": float(np.average(np.abs(errors), weights=durations)),
        "duration_weighted_rmse_w": float(np.sqrt(np.average(errors ** 2, weights=durations))),
        "duration_weighted_mape_percent": float(100 * np.average(np.abs(errors) / measured, weights=durations)),
        "measured_energy_wh": float(np.sum(measured * durations) / 3600),
        "estimated_energy_wh": float(np.sum(predictions * durations) / 3600),
        "samples": len(rows), "flights": len({r["flight_id"] for r in rows}),
    }


def calibrate_energy(measurements, base_model, output, vehicle_id, data_kind,
                     maximum_validation_mape=10.):
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    if not vehicle_id.strip() or data_kind not in ("measured", "synthetic"):
        raise ValueError("Identifique o veículo e declare data_kind measured ou synthetic.")
    if not isfinite(maximum_validation_mape) or maximum_validation_mape <= 0:
        raise ValueError("Limite de validação deve ser finito e positivo.")
    model = load_energy_model(base_model)
    rows = read_measurements(measurements, model)
    train = [r for r in rows if r["split"] == "train"]
    validation = [r for r in rows if r["split"] == "validation"]
    fitted, condition = fit_parameters(train, model)
    _, train_metrics = _evaluate(train, fitted)
    _, validation_metrics = _evaluate(validation, fitted)
    _, base_metrics = _evaluate(validation, model)
    predictions, _ = _evaluate(rows, fitted)
    grouped = []
    for flight_id in dict.fromkeys(r["flight_id"] for r in rows):
        subset = [r for r in rows if r["flight_id"] == flight_id]
        _, stats = _evaluate(subset, fitted)
        grouped.append({"flight_id": flight_id, "split": subset[0]["split"], **stats})
    validation_flights = [r for r in grouped if r["split"] == "validation"]
    horizontal_range = [min(r["horizontal_speed_mps"] for r in train),
                        max(r["horizontal_speed_mps"] for r in train)]
    vertical_maximum = max(r["vertical_speed_mps"] for r in train)
    outside_training = sum(not (
        horizontal_range[0] <= r["horizontal_speed_mps"] <= horizontal_range[1]
        and 0 <= r["vertical_speed_mps"] <= vertical_maximum
    ) for r in validation)
    passed = (validation_metrics["duration_weighted_mape_percent"] <= maximum_validation_mape
              and outside_training == 0
              and all(r["duration_weighted_mape_percent"] <= maximum_validation_mape
                      for r in validation_flights))
    evidence = {
        "vehicle_id": vehicle_id, "data_kind": data_kind,
        "measurements_sha256": hashlib.sha256(measurements.read_bytes()).hexdigest(),
        "base_model_sha256": hashlib.sha256(base_model.read_bytes()).hexdigest(),
        "maximum_validation_mape_percent": maximum_validation_mape,
        "held_out_criterion_passed": passed,
        "real_measurements_declared": data_kind == "measured",
        "training_condition_number": condition,
        "training_horizontal_speed_range_mps": horizontal_range,
        "training_vertical_speed_range_mps": [0, vertical_maximum],
        "validation_outside_training_envelope_rows": outside_training,
        "training_flights": sorted({r["flight_id"] for r in train}),
        "validation_flights": sorted({r["flight_id"] for r in validation}),
        "fit_parameters": ["electrical_efficiency", "climb_efficiency", "auxiliary_power_w"],
        "scope": "Ajuste parcial condicionado à geometria/peso de referência. Não comprova calibração física completa nem economia real. Não alterar limiar após observar validação.",
    }
    payload = model_manifest(fitted)
    payload["calibration"] = evidence
    payload["parameter_fit_available"] = True
    output.mkdir(parents=True, exist_ok=False)
    (output / "measurements.csv").write_bytes(measurements.read_bytes())
    (output / "base_model.json").write_bytes(base_model.read_bytes())
    (output / "candidate_model.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"calibration": evidence, "train": train_metrics,
              "validation": validation_metrics, "base_model_validation": base_metrics}
    (output / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "predictions.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*rows[0], "estimated_power_w", "power_error_w"])
        writer.writeheader()
        writer.writerows({**row, "estimated_power_w": float(prediction),
                          "power_error_w": float(prediction - row["measured_power_w"])}
                         for row, prediction in zip(rows, predictions))
    with (output / "flight_validation.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(grouped[0]))
        writer.writeheader()
        writer.writerows(grouped)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    parser.add_argument("--base-model", type=Path, default=Path("configs/energy_reference.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--data-kind", choices=("measured", "synthetic"), required=True)
    parser.add_argument("--maximum-validation-mape", type=float, default=10.)
    args = parser.parse_args()
    report = calibrate_energy(args.measurements, args.base_model, args.output,
                              args.vehicle_id, args.data_kind, args.maximum_validation_mape)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
