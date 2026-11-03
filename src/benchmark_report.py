"""Relatório pareado de energia estimada das trajetórias executadas no simulador."""

import argparse
import csv
import hashlib
from html import escape
import json
from math import isfinite
from pathlib import Path
from statistics import mean, stdev

from src.telemetry_metrics import _flag


def _read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _true(value):
    try:
        return _flag(value)
    except ValueError:
        return False


def _resolve_recorded_path(value, root):
    path = Path(value)
    candidates = (path, root / path, root.parent / path,
                  Path(__file__).resolve().parents[1] / path)
    return next((p.resolve() for p in candidates if p.exists()), root / path)


def _collect(source):
    """Preserva a lista pré-definida e recupera resultados de tentativas parciais."""
    root = source if source.is_dir() else source.parent
    csv_path = source if source.is_file() else root / "all_flights.csv"
    if not csv_path.is_file():
        csv_path = root / "comparison.csv"
    rows = _read_csv(csv_path) if csv_path.is_file() else []
    provenance = [csv_path] if csv_path.is_file() else []
    expected, attempts = {}, []
    definition, protocol = {}, {}
    manifest = root / "manifest.json"
    if manifest.is_file():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        definition = raw.get("definition", {})
        protocol = raw
        provenance.append(manifest)
        for location in definition.get("locations", []):
            for repetition in range(1, int(definition["repetitions"]) + 1):
                expected[str(location["id"]), repetition] = {"status": "not_started", "error": ""}
    protocol_path = root / "protocol.json"
    if protocol_path.is_file():
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        provenance.append(protocol_path)
    attempts_path = root / "attempts.json"
    if attempts_path.is_file():
        attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
        provenance.append(attempts_path)
        for attempt in attempts:
            key = str(attempt["case"]), int(attempt["repetition"])
            expected[key] = {"status": attempt["status"], "error": attempt.get("error", "")}
            folder = _resolve_recorded_path(attempt["output"], root)
            partial = folder / "comparison.csv"
            # all_flights.csv só recebe uma tentativa após o comparador retornar.
            # Recupera os voos já salvos se a tentativa falhou no meio.
            existing = {r["method"] for r in rows if
                        str(r.get("geographic_case", "")) == key[0]
                        and str(r.get("repetition", "")) == str(key[1])}
            if partial.is_file():
                partial_rows = _read_csv(partial)
                rows.extend({"geographic_case": key[0], "repetition": key[1], **row}
                            for row in partial_rows if row["method"] not in existing)
                provenance.append(partial)
    default_case = str(protocol.get("effective_scenario", {}).get("scenario_id", root.name))
    for row in rows:
        if row.get("trajectory_kind", "").startswith("ideal"):
            raise ValueError("O relatório exige execuções do simulador; trajetórias ideais não são voos.")
        row["geographic_case"] = str(row.get("geographic_case") or row.get("case") or default_case)
        repetition = _number(row.get("repetition", 1))
        if repetition is None or repetition < 1 or not repetition.is_integer():
            raise ValueError("Repetição deve ser um inteiro positivo.")
        row["repetition"] = int(repetition)
        expected.setdefault((row["geographic_case"], row["repetition"]),
                            {"status": "recorded", "error": ""})
    if not expected:
        # Um protocolo sem CSV é uma tentativa sem resultado, inclusive dry-run.
        if protocol:
            expected[default_case, 1] = {"status": "planned" if protocol.get("dry_run") else "no_results", "error": ""}
        else:
            raise ValueError("Fonte sem comparison.csv, all_flights.csv ou protocolo de tentativas.")
    return root, rows, expected, protocol, definition, provenance


def _exclusions(row, minimum_coverage):
    if row is None:
        return ["voo_ausente"]
    reasons = [v for v in row.get("energy_comparison_exclusion_reasons", "").split(";") if v]
    if not _true(row.get("energy_comparison_eligible")):
        reasons.append("elegibilidade_nao_confirmada")
    if not _true(row.get("mission_completed_safely")):
        reasons.append("missao_incompleta_ou_insegura")
    coverage = _number(row.get("executed_coverage_percent"))
    if not _true(row.get("executed_coverage_available")) or coverage is None:
        reasons.append("cobertura_indisponivel")
    elif coverage + 1e-9 < minimum_coverage or coverage > 100 + 1e-9:
        reasons.append("cobertura_insuficiente_ou_invalida")
    if _number(row.get("coverage_telemetry_gaps")) != 0:
        reasons.append("lacunas_na_telemetria_ou_registro_ausente")
    energy = _number(row.get("estimated_energy_wh"))
    if not _true(row.get("energy_estimate_available")) or energy is None or energy <= 0:
        reasons.append("energia_indisponivel_ou_invalida")
    if _number(row.get("energy_outside_envelope_intervals")) != 0:
        reasons.append("fora_do_envelope_energetico_ou_registro_ausente")
    return list(dict.fromkeys(reasons))


