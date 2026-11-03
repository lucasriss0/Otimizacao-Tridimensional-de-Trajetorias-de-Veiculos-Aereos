"""Verificação posterior da resolução temporal, sem reotimizar planos."""

import argparse
import csv
import json
from pathlib import Path

from src.coverage_comparison import compare_coverage_flights


def _read(path):
    with path.open(encoding="utf-8-sig") as stream:
        return {row["method"]: row for row in csv.DictReader(stream)}


def _comparison(original, folder, case, time_step_s):
    old_protocol = json.loads((original / "protocol.json").read_text(encoding="utf-8"))
    new_protocol = json.loads((folder / "protocol.json").read_text(encoding="utf-8"))
    old_plans = {p["method"]: p["path"] for p in old_protocol["plans"]}
    new_plans = {p["method"]: p["path"] for p in new_protocol["plans"]}
    same_plans = (old_plans["referencia_2d"] == new_plans["horizontal_2d"]
                  and old_plans["proposta_completa"] == new_plans["climb_orientation"])
    old, new = _read(original / "comparison.csv"), _read(folder / "comparison.csv")
    original_eligible = all(old[method]["energy_comparison_eligible"] == "True"
                            for method in ("referencia_2d", "proposta_completa"))
    refined_eligible = all(new[method]["energy_comparison_eligible"] == "True"
                           for method in ("referencia_2d", "proposta_subida_orientacao"))
    eligible = same_plans and original_eligible and refined_eligible
    before = after = None
    if original_eligible:
        before = 100 * (1 - float(old["proposta_completa"]["estimated_energy_wh"]) / float(old["referencia_2d"]["estimated_energy_wh"]))
    if refined_eligible:
        after = 100 * (1 - float(new["proposta_subida_orientacao"]["estimated_energy_wh"]) / float(new["referencia_2d"]["estimated_energy_wh"]))
    return {"case": case, "identical_plans": same_plans, "comparable": eligible,
            "original_time_step_s": old["referencia_2d"].get("simulation_time_step_s", .05),
            "refined_time_step_s": time_step_s,
            "original_reduction_percent": before, "refined_reduction_percent": after,
            "change_percentage_points": after - before if eligible else None,
            "refined_reference_error": new["referencia_2d"].get("error", ""),
            "refined_proposed_error": new["proposta_subida_orientacao"].get("error", "")}


def analyze_time_step_check(source: Path, output: Path):
    """Regenera somente a análise dos arquivos coletados, sem nova simulação."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    protocol = json.loads((source / "protocol.json").read_text(encoding="utf-8"))
    rows = []
    for index, case in enumerate(protocol["cases"]):
        if case["status"] == "recorded":
            rows.append(_comparison(Path(case["original"]), source / f"case_{index:02d}",
                                    case["case"], protocol["requested_time_step_s"]))
    output.mkdir(parents=True)
    protocol["analysis_source"] = str(source)
    (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "time_step_comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["case", "comparable"])
        writer.writeheader()
        writer.writerows(rows)
    return output


def run_time_step_check(benchmark: Path, output: Path, time_step_s=.025,
                        host="127.0.0.1", port=23000):
    """Repete um par por recorte com dt menor. Dois passos não provam convergência."""
    benchmark, output = Path(benchmark).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    flights = benchmark / "flights" if (benchmark / "flights").is_dir() else benchmark
    attempts = json.loads((flights / "attempts.json").read_text(encoding="utf-8"))
    definition = json.loads((flights / "manifest.json").read_text(encoding="utf-8"))["definition"]
    # A configuração comum fica arquivada pelo orquestrador, sem dependência
    # de alterações futuras na configuração de trabalho.
    model = benchmark / "implementation/configs/energy_reference.json"
    if not model.is_file():
        raise FileNotFoundError("Modelo energético original arquivado não encontrado.")
    output.mkdir(parents=True)
    protocol = {"requested_time_step_s": time_step_s,
                "scope": "Diagnóstico posterior em todos os recortes com um par completo, sem escolher por ganho. Planos devem coincidir com a coleta original. Não é validação elétrica nem estudo formal de convergência com três níveis.",
                "source": str(benchmark), "cases": []}
    rows, seen = [], set()
    for index, location in enumerate(definition["locations"]):
        case = location["id"]
        original = None
        for attempt in attempts:
            if attempt["case"] != case or case in seen:
                continue
            path = Path(attempt["output"])
            if not (path / "comparison.csv").is_file():
                continue
            pair = _read(path / "comparison.csv")
            if all(pair.get(method, {}).get("mission_completed") == "True"
                   for method in ("referencia_2d", "proposta_completa")):
                original = path
                seen.add(case)
                break
        if original is None:
            protocol["cases"].append({"case": case, "status": "no_complete_original_pair"})
            continue
        folder = output / f"case_{index:02d}"
        entry = {"case": case, "original": str(original), "status": "started"}
        protocol["cases"].append(entry)
        (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            compare_coverage_flights(flights / f"scenario_{index:02d}.yaml", folder,
                host=host, port=port, energy_model_path=model, executor="lua",
                disable_rendering=True, time_step_s=time_step_s)
            rows.append(_comparison(original, folder, case, time_step_s))
            entry["status"] = "recorded"
        except Exception as error:
            entry.update(status="failed", error=str(error))
        finally:
            (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        with (output / "time_step_comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-step", type=float, default=.025)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=23000)
    parser.add_argument("--analyze-only", action="store_true", help="A entrada é uma pasta time_step_check já coletada; não conecta ao simulador.")
    args = parser.parse_args()
    if args.analyze_only:
        print(analyze_time_step_check(args.benchmark, args.output))
    else:
        print(run_time_step_check(args.benchmark, args.output, args.time_step, args.host, args.port))


if __name__ == "__main__":
    main()
