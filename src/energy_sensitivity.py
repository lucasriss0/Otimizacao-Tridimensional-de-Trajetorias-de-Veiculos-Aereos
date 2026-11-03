"""Sensibilidade de energia estimada sobre os mesmos voos já registrados."""

import argparse
import csv
from dataclasses import replace
import hashlib
import io
from itertools import product
import json
from math import isfinite
from pathlib import Path
from statistics import mean

from src.energy import EnergyModel, estimate_energy, model_manifest


# Grade fixa, definida no código antes da leitura de qualquer resultado.
WEIGHT_FACTORS = (.8, 1., 1.2)
ELECTRICAL_EFFICIENCY_FACTORS = (.8, 1., 1.2)
AUXILIARY_ADDITIONS_W = (0., 100.)
GRID_VERSION = "fixed_theoretical_v1"
WARNING = ("Sensibilidade de hipóteses teóricas sobre trajetórias do simulador; "
           "não calibra o drone e não comprova economia real de bateria.")


def sensitivity_configurations():
    """Dezoito modelos teóricos comuns aos dois métodos, sem ajuste aos dados."""
    base = EnergyModel()
    configurations = []
    for index, (weight, efficiency, auxiliary) in enumerate(product(
            WEIGHT_FACTORS, ELECTRICAL_EFFICIENCY_FACTORS, AUXILIARY_ADDITIONS_W)):
        model = replace(base, weight_n=base.weight_n * weight,
                        electrical_efficiency=base.electrical_efficiency * efficiency,
                        auxiliary_power_w=base.auxiliary_power_w + auxiliary,
                        climb_efficiency=.8, calibration=None)
        configurations.append({
            "configuration_id": f"theory_{index:02d}",
            "weight_factor": weight, "electrical_efficiency_factor": efficiency,
            "auxiliary_addition_w": auxiliary, "model": model_manifest(model),
        })
    return configurations


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _telemetry_path(raw, root):
    if not raw:
        raise FileNotFoundError("Voo sem run_directory no benchmark.")
    folder = Path(raw)
    project = Path(__file__).resolve().parents[1]
    candidates = (folder, root / folder, root.parent / folder, project / folder)
    for candidate in candidates:
        path = candidate / "telemetry.csv"
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"Telemetria não encontrada para {raw}.")


def _collect_pairs(report, root):
    """Aceita somente pares elegíveis; revalida observação e limites de velocidade."""
    pairs = report.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("O benchmark deve conter uma lista de pares.")
    minimum = _finite((report.get("benchmark_definition") or {}).get(
        "minimum_executed_coverage_percent", 100.))
    if minimum is None or not 0 < minimum <= 100:
        raise ValueError("Limiar de cobertura inválido no benchmark.")
    selected, excluded, telemetry_sources, seen = [], [], {}, set()
    for pair in pairs:
        case = str(pair["geographic_case"])
        repetition = pair["repetition"]
        if (isinstance(repetition, bool) or not isinstance(repetition, int)
                or repetition < 1):
            raise ValueError("Repetição deve ser um inteiro positivo.")
        key = case, repetition
        if key in seen:
            raise ValueError(f"Par duplicado no benchmark: {key}.")
        seen.add(key)
        record = {"geographic_case": case, "repetition": repetition}
        if pair.get("comparable") is not True:
            excluded.append({**record, "reason": "par_inelegivel_no_benchmark"})
            continue
        try:
            if any(pair.get(name) for name in ("reference_exclusion_reasons",
                    "proposed_exclusion_reasons", "pair_exclusion_reasons")):
                raise ValueError("Par comparável contém motivos de exclusão.")
            flights = []
            for side in ("reference", "proposed"):
                flight = pair.get(side)
                if not isinstance(flight, dict) or flight.get("mission_completed_safely") is not True:
                    raise ValueError(f"Conclusão segura não confirmada: {side}.")
                coverage = _finite(flight.get("executed_coverage_percent"))
                if coverage is None or not minimum - 1e-9 <= coverage <= 100. + 1e-9:
                    raise ValueError(f"Cobertura inválida ou insuficiente: {side}.")
                if str(flight.get("trajectory_kind", "")).startswith("ideal"):
                    raise ValueError("Trajetórias ideais não são voos registrados.")
                path = _telemetry_path(flight.get("run_directory"), root)
                raw = path.read_bytes()
                sha256 = hashlib.sha256(raw).hexdigest()
                if flight.get("telemetry_sha256") and flight["telemetry_sha256"] != sha256:
                    raise ValueError(f"Hash da telemetria difere do benchmark: {side}.")
                samples = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                telemetry_sources[str(path)] = {"path": str(path), "sha256": sha256,
                                                "samples": len(samples)}
                # Os limites são os mesmos em toda a grade; não se ampliam
                # para acomodar uma trajetória que excedeu a referência.
                summary, _ = estimate_energy(samples, EnergyModel())
                if not summary["energy_estimate_available"]:
                    raise ValueError(f"Observação insuficiente para energia: {side}.")
                if summary["energy_outside_envelope_intervals"]:
                    raise ValueError(f"Trajetória fora do envelope energético: {side}.")
                flights.append({"method": flight["method"], "samples": samples,
                                "path": str(path), "sha256": sha256,
                                "parameter_fit_available": flight.get("energy_parameter_fit_available") is True})
            if flights[0]["method"] == flights[1]["method"]:
                raise ValueError("O par deve conter métodos distintos.")
            if any(report.get(f"{side}_method") is not None
                   and report[f"{side}_method"] != flight["method"]
                   for side, flight in zip(("reference", "proposed"), flights)):
                raise ValueError("Métodos do par diferem dos métodos declarados no benchmark.")
            selected.append({**record, "reference": flights[0], "proposed": flights[1]})
        except (ValueError, KeyError, TypeError, OverflowError, OSError, UnicodeError) as error:
            excluded.append({**record, "reason": "telemetria_ou_par_invalido", "error": str(error)})
    return selected, excluded, list(telemetry_sources.values())