def _flight(row):
    if row is None:
        return None
    return {"method": row["method"],
            "estimated_energy_wh": _number(row.get("estimated_energy_wh")),
            "executed_coverage_percent": _number(row.get("executed_coverage_percent")),
            "cultivable_area_m2": _number(row.get("cultivable_area_m2")),
            "covered_area_m2": _number(row.get("executed_covered_area_m2")),
            "observed_duration_s": _number(row.get("observed_duration_s")),
            "distance_3d_m": _number(row.get("executed_distance_3d_m")),
            "elevation_gain_m": _number(row.get("executed_elevation_gain_m")),
            "mission_completed_safely": _true(row.get("mission_completed_safely")),
            "run_directory": row.get("run_directory", ""),
            "energy_model": row.get("energy_model"),
            "energy_model_sha256": row.get("energy_model_sha256"),
            "energy_parameter_fit_available": _true(row.get("energy_parameter_fit_available"))}


def _pairs(rows, expected, protocol, reference_method, proposed_method):
    by_key = {}
    for row in rows:
        key = row["geographic_case"], row["repetition"], row["method"]
        if key in by_key:
            raise ValueError(f"Voo duplicado para {key}; não é permitido escolher uma repetição favorável.")
        by_key[key] = row
    minimum = protocol.get("minimum_executed_coverage_percent", 100.)
    minimum = protocol.get("definition", {}).get("minimum_executed_coverage_percent", minimum)
    minimum = _number(minimum)
    if minimum is None or not 0 < minimum <= 100:
        raise ValueError("Limiar de cobertura do protocolo inválido.")
    result = []
    for (case, repetition), attempt in expected.items():
        ref = by_key.get((case, repetition, reference_method))
        prop = by_key.get((case, repetition, proposed_method))
        ref_reasons, prop_reasons = _exclusions(ref, minimum), _exclusions(prop, minimum)
        pair_reasons = []
        if protocol.get("dry_run"):
            pair_reasons.append("protocolo_sem_execucao")
        if ref and prop:
            if ref.get("energy_model") != prop.get("energy_model"):
                pair_reasons.append("modelos_energeticos_diferentes")
            ref_hash, prop_hash = ref.get("energy_model_sha256"), prop.get("energy_model_sha256")
            if not ref_hash or not prop_hash:
                pair_reasons.append("parametros_energeticos_nao_verificados")
            elif ref_hash != prop_hash:
                pair_reasons.append("parametros_energeticos_diferentes")
            ref_area = _number(ref.get("cultivable_area_m2"))
            prop_area = _number(prop.get("cultivable_area_m2"))
            if ref_area is None or prop_area is None or min(ref_area, prop_area) <= 0:
                pair_reasons.append("area_cultivavel_indisponivel")
            elif abs(ref_area - prop_area) > 1e-6:
                pair_reasons.append("areas_cultivaveis_diferentes")
        comparable = not (ref_reasons or prop_reasons or pair_reasons)
        a, b = _flight(ref), _flight(prop)
        reduction = 100 * (a["estimated_energy_wh"] - b["estimated_energy_wh"]) / a["estimated_energy_wh"] if comparable else None
        result.append({"geographic_case": case, "repetition": repetition,
                       "attempt_status": attempt["status"], "attempt_error": attempt["error"],
                       "reference": a, "proposed": b, "comparable": comparable,
                       "reference_exclusion_reasons": ref_reasons,
                       "proposed_exclusion_reasons": prop_reasons,
                       "pair_exclusion_reasons": pair_reasons,
                       "estimated_energy_reduction_percent": reduction})
    return result


