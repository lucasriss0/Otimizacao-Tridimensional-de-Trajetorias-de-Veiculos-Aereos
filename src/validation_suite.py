"""Executa um conjunto geográfico pré-definido, preservando todas as tentativas."""

import argparse
import csv
import json
from pathlib import Path

import yaml

from src.coverage_comparison import compare_coverage_flights
from src.energy import load_energy_model, model_manifest
from src.scenario import load_scenario


def run_validation_suite(manifest_path, output, dry_run=False,
                         host="127.0.0.1", port=23000):
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else (manifest_path.parent / path).resolve()

    base_path = resolve(manifest["base_scenario"])
    energy_path = resolve(manifest["energy_model"])
    model = load_energy_model(energy_path)
    base = load_scenario(base_path)
    repetitions = manifest["repetitions"]
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError("Repetições devem ser um inteiro positivo.")
    locations = manifest["locations"]
    if not locations or len({entry["id"] for entry in locations}) != len(locations):
        raise ValueError("Informe locais com identificadores únicos.")
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(json.dumps({
        "definition": manifest, "base_scenario_yaml": base_path.read_text(encoding="utf-8"),
        "energy_model": model_manifest(model), "dry_run": dry_run,
        "scope": "Recortes geográficos exploratórios; não representam limites cadastrais de fazendas. Repetições não são terrenos independentes. Ordem dos métodos fixa.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    attempts, rows = [], []
    for index, location in enumerate(locations):
        raw = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        raw["id"] = str(location["id"])
        raw["terrain"]["topodata"] = str(base.terrain.topodata.resolve())
        raw["terrain"]["center_lat"] = location["center_lat"]
        raw["terrain"]["center_lon"] = location["center_lon"]
        scenario_path = output / f"scenario_{index:02d}.yaml"
        scenario_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        for repetition in range(1, repetitions + 1):
            folder = output / f"case_{index:02d}_repeat_{repetition:02d}"
            attempt = {"case": raw["id"], "repetition": repetition,
                       "output": str(folder), "status": "started", "error": ""}
            attempts.append(attempt)
            status_path = output / "attempts.json"
            status_path.write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                compare_coverage_flights(
                    scenario_path, folder, host=host, port=port, dry_run=dry_run,
                    energy_model_path=energy_path, ablation=True,
                    minimum_executed_coverage=manifest["minimum_executed_coverage_percent"],
                    maximum_telemetry_gap_s=manifest["maximum_telemetry_gap_s"],
                )
                if not dry_run:
                    with (folder / "comparison.csv").open(encoding="utf-8-sig") as stream:
                        for row in csv.DictReader(stream):
                            rows.append({"geographic_case": raw["id"], "repetition": repetition, **row})
                    with (output / "all_flights.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                        writer.writeheader()
                        writer.writerows(rows)
                attempt["status"] = "planned" if dry_run else "recorded"
            except (ValueError, RuntimeError, FileNotFoundError) as error:
                attempt["status"] = "failed"
                attempt["error"] = str(error)
                # Não substitui cenários que falharam por cenários favoráveis.
            finally:
                status_path.write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("configs/validation_suite.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    args = parser.parse_args()
    result = run_validation_suite(args.manifest, args.output, args.dry_run, args.host, args.port)
    print(f"Lote registrado: {result}. Consulte attempts.json para falhas.")


if __name__ == "__main__":
    main()