def _write_csv(path, rows, empty_fields):
    fields = list(dict.fromkeys(key for row in rows for key in row)) or empty_fields
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plot(configurations, summaries, output, analyzed_pairs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    values = {row["configuration_id"]: row["case_mean_estimated_energy_reduction_percent"]
              for row in summaries}
    available = [value for value in values.values() if value is not None]
    limit = max([abs(value) for value in available] + [.01])
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8), constrained_layout=True)
    for ax, auxiliary in zip(axes, AUXILIARY_ADDITIONS_W):
        matrix = np.full((len(WEIGHT_FACTORS), len(ELECTRICAL_EFFICIENCY_FACTORS)), np.nan)
        for config in configurations:
            if config["auxiliary_addition_w"] == auxiliary:
                value = values[config["configuration_id"]]
                if value is not None:
                    matrix[WEIGHT_FACTORS.index(config["weight_factor"]),
                           ELECTRICAL_EFFICIENCY_FACTORS.index(config["electrical_efficiency_factor"])] = value
        image = ax.imshow(np.ma.masked_invalid(matrix), cmap="RdYlGn", vmin=-limit, vmax=limit)
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                value = matrix[row, column]
                ax.text(column, row, f"{value:+.3f}%" if isfinite(value) else "sem pares",
                        ha="center", va="center", fontsize=9)
        ax.set_xticks(range(3), ["0,64", "0,80", "0,96"])
        ax.set_yticks(range(3), ["80", "100", "120"])
        ax.set_xlabel("Eficiência elétrica teórica")
        ax.set_ylabel("Peso teórico (N)")
        ax.set_title(f"Potência auxiliar: {auxiliary:.0f} W")
    fig.colorbar(image, ax=axes, label="Redução estimada média por recorte (%)", shrink=.85)
    fig.suptitle(f"Sensibilidade nas mesmas trajetórias · {analyzed_pairs} pares analisados")
    fig.supxlabel("Positivo favorece a proposta; negativo indica aumento. Hipóteses teóricas, sem prova de bateria real.", fontsize=8)
    fig.savefig(output / "energy_sensitivity.png", dpi=180)
    fig.savefig(output / "energy_sensitivity.svg")
    plt.close(fig)


