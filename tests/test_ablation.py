import csv
import json
from pathlib import Path

import numpy as np
import pytest

from src.ablation import METHODS, ideal_samples, run_ablation, select_ablation_plans
from src.planning_experiments import synthetic_cases
from src.coverage_comparison import compare_coverage_flights


def test_five_methods_isolate_planning_weights_and_preserve_mission():
    case = synthetic_cases()[0]
    plans = select_ablation_plans(case)
    assert tuple(p.method for p in plans) == METHODS
    assert [p.planning_climb_weight for p in plans] == [0, 0, 10, 0, 10]
    assert all(p.evaluation_climb_weight == 10 for p in plans)
    assert all(p.path[0] == p.path[-1] == case.launch for p in plans)
    assert all(p.eligible and p.coverage_percent == 100 for p in plans)
    assert all(p.normalized_cost == pytest.approx(plans[0].normalized_cost) for p in plans)


def test_ideal_path_has_correct_duration_including_closure():
    case = synthetic_cases()[0]
    samples = ideal_samples(case, [(0, 0), (0, 1), (0, 0)], 2)
    assert [s["simulation_time_s"] for s in samples] == [0, 5, 10]
    assert samples[0]["drone_x_m"] == samples[-1]["drone_x_m"]
    with pytest.raises(ValueError):
        ideal_samples(case, [(0, 0)], 0)
    with pytest.raises(ValueError):
        select_ablation_plans(case, 0)


def test_offline_suite_keeps_all_cases_ties_and_provenance(tmp_path):
    output = run_ablation(tmp_path / "suite")
    with (output / "ablation.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 30
    assert all(r["trajectory_kind"] == "ideal_constant_3d_speed" for r in rows)
    assert all(r["energy_calibrated"] == "False" for r in rows)
    with (output / "effects.csv").open(encoding="utf-8-sig") as stream:
        effects = list(csv.DictReader(stream))
    assert len(effects) == 36
    assert all(abs(float(r["estimated_energy_reduction_percent"])) < 1e-8
               for r in effects if r["case"] == "flat_clear")
    assert (output / rows[0]["route_file"]).exists()
    with pytest.raises(FileExistsError):
        run_ablation(output)


def test_five_flights_can_be_prepared_without_simulator(tmp_path):
    output = compare_coverage_flights(Path("configs/demo_coverage.yaml"), tmp_path / "flights",
                                     dry_run=True, ablation=True)
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    assert tuple(p["method"] for p in protocol["plans"]) == METHODS
    assert len(list(output.glob("planned_*.csv"))) == 5
