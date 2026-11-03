"""Compara energia e missão em níveis explícitos de exagero vertical."""

import argparse
import csv
import hashlib
from html import escape
import json
import shutil
from pathlib import Path
from statistics import mean

import numpy as np

from src.benchmark_report import generate_benchmark_report, _number


def summarize_levels(records):
    result = []
    for factor in sorted({r["height_scale"] for r in records}):
        rows = [r for r in records if r["height_scale"] == factor]
        values = [r["estimated_energy_reduction_percent"] for r in rows if r["comparable"]]
        result.append({"height_scale": factor, "expected_pairs": len(rows),
            "eligible_pairs": len(values), "mean_estimated_energy_reduction_percent": mean(values) if values else None,
            "minimum_estimated_energy_reduction_percent": min(values) if values else None,
            "maximum_estimated_energy_reduction_percent": max(values) if values else None,
            "positive_pairs": sum(v > 1e-9 for v in values),
            "negative_pairs": sum(v < -1e-9 for v in values),
            "tied_pairs": sum(abs(v) <= 1e-9 for v in values)})
    return result


def _controls(protocol):
    scenario = protocol["effective_scenario"]
    return {"simulation": scenario["simulation"], "coverage": scenario["coverage"],
            "baseline_planner": protocol.get("baseline_planner", "astar_legacy"),
            "wind": scenario.get("wind"), "obstacles": scenario.get("obstacles"),
            "area_m": scenario["terrain"]["area_m"], "grid_size": scenario["terrain"].get("size"),
            "energy_model": protocol["energy_model"]}