def analyze_energy_sensitivity(source: Path, output: Path) -> Path:
    """Reestima os mesmos voos, sem selecionar planos nem alterar o benchmark."""
    # Constrói toda a grade antes de ler os resultados: não seleciona
    # parâmetros a partir de ganhos observados.
    configurations = sensitivity_configurations()
    source, output = Path(source).resolve(), Path(output).resolve()
    source = source / "benchmark.json" if source.is_dir() else source
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    raw = source.read_bytes()
    report = json.loads(raw.decode("utf-8"))
    if report.get("evidence_kind") != "simulator_trajectory_with_estimated_energy":
        raise ValueError("A sensibilidade exige benchmark de trajetórias executadas no simulador.")
    pairs, excluded, sources = _collect_pairs(report, source.parent)
    pair_rows, case_rows, configuration_rows = [], [], []
    for config in configurations:
        model = EnergyModel(**config["model"]["parameters"])
        reductions_by_case = {}
        for pair in pairs:
            energy = {}
            for side in ("reference", "proposed"):
                metrics, _ = estimate_energy(pair[side]["samples"], model)
                if not metrics["energy_estimate_available"] or metrics["energy_outside_envelope_intervals"]:
                    raise ValueError("A grade não pode aceitar observação insuficiente ou ampliar o envelope.")
                energy[side] = metrics["estimated_energy_wh"]
            reduction = 100 * (energy["reference"] - energy["proposed"]) / energy["reference"]
            reductions_by_case.setdefault(pair["geographic_case"], []).append(reduction)
            pair_rows.append({"configuration_id": config["configuration_id"],
                              "geographic_case": pair["geographic_case"], "repetition": pair["repetition"],
                              "reference_method": pair["reference"]["method"],
                              "proposed_method": pair["proposed"]["method"],
                              "reference_estimated_energy_wh": energy["reference"],
                              "proposed_estimated_energy_wh": energy["proposed"],
                              "estimated_energy_reduction_percent": reduction,
                              "reference_telemetry_sha256": pair["reference"]["sha256"],
                              "proposed_telemetry_sha256": pair["proposed"]["sha256"],
                              "energy_calibrated": False})
        case_means = []
        for case, reductions in reductions_by_case.items():
            case_means.append(mean(reductions))
            case_rows.append({"configuration_id": config["configuration_id"], "geographic_case": case,
                              "analyzed_pairs": len(reductions),
                              "mean_estimated_energy_reduction_percent": mean(reductions)})
        configuration_rows.append({"configuration_id": config["configuration_id"],
                                   "weight_n": model.weight_n,
                                   "electrical_efficiency": model.electrical_efficiency,
                                   "auxiliary_power_w": model.auxiliary_power_w,
                                   "climb_efficiency": model.climb_efficiency,
                                   "analyzed_pairs": len(pairs), "geographic_cases": len(case_means),
                                   "case_mean_estimated_energy_reduction_percent": mean(case_means) if case_means else None})
    means = [row["case_mean_estimated_energy_reduction_percent"] for row in configuration_rows
             if row["case_mean_estimated_energy_reduction_percent"] is not None]
    source_model = report.get("energy_model") or {}
    source_fitted = bool(source_model.get("calibration")) or any(
        pair[side]["parameter_fit_available"] for pair in pairs for side in ("reference", "proposed"))
    summary = {
        "schema_version": 1, "grid_version": GRID_VERSION,
        "scope": WARNING, "real_battery_saving_proven": False, "energy_calibrated": False,
        "benchmark_report": str(source), "benchmark_sha256": hashlib.sha256(raw).hexdigest(),
        "source_reported_pairs": len(report["pairs"]),
        "source_comparable_pairs": sum(pair.get("comparable") is True for pair in report["pairs"]),
        "analyzed_pairs": len(pairs), "excluded_pairs": excluded,
        "geographic_cases_analyzed": len({pair["geographic_case"] for pair in pairs}),
        "configuration_count": len(configurations),
        "configurations_with_estimated_saving": sum(value > 1e-9 for value in means),
        "configurations_with_estimated_increase": sum(value < -1e-9 for value in means),
        "configurations_with_tie": sum(abs(value) <= 1e-9 for value in means),
        "configurations_without_result": len(configurations) - len(means),
        "minimum_case_mean_estimated_energy_reduction_percent": min(means) if means else None,
        "maximum_case_mean_estimated_energy_reduction_percent": max(means) if means else None,
        "all_configurations_show_estimated_saving_for_analyzed_pairs": (
            len(means) == len(configurations) and all(value > 1e-9 for value in means)),
        "source_parameter_fit_detected": source_fitted,
        "calibration_policy": "Ajustes da origem não são transferidos. Todos os modelos da grade são hipóteses teóricas não calibradas.",
        "weighting": "Média das repetições por recorte, depois média com o mesmo peso para cada recorte elegível.",
        "telemetry_sources": sources, "configuration_results": configuration_rows,
    }
    output.mkdir(parents=True, exist_ok=False)
    configuration_record = {
        "schema_version": 1, "grid_version": GRID_VERSION, "warning": WARNING,
        "grid_selection_policy": "Grade fixa no código antes de ler dados; não ajustada para favorecer resultados.",
        "trajectory_policy": "Mesmas telemetrias e planos registrados. Nenhuma nova missão ou seleção de rota.",
        "base_model": model_manifest(EnergyModel()),
        "benchmark_original_energy_model": source_model,
        "weight_factors": WEIGHT_FACTORS,
        "electrical_efficiency_factors": ELECTRICAL_EFFICIENCY_FACTORS,
        "auxiliary_additions_w": AUXILIARY_ADDITIONS_W,
        "fixed_climb_efficiency": .8, "configurations": configurations,
        "real_battery_saving_proven": False,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    for filename, value in (("sensitivity_configuration.json", configuration_record),
                            ("sensitivity_summary.json", summary)):
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    _write_csv(output / "pair_sensitivity.csv", pair_rows,
               ["configuration_id", "geographic_case", "repetition", "estimated_energy_reduction_percent"])
    _write_csv(output / "case_sensitivity.csv", case_rows,
               ["configuration_id", "geographic_case", "analyzed_pairs", "mean_estimated_energy_reduction_percent"])
    _write_csv(output / "configuration_sensitivity.csv", configuration_rows, ["configuration_id"])
    _plot(configurations, configuration_rows, output, len(pairs))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="benchmark.json ou sua pasta, após a coleta dos voos.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_energy_sensitivity(args.source, args.output)
    print(f"Sensibilidade: {result}")
    print(WARNING)


if __name__ == "__main__":
    main()