def _summarize(pairs):
    eligible = [p for p in pairs if p["comparable"]]
    reductions = [p["estimated_energy_reduction_percent"] for p in eligible]
    case_rows = []
    for case in dict.fromkeys(p["geographic_case"] for p in pairs):
        subset = [p for p in pairs if p["geographic_case"] == case]
        values = [p["estimated_energy_reduction_percent"] for p in subset if p["comparable"]]
        case_rows.append({"geographic_case": case, "expected_pairs": len(subset),
                          "eligible_pairs": len(values),
                          "mean_estimated_energy_reduction_percent": mean(values) if values else None})
    case_means = [r["mean_estimated_energy_reduction_percent"] for r in case_rows
                  if r["mean_estimated_energy_reduction_percent"] is not None]
    reference = sum(p["reference"]["estimated_energy_wh"] for p in eligible)
    proposed = sum(p["proposed"]["estimated_energy_wh"] for p in eligible)
    return {"expected_pairs": len(pairs), "eligible_pairs": len(eligible),
            "ineligible_or_missing_pairs": len(pairs) - len(eligible),
            "recorded_flights_in_target_pairs": sum(p[k] is not None for p in pairs for k in ("reference", "proposed")),
            "all_pairs_eligible": bool(pairs) and len(eligible) == len(pairs),
            "positive_pairs": sum(v > 1e-9 for v in reductions),
            "negative_pairs": sum(v < -1e-9 for v in reductions),
            "tied_pairs": sum(abs(v) <= 1e-9 for v in reductions),
            "mean_estimated_energy_reduction_percent": mean(reductions) if reductions else None,
            "sample_sd_estimated_energy_reduction_percent": stdev(reductions) if len(reductions) > 1 else None,
            "minimum_estimated_energy_reduction_percent": min(reductions) if reductions else None,
            "maximum_estimated_energy_reduction_percent": max(reductions) if reductions else None,
            "total_reference_estimated_energy_wh": reference if eligible else None,
            "total_proposed_estimated_energy_wh": proposed if eligible else None,
            "pooled_estimated_energy_reduction_percent": 100 * (reference - proposed) / reference if eligible else None,
            "case_mean_estimated_energy_reduction_percent": mean(case_means) if case_means else None,
            "geographic_cases_with_eligible_pairs": len(case_means),
            "observed_mean_estimated_energy_saving": bool(reductions) and mean(reductions) > 1e-9,
            "real_battery_saving_proven": False}, case_rows