def _write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ["case"]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plots(records, terrains, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    origins = list(dict.fromkeys(r["geographic_origin"] for r in records))
    factors = sorted({r["height_scale"] for r in records})
    fig, axes = plt.subplots(2, len(origins), figsize=(max(9., 5 * len(origins)), 7), squeeze=False)
    for column, origin in enumerate(origins):
        rows = sorted([r for r in records if r["geographic_origin"] == origin], key=lambda r: r["height_scale"])
        x = [r["height_scale"] for r in rows]
        for side, color, label in (("reference", "#475569", "Referência"), ("proposed", "#e27a10", "Proposta")):
            y = [r[f"{side}_estimated_energy_wh"] if r["comparable"] else np.nan for r in rows]
            axes[0, column].plot(x, y, marker="o", linestyle="--" if side == "proposed" else "-",
                                 color=color, label=label)
        gains = [r["estimated_energy_reduction_percent"] if r["comparable"] else np.nan for r in rows]
        axes[1, column].plot(x, gains, "o-", color="#087f5b")
        for row in rows:
            if row["comparable"]:
                value = row["estimated_energy_reduction_percent"]
                axes[1, column].annotate(f"{value:+.3f}%", (row["height_scale"], value),
                                         xytext=(0, 7), textcoords="offset points", ha="center", fontsize=8)
            else:
                axes[1, column].annotate("inelegível", (row["height_scale"], 0),
                                         xytext=(0, -14), textcoords="offset points", ha="center", fontsize=8)
        axes[0, column].set_title(origin.capitalize())
        axes[0, column].set_ylabel("Energia estimada (Wh)")
        axes[0, column].legend()
        axes[1, column].set_ylabel("Redução estimada (%)")
        axes[1, column].set_xlabel("Fator vertical — 1× original; 5×/10× sintéticos")
        axes[1, column].axhline(0, color="#64748b", linewidth=.7)
        finite_gains = [value for value in gains if np.isfinite(value)] or [0.]
        low, high = min(0., *finite_gains), max(0., *finite_gains)
        padding = max(.25, (high - low) * .2)
        axes[1, column].set_ylim(low - padding, high + padding)
        span = max(max(factors) - min(factors), 1.)
        for ax in axes[:, column]:
            ax.set_xticks(factors, [f"{f:g}×" for f in factors])
            ax.grid(alpha=.2)
            ax.margins(x=.15, y=.25)
            ax.set_xlim(min(factors) - span * .15, max(factors) + span * .15)
    fig.suptitle("Mesmo regime de voo e área — efeito do relevo sobre a comparação", fontsize=13)
    fig.tight_layout(rect=(0, .02, 1, .95))
    fig.savefig(output / "energy_by_relief.png", dpi=180)
    fig.savefig(output / "energy_by_relief.svg")
    plt.close(fig)

    if terrains:
        fig = plt.figure(figsize=(4.5 * len(factors), 3.5 * len(origins)))
        maximum = max(float(np.ptp(data[0])) for data in terrains.values())
        for row_index, origin in enumerate(origins):
            for column, factor in enumerate(factors):
                ax = fig.add_subplot(len(origins), len(factors), row_index * len(factors) + column + 1, projection="3d")
                item = terrains.get((origin, factor))
                if item is None:
                    ax.set_axis_off()
                    ax.set_title(f"{origin} {factor:g}× — sem voo no lote principal")
                    ax.text2D(.5, .5, "Tentativa não executada\nConsulte o motivo de exclusão",
                              transform=ax.transAxes, ha="center", va="center")
                    continue
                z, cell = item
                y, x = np.indices(z.shape)
                relative = z - np.min(z)
                ax.plot_surface(x * cell, y * cell, relative, cmap="terrain", vmin=0, vmax=maximum,
                                linewidth=.2, edgecolor="#334155", alpha=.95)
                ax.set_zlim(0, max(maximum, 1))
                ax.set_title(f"{origin} {factor:g}× | desnível {np.ptp(z):.1f} m")
                ax.set_xlabel("Leste (m)")
                ax.set_ylabel("Linha (m)")
                ax.set_zlabel("Altura relativa (m)")
                ax.view_init(28, -55)
        fig.suptitle("Mesma escala vertical nos nove painéis — apenas 1× representa o relevo original")
        fig.tight_layout(rect=(0, 0, 1, .97))
        fig.savefig(output / "terrain_levels.png", dpi=160)
        plt.close(fig)


def generate_relief_report(source: Path, output: Path):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    flights = source / "flights" if (source / "flights").is_dir() else source
    manifest_path = flights / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    definition = manifest["definition"]
    locations = {str(item["id"]): item for item in definition["locations"]}
    if any("height_scale" not in item or "geographic_origin" not in item for item in locations.values()):
        raise ValueError("O manifesto deve declarar origem geográfica e fator vertical de cada caso.")
    output.mkdir(parents=True)
    generate_benchmark_report(flights, output / "paired", proposed_method="proposta_subida_orientacao")
    paired = json.loads((output / "paired/benchmark.json").read_text(encoding="utf-8"))
    attempts = json.loads((flights / "attempts.json").read_text(encoding="utf-8"))
    folders = {(a["case"], int(a["repetition"])): Path(a["output"]) for a in attempts}
    raw_by_key = {}
    if (flights / "all_flights.csv").is_file():
        with (flights / "all_flights.csv").open(encoding="utf-8-sig") as stream:
            raw_by_key = {(row["geographic_case"], int(row["repetition"]), row["method"]): row
                          for row in csv.DictReader(stream)}
    records, terrains, controls, provenance = [], {}, None, []
    for pair in paired["pairs"]:
        entry = locations[pair["geographic_case"]]
        origin, factor = str(entry["geographic_origin"]), float(entry["height_scale"])
        reference, proposed = pair["reference"] or {}, pair["proposed"] or {}
        folder = folders.get((pair["geographic_case"], pair["repetition"]))
        record = {"case": pair["geographic_case"], "geographic_origin": origin, "height_scale": factor,
            "repetition": pair["repetition"], "synthetic_terrain": factor != 1,
            "attempt_status": pair["attempt_status"], "attempt_error": pair["attempt_error"],
            "relief_m": None, "comparable": pair["comparable"],
            "reference_orientation": None, "proposed_orientation": None,
            "reference_planned_cost": None, "proposed_planned_cost": None,
            "estimated_energy_reduction_percent": pair["estimated_energy_reduction_percent"],
            "exclusion_reasons": ";".join(pair["reference_exclusion_reasons"] + pair["proposed_exclusion_reasons"] + pair["pair_exclusion_reasons"])}
        for side, row in (("reference", reference), ("proposed", proposed)):
            for key in ("estimated_energy_wh", "observed_duration_s", "distance_3d_m", "elevation_gain_m", "executed_coverage_percent"):
                record[f"{side}_{key}"] = row.get(key)
            raw = raw_by_key.get((pair["geographic_case"], pair["repetition"], row.get("method")), {})
            for key in ("collisions", "clearance_violations", "minimum_clearance_m", "energy_outside_envelope_intervals"):
                record[f"{side}_{key}"] = _number(raw.get(key))
        if folder is not None and (folder / "protocol.json").exists():
            path = folder / "protocol.json"
            protocol = json.loads(path.read_text(encoding="utf-8"))
            current = _controls(protocol)
            if controls is not None and current != controls:
                raise ValueError("Os casos não usam o mesmo regime de voo e modelo energético.")
            controls = current
            provenance.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            scenario = protocol["effective_scenario"]
            plans = {plan["method"]: plan for plan in protocol.get("plans", [])}
            reference_plan = protocol.get("method_plan_mapping", {}).get("referencia_2d", "horizontal_2d")
            record["reference_orientation"] = plans.get(reference_plan, {}).get("orientation")
            record["proposed_orientation"] = plans.get("climb_orientation", {}).get("orientation")
            record["reference_planned_cost"] = plans.get(reference_plan, {}).get("normalized_cost")
            record["baseline_planner"] = protocol.get("baseline_planner", "astar_legacy")
            record["baseline_description"] = protocol.get("baseline_description", "Referência histórica A*.")
            record["proposed_planned_cost"] = plans.get("climb_orientation", {}).get("normalized_cost")
            if float(scenario["terrain"].get("height_scale", 1.)) != factor:
                raise ValueError("O fator vertical executado difere do manifesto.")
            with np.load(folder / "terrain.npz") as data:
                elevation = data["terrain"]
            w = scenario["coverage"]["window"]
            mission = elevation[w["row_start"]:w["row_end"]+1, w["col_start"]:w["col_end"]+1]
            record["relief_m"] = float(np.ptp(mission))
            terrains[origin, factor] = (mission, scenario["terrain"]["area_m"] / elevation.shape[1])
        records.append(record)
    levels = summarize_levels(records)
    trends = []
    for origin in dict.fromkeys(r["geographic_origin"] for r in records):
        by_level = sorted([r for r in records if r["geographic_origin"] == origin], key=lambda r: r["height_scale"])
        valid = bool(by_level) and all(r["comparable"] for r in by_level)
        values = [r["estimated_energy_reduction_percent"] for r in by_level] if valid else []
        trends.append({"geographic_origin": origin, "all_levels_eligible": valid,
            "nondecreasing_with_relief": all(b + 1e-9 >= a for a, b in zip(values, values[1:])) if valid else None,
            "change_last_vs_first_percentage_points": values[-1] - values[0] if valid else None})
    base = {(r["geographic_origin"], r["repetition"]): r for r in records if r["height_scale"] == 1}
    for record in records:
        anchor = base.get((record["geographic_origin"], record["repetition"]))
        record["change_vs_original_percentage_points"] = (
            record["estimated_energy_reduction_percent"] - anchor["estimated_energy_reduction_percent"]
            if anchor and record["comparable"] and anchor["comparable"] else None)
    summary = {"expected_pairs": len(records), "eligible_pairs": sum(r["comparable"] for r in records),
               "levels": levels, "trends": trends, "common_controls": controls, "records": records,
               "scope": definition.get("scope"), "selection_rule": definition.get("selection_rule"),
               "real_battery_saving_proven": False, "source_protocols": provenance}
    analysis = output / "analysis_sources"
    analysis.mkdir()
    summary["analysis_sources"] = []
    for filename in ("relief_report.py", "benchmark_report.py"):
        script = Path(__file__).parent / filename
        shutil.copy2(script, analysis / filename)
        summary["analysis_sources"].append({"file": f"analysis_sources/{filename}",
            "sha256": hashlib.sha256(script.read_bytes()).hexdigest()})
    summary["simulation_time_steps_s"] = sorted({float(row["simulation_time_step_s"])
        for row in raw_by_key.values() if row.get("simulation_time_step_s") not in (None, "")})
    (output / "relief_comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    _write_csv(output / "relief_comparison.csv", records)
    _write_csv(output / "level_summary.csv", levels)
    _plots(records, terrains, output)
    def f(value, digits=3):
        return "—" if value is None else f"{value:.{digits}f}"
    simulation = (controls or {}).get("simulation", {})
    coverage = (controls or {}).get("coverage", {})
    step_text = ", ".join(f(value, 3) for value in summary["simulation_time_steps_s"]) or "não registrado"
    lines = ["# Relatório comparativo: relevo e energia estimada", "",
        "Foram testados os mesmos três recortes com fatores verticais de 1×, 5× e 10×. Apenas 1× representa o TOPODATA original; os demais são terrenos sintéticos derivados.", "",
        f"O cenário 1× foi reexecutado no mesmo regime dos demais: {f(simulation.get('speed_mps'),1)} m/s, altura-alvo de {f(coverage.get('clearance_m'),1)} m, largura de aplicação de {f(coverage.get('swath_m'),1)} m e faixas a cada {f(coverage.get('stripe_spacing_m'),1)} m. Os dois métodos usam a mesma origem, retorno, controlador, terreno e modelo de energia. Passos temporais registrados: {step_text} s.", "",
        "## Comparação por missão", "",
        "| Recorte | Fator | Desnível (m) | Referência (Wh) | Proposta (Wh) | Redução estimada (%) | Cobertura ref./prop. (%) | Par válido |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in records:
        lines.append(f"| {r['geographic_origin']} | {r['height_scale']:g}× | {f(r['relief_m'],1)} | {f(r['reference_estimated_energy_wh'])} | {f(r['proposed_estimated_energy_wh'])} | {f(r['estimated_energy_reduction_percent'])} | {f(r['reference_executed_coverage_percent'],1)}/{f(r['proposed_executed_coverage_percent'],1)} | {'Sim' if r['comparable'] else 'Não'} |")
    excluded = [r for r in records if not r["comparable"]]
    if excluded:
        lines += ["", "## Tentativas inelegíveis", "",
                  "| Caso | Estado | Erro de execução | Motivos de exclusão |",
                  "| --- | --- | --- | --- |"]
        for record in excluded:
            clean = lambda value: str(value).replace("|", "/").replace("\n", " ")
            lines.append("| " + " | ".join(clean(record[key]) for key in
                ("case", "attempt_status", "attempt_error", "exclusion_reasons")) + " |")
    lines += ["", "## Resultado por nível de relevo", "",
        "| Fator | Pares válidos/previstos | Redução média por recorte (%) | Reduções / empates / aumentos |", "| --- | --- | --- | --- |"]
    for level in levels:
        lines.append(f"| {level['height_scale']:g}× | {level['eligible_pairs']}/{level['expected_pairs']} | {f(level['mean_estimated_energy_reduction_percent'])} | {level['positive_pairs']} / {level['tied_pairs']} / {level['negative_pairs']} |")
    lines += ["", "Se os conjuntos elegíveis diferirem entre os fatores, as médias agregadas não constituem uma comparação completa do efeito do relevo. A leitura principal deve acompanhar a mesma origem nos três níveis.", "",
              "## Distância, duração e subida executadas", "",
              "| Recorte | Fator | Distância ref./prop. (m) | Duração ref./prop. (s) | Subida ref./prop. (m) |",
              "| --- | --- | --- | --- | --- |"]
    for r in records:
        lines.append(f"| {r['geographic_origin']} | {r['height_scale']:g}× | {f(r['reference_distance_3d_m'],1)}/{f(r['proposed_distance_3d_m'],1)} | {f(r['reference_observed_duration_s'],1)}/{f(r['proposed_observed_duration_s'],1)} | {f(r['reference_elevation_gain_m'],1)}/{f(r['proposed_elevation_gain_m'],1)} |")
    lines += ["", "## Segurança e limites do modelo energético", "",
              "| Recorte | Fator | Colisões ref./prop. | Violações de altura ref./prop. | Menor altura ref./prop. (m) | Intervalos fora do envelope ref./prop. |",
              "| --- | --- | --- | --- | --- | --- |"]
    for r in records:
        lines.append(f"| {r['geographic_origin']} | {r['height_scale']:g}× | {f(r['reference_collisions'],0)}/{f(r['proposed_collisions'],0)} | {f(r['reference_clearance_violations'],0)}/{f(r['proposed_clearance_violations'],0)} | {f(r['reference_minimum_clearance_m'],1)}/{f(r['proposed_minimum_clearance_m'],1)} | {f(r['reference_energy_outside_envelope_intervals'],0)}/{f(r['proposed_energy_outside_envelope_intervals'],0)} |")
    lines += ["", "As métricas de voos inelegíveis podem ser parciais. Elas ficam identificadas na primeira tabela e não sustentam comparação de economia.", "",
              "## A vantagem cresceu com o relevo?", ""]
    for trend in trends:
        if trend["all_levels_eligible"]:
            change = trend["change_last_vs_first_percentage_points"]
            last = max((r for r in records if r["geographic_origin"] == trend["geographic_origin"]),
                       key=lambda r:r["height_scale"])["estimated_energy_reduction_percent"]
            if abs(change) <= 1e-9:
                wording = "a redução percentual do último nível permaneceu igual à do controle 1×"
            elif change < 0:
                wording = "o resultado do último nível ficou mais desfavorável à proposta"
            elif last < -1e-9:
                wording = "a desvantagem estimada diminuiu, mas a proposta ainda gastou mais no último nível"
            elif abs(last) <= 1e-9:
                wording = "o resultado melhorou até chegar a um empate no último nível"
            elif trend["nondecreasing_with_relief"]:
                wording = "a vantagem estimada cresceu com o relevo"
            else:
                wording = "a vantagem final aumentou, mas sem crescimento monotônico"
            lines.append(f"Em {trend['geographic_origin']}, {wording}. A mudança entre o último e o primeiro nível foi de {f(change)} pontos percentuais.")
        else:
            lines.append(f"Em {trend['geographic_origin']}, faltou um par elegível em pelo menos um nível; a tendência completa permanece indeterminada.")
    descriptions = list(dict.fromkeys(r.get("baseline_description", "Referência histórica A*.") for r in records))
    lines += ["", "Referência: " + " / ".join(descriptions), "",
              "A proposta A* escolhe entre horizontal e vertical pelo custo de distância e subida. As orientações e os custos planejados de cada caso estão no CSV. O peso de subida e o modelo energético permaneceram iguais em todos os níveis; não foram ajustados para produzir ganho.", "",
              "O custo de distância 3D + peso × subida não é energia em Wh. Uma rota com menos subida pode gastar mais se aumentar distância ou duração. A escolha atual minimiza esse custo auxiliar, não diretamente a energia estimada do voo."]
    lines += ["", "![Comparação de energia por relevo](energy_by_relief.png)", "", "![Desníveis dos terrenos](terrain_levels.png)", "",
        "## Interpretação e limites", "",
        "Reduções positivas favorecem a proposta; negativas representam piora. Falhas e cobertura insuficiente ficam no denominador, com redução em branco. O CSV contém também distância, duração e subida acumulada. Valores de energia de voos inelegíveis são parciais e não podem ser usados para anunciar economia.", "",
        "Os fatores foram definidos antes da coleta; não se escolheu apenas o terreno favorável. As versões ampliadas são variações dos mesmos recortes, não novas fazendas independentes. Este teste mostra como o comportamento muda com o relevo nas condições registradas.", "",
        "A energia é estimada por um modelo teórico não calibrado. O benchmark anterior encontrou falha do controlador ao alterar o passo para 0,025 s. O presente experimento mantém 0,05 s e não resolve essa limitação. Não comprova economia real de bateria nem generalização.", "",
        "O comparativo anterior usava 8 m/s e altura-alvo de 60 m. Seus Wh não devem ser comparados diretamente aos atuais para atribuir a diferença exclusivamente ao relevo; use o controle 1× desta coleta.", "",
        "Consulte paired/index.html para os pares individuais, inclusive motivos de exclusão e rastreabilidade. As versões com relevo maior são identificadas no painel do CoppeliaSim."]
    (output / "relatorio.md").write_text("\n".join(lines), encoding="utf-8")
    # HTML local sem dependências de rede; conserva tabelas e imagens do Markdown.
    html = ["<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Comparativo de relevo</title><style>body{font:16px system-ui;max-width:1250px;margin:36px auto;padding:0 24px;line-height:1.55;color:#182535}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #cbd5e1;padding:7px;text-align:left}img{max-width:100%}.scroll{overflow-x:auto}</style>"]
    in_table, heading = False, False
    for line in lines:
        if line.startswith("|"):
            if line.startswith("| ---"):
                continue
            if not in_table:
                html.append("<div class='scroll'><table>")
                in_table, heading = True, True
            tag = "th" if heading else "td"
            html.append("<tr>" + "".join(f"<{tag}>{escape(cell.strip())}</{tag}>" for cell in line.strip("|").split("|")) + "</tr>")
            heading = False
            continue
        if in_table:
            html.append("</table></div>")
            in_table = False
        if line.startswith("# "):
            html.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            html.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("!["):
            alt, url = line[2:].split("](")
            html.append(f"<img alt='{escape(alt)}' src='{escape(url[:-1])}'>")
        elif line:
            html.append(f"<p>{escape(line)}</p>")
    if in_table:
        html.append("</table></div>")
    html.append("<p><a href='paired/index.html'>Relatório pareado</a> · <a href='relief_comparison.csv'>Dados CSV</a> · <a href='relief_comparison.json'>Dados e protocolo JSON</a></p></html>")
    (output / "index.html").write_text("\n".join(html), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(generate_relief_report(args.source, args.output) / "index.html")


if __name__ == "__main__":
    main()