def _format(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def _method_comparisons(rows, expected, protocol, reference_method):
    """As variantes também usam pares completos; não mistura terrenos entre métodos."""
    from src.ablation import METHODS
    comparisons = []
    for method in METHODS[1:]:
        if method != reference_method and any(row["method"] == method for row in rows):
            pairs = _pairs(rows, expected, protocol, reference_method, method)
            summary, cases = _summarize(pairs)
            comparisons.append({"method": method, "summary": summary, "cases": cases})
    return comparisons


def _plots(pairs, root, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    labels = [f"{p['geographic_case']} / {p['repetition']}" for p in pairs]
    x = np.arange(len(pairs))
    width = max(7., .9 * len(pairs))
    figures = []
    fig, axes = plt.subplots(2, 1, figsize=(width, 7.), sharex=True)
    for side, offset, color, label in (("reference", -.18, "#475569", "Referência"),
                                       ("proposed", .18, "#0284c7", "Proposta")):
        energies = [p[side]["estimated_energy_wh"] if p[side] else None for p in pairs]
        for i, value in enumerate(energies):
            if value is not None:
                axes[0].bar(x[i] + offset, value, width=.34, color=color,
                            alpha=1. if pairs[i]["comparable"] else .35,
                            label=label if i == next(j for j, v in enumerate(energies) if v is not None) else None)
    axes[0].set_ylabel("Energia estimada (Wh)")
    axes[0].margins(y=.2)
    handles, _ = axes[0].get_legend_handles_labels()
    if handles:
        axes[0].legend()
    axes[0].set_title("Trajetórias executadas no simulador · modelo teórico de energia")
    for i, pair in enumerate(pairs):
        value = pair["estimated_energy_reduction_percent"]
        if value is None:
            axes[1].text(i, 0, "sem par\nelegível", ha="center", va="center", fontsize=8)
        else:
            axes[1].bar(i, value, color="#15803d" if value >= 0 else "#b91c1c")
            axes[1].annotate(f"{value:.3f}%", (i, value), ha="center",
                             xytext=(0, 4 if value >= 0 else -12), textcoords="offset points", fontsize=8)
    axes[1].axhline(0, color="#334155", linewidth=.8)
    reductions = [p["estimated_energy_reduction_percent"] for p in pairs if p["comparable"]]
    low, high = min([0., *reductions]), max([0., *reductions])
    margin = max(high - low, 1.) * .2
    axes[1].set_ylim(low - margin, high + margin)
    axes[1].set_xlim(-.6, len(pairs) - .4)
    axes[1].set_ylabel("Redução estimada (%)")
    axes[1].set_xticks(x, labels, rotation=25, ha="right")
    axes[0].grid(axis="y", alpha=.2)
    axes[1].grid(axis="y", alpha=.2)
    fig.text(.02, .005, "Barras claras: par inelegível. Valores negativos: a proposta gastou mais no modelo. Não é bateria medida.", fontsize=8)
    fig.tight_layout(rect=(0, .035, 1, 1))
    fig.savefig(output / "energy_comparison.png", dpi=180)
    fig.savefig(output / "energy_comparison.svg")
    plt.close(fig)
    figures.append("energy_comparison.png")
    trajectories = []
    for pair in pairs:
        positions = []
        for side in ("reference", "proposed"):
            row = pair[side]
            path = _resolve_recorded_path(row.get("run_directory", ""), root) / "telemetry.csv" if row and row.get("run_directory") else None
            samples = _read_csv(path) if path and path.is_file() else []
            points = [(_number(r.get("drone_x_m")), _number(r.get("drone_y_m"))) for r in samples]
            positions.append([p for p in points if None not in p])
        if any(positions):
            trajectories.append((pair, positions))
    # O gráfico é uma amostra visual explicitamente identificada; o resumo usa todos os pares.
    if trajectories:
        shown = trajectories[:6]
        fig, axes = plt.subplots(len(shown), 2, figsize=(10, 4 * len(shown)), squeeze=False)
        for row_index, (pair, positions) in enumerate(shown):
            all_points = [p for side in positions for p in side]
            for column, (side, points) in enumerate(zip(("Referência", "Proposta"), positions)):
                ax = axes[row_index, column]
                if points:
                    xs, ys = zip(*points)
                    ax.plot(xs, ys, color="#475569" if column == 0 else "#0284c7", linewidth=1)
                    ax.scatter(xs[0], ys[0], marker="o", color="#15803d", s=22, label="Início")
                    ax.scatter(xs[-1], ys[-1], marker="x", color="#b91c1c", s=22, label="Fim")
                else:
                    ax.text(.5, .5, "Telemetria indisponível", transform=ax.transAxes, ha="center")
                all_x, all_y = zip(*all_points)
                margin = max(max(all_x) - min(all_x), max(all_y) - min(all_y), 1.) * .06
                ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
                ax.set_ylim(min(all_y) - margin, max(all_y) + margin)
                ax.set_aspect("equal", adjustable="box")
                ax.set_xlabel("Leste local (m)")
                ax.set_ylabel("Norte local (m)")
                ax.set_title(f"{pair['geographic_case']} / {pair['repetition']} · {side}")
                ax.grid(alpha=.2)
        fig.suptitle("Trajetórias medidas no simulador · primeiros seis pares com telemetria disponível")
        fig.tight_layout(rect=(0, 0, 1, .98))
        fig.savefig(output / "trajectory_comparison.png", dpi=160)
        plt.close(fig)
        figures.append("trajectory_comparison.png")
    return figures


def _html(report, figures):
    s = report["summary"]
    rows = []
    for pair in report["pairs"]:
        reference, proposed = pair["reference"] or {}, pair["proposed"] or {}
        reasons = pair["reference_exclusion_reasons"] + pair["proposed_exclusion_reasons"] + pair["pair_exclusion_reasons"]
        status = "Elegível" if pair["comparable"] else "; ".join(dict.fromkeys(reasons))
        rows.append("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in (
            pair["geographic_case"], pair["repetition"], _format(reference.get("estimated_energy_wh")),
            _format(proposed.get("estimated_energy_wh")), _format(reference.get("executed_coverage_percent"), 2),
            _format(proposed.get("executed_coverage_percent"), 2), _format(pair["estimated_energy_reduction_percent"]), status)) + "</tr>")
    if not s["eligible_pairs"]:
        conclusion = "Não há pares elegíveis para concluir economia energética neste conjunto."
    else:
        result = "redução" if s["mean_estimated_energy_reduction_percent"] >= 0 else "aumento"
        conclusion = (f"Nos {s['eligible_pairs']} pares elegíveis de {s['expected_pairs']} previstos, "
                      f"a proposta apresentou {result} médio de {abs(s['mean_estimated_energy_reduction_percent']):.3f}% "
                      f"na energia estimada. Houve {s['positive_pairs']} reduções, {s['negative_pairs']} aumentos "
                      f"e {s['tied_pairs']} empates.")
    contributions = ""
    if report.get("method_comparisons"):
        contributions = "<h2>Contribuição de cada alteração</h2><table><tr><th>Variante versus referência</th><th>Pares elegíveis/previstos</th><th>Redução estimada média por recorte (%)</th></tr>"
        for item in report["method_comparisons"]:
            summary = item["summary"]
            contributions += (f"<tr><td>{escape(item['method'])}</td><td>{summary['eligible_pairs']}/{summary['expected_pairs']}</td>"
                              f"<td>{_format(summary['case_mean_estimated_energy_reduction_percent'])}</td></tr>")
        contributions += "</table><p>Orientação e penalização de subida são contribuições diferentes. Quando a referência é geométrica, o contraste com A* 3D também muda a estratégia de conexão e não isola somente a distância 3D.</p>"
    resolution = ""
    if report.get("time_step_check"):
        resolution = "<h2>Verificação posterior do passo temporal</h2><p>As mesmas rotas foram testadas com passo menor. Isso não altera as médias do lote original e não comprova convergência numérica.</p><table><tr><th>Recorte</th><th>Passo menor (s)</th><th>Comparação válida</th><th>Diagnóstico</th></tr>"
        for item in report["time_step_check"]["cases"]:
            diagnostic = "; ".join(dict.fromkeys(v for v in (
                item.get("refined_reference_error"), item.get("refined_proposed_error")) if v))
            resolution += (f"<tr><td>{escape(item['case'])}</td><td>{escape(item.get('refined_time_step_s',''))}</td>"
                           f"<td>{'Sim' if _true(item.get('comparable')) else 'Não'}</td><td>{escape(diagnostic)}</td></tr>")
        resolution += "</table><p>Falhas ou mudanças relevantes com o passo menor impedem concluir robustez numérica do ganho. O controlador demonstrativo precisa ser validado antes de afirmar economia física de bateria.</p>"
    return ("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>Benchmark de energia estimada</title><style>body{font:16px system-ui;margin:40px auto;padding:0 24px;max-width:1250px;color:#172033;line-height:1.5}h1{line-height:1.2}.notice{background:#fff4ce;padding:18px;border-left:4px solid #b7791f}img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #dbe2ea;padding:8px;text-align:left}th{background:#eef2f6}.scroll{overflow:auto}code{background:#eef2f6;padding:2px 4px}</style>"
            "<h1>Benchmark de energia estimada</h1>"
            f"<p><strong>{escape(report['reference_method'])}</strong> versus <strong>{escape(report['proposed_method'])}</strong>.</p>"
            f"<p>{escape(conclusion)}</p>"
            "<p class='notice'><strong>Resultado de simulação com modelo energético.</strong> Energia calculada a partir da trajetória executada; não há medição elétrica de bateria. Este benchmark não comprova economia real de bateria. Células cobertas representam cobertura geométrica, sem medição de produto depositado.</p>"
            f"<p>Previstos: {s['expected_pairs']} pares. Elegíveis: {s['eligible_pairs']}. Inelegíveis ou ausentes: {s['ineligible_or_missing_pairs']}. Voos registrados nos pares: {s['recorded_flights_in_target_pairs']}.</p>"
            f"<p>Média por terreno (cada terreno com o mesmo peso): {_format(s['case_mean_estimated_energy_reduction_percent'])}%. Redução na soma dos Wh dos pares elegíveis: {_format(s['pooled_estimated_energy_reduction_percent'])}%.</p>"
            + "".join(f"<figure><img src='{escape(name)}' alt='Comparação de energia ou trajetórias'></figure>" for name in figures)
            + "<h2>Todos os pares previstos</h2><p>Redução positiva favorece a proposta; negativa indica aumento. Ausência de resultado permanece no denominador. Barras claras no gráfico indicam pares inelegíveis.</p><div class='scroll'><table><thead><tr>"
            + "".join(f"<th>{v}</th>" for v in ("Terreno", "Repetição", "Referência (Wh estimados)", "Proposta (Wh estimados)", "Cobertura referência (%)", "Cobertura proposta (%)", "Redução estimada (%)", "Situação"))
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            + contributions
            + resolution
            + "<h2>Limites da conclusão</h2><ul>" + "".join(f"<li>{escape(text)}</li>" for text in report["limitations"])
            + "</ul><p>Dados para auditoria: <a href='benchmark.json'>benchmark.json</a>, <a href='pairs.csv'>pairs.csv</a> e <a href='all_recorded_flights.csv'>todos os voos registrados</a>.</p></html>")


def generate_benchmark_report(source: Path, output: Path,
                              reference_method="referencia_2d", proposed_method="proposta_completa",
                              time_step_check: Path | None = None) -> Path:
    """Aceita pasta de comparação, pasta de lote ou CSV acumulado de voos."""
    source, output = Path(source), Path(output)
    if not source.exists():
        raise FileNotFoundError(f"Fonte não encontrada: {source}")
    if output.exists():
        raise FileExistsError(f"Escolha uma pasta nova: {output}")
    if reference_method == proposed_method:
        raise ValueError("Referência e proposta devem ser métodos diferentes.")
    root, rows, expected, protocol, definition, provenance = _collect(source)
    pairs = _pairs(rows, expected, protocol, reference_method, proposed_method)
    summary, cases = _summarize(pairs)
    resolution = None
    if time_step_check is not None:
        folder = Path(time_step_check)
        resolution = {"protocol": json.loads((folder / "protocol.json").read_text(encoding="utf-8")),
                      "cases": _read_csv(folder / "time_step_comparison.csv")}
        provenance.extend([folder / "protocol.json", folder / "time_step_comparison.csv"])
    report = {"schema_version": 1, "reference_method": reference_method, "proposed_method": proposed_method,
              "baseline_planner": protocol.get("baseline_planner", definition.get("baseline_planner", "astar_legacy")),
              "baseline_description": protocol.get("baseline_description", definition.get("baseline_description", "Consulte o protocolo individual do par.")),
              "evidence_kind": "simulator_trajectory_with_estimated_energy",
              "real_battery_saving_proven": False, "summary": summary, "cases": cases, "pairs": pairs,
              "energy_model": protocol.get("energy_model"), "benchmark_definition": definition,
              "method_comparisons": _method_comparisons(rows, expected, protocol, reference_method),
              "time_step_check": resolution,
              "source_files": [{"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                               for p in dict.fromkeys(provenance)],
              "limitations": [
                  "O modelo de energia não substitui tensão e corrente medidas em um drone real; não há prova de bateria física.",
                  "A comparação usa elegibilidade registrada e verifica segurança, cobertura, lacunas e envelope energético; não refaz a simulação.",
                  "Repetições do mesmo terreno não são novos terrenos independentes. Não foram calculados valores-p ou intervalos de confiança de generalização.",
                  "Médias são descritivas dos pares elegíveis. Falhas e pares ausentes são mostrados e permanecem no total previsto.",
                  "Redução percentual média, média por terreno e redução na soma dos Wh têm ponderações diferentes.",
                  "Amostragem, massa, carga, vento, velocidade, controle e critérios devem ser fixados antes de comparar métodos.",
                  "Cobertura é geométrica dos centros de células e não comprova dose ou qualidade agronômica.",
              ]}
    output.mkdir(parents=True, exist_ok=False)
    (output / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    flattened = []
    for pair in pairs:
        entry = {key: value for key, value in pair.items() if key not in ("reference", "proposed")}
        for side in ("reference", "proposed"):
            entry.update({f"{side}_{key}": value for key, value in (pair[side] or {}).items()})
        flattened.append(entry)
    for filename, entries in (("pairs.csv", flattened), ("all_recorded_flights.csv", rows)):
        fields = list(dict.fromkeys(key for entry in entries for key in entry))
        with (output / filename).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields or ["method"])
            writer.writeheader()
            writer.writerows(entries)
    figures = _plots(pairs, root, output)
    (output / "index.html").write_text(_html(report, figures), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pasta de comparação/lote ou CSV acumulado de voos.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", default="referencia_2d")
    parser.add_argument("--proposed", default="proposta_completa")
    parser.add_argument("--time-step-check", type=Path)
    args = parser.parse_args()
    result = generate_benchmark_report(args.source, args.output, args.reference, args.proposed, args.time_step_check)
    print(f"Relatório: {(result / 'index.html').resolve()}")
    print("Energia estimada de trajetórias no simulador; não comprova economia real de bateria.")


if __name__ == "__main__":
    main()
