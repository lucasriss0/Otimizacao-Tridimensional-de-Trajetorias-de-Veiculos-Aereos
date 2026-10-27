import csv
import json
from types import SimpleNamespace

import numpy as np
import pytest

from src.coverage import CoverageWindow
from src.executed_coverage import (
    analyze_executed_coverage, assess_flight, export_energy_contrasts,
    measure_executed_coverage,
)
from src.planning_experiments import PlanningCase


def case():
    return PlanningCase("line", np.zeros((3, 5)), 10, 20, 2,
                        CoverageWindow(1, 0, 1, 4), np.zeros((3, 5), bool), (1, 0))


def point(t, x, y=0, active=True):
    return dict(simulation_time_s=t, drone_x_m=x, drone_y_m=y,
                application_active=active)


def test_sparse_segment_covers_between_samples_with_anisotropic_cells():
    summary, mask, cultivable = measure_executed_coverage([point(0, -20), point(1, 20)], case())
    assert summary["executed_coverage_percent"] == 100
    assert summary["executed_covered_area_m2"] == 1000
    assert summary["application_observed_duration_s"] == 1
    assert mask.sum() == cultivable.sum() == 5
    assert not mask[0].any() and not mask[2].any()


def test_dense_and_sparse_path_give_same_coverage_and_return_does_not_double_area():
    sparse = [point(0, -20), point(1, 20)]
    dense = [point(i / 4, x) for i, x in enumerate([-20, -10, 0, 10, 20])]
    a = measure_executed_coverage(sparse, case())[0]
    b = measure_executed_coverage(dense + [point(2, -20)], case())[0]
    assert a["executed_covered_area_m2"] == b["executed_covered_area_m2"]


def test_inactive_application_and_gaps_do_not_bridge_unobserved_area():
    inactive = [point(0, -20), point(.3, -10, active=False),
                point(.6, 10, active=False), point(1, 20)]
    a = measure_executed_coverage(inactive, case())[0]
    b = measure_executed_coverage([point(0, -20), point(10, 20)], case())[0]
    assert a["executed_coverage_percent"] == b["executed_coverage_percent"] == 40
    assert a["coverage_active_segments"] == 0
    assert b["coverage_telemetry_gaps"] == 1
    off = measure_executed_coverage([point(0, 0, active=False), point(1, 20, active=False)], case())[0]
    assert off["executed_coverage_available"] and off["executed_coverage_percent"] == 0


def test_outside_positions_are_not_clamped_to_boundary_and_obstacles_are_excluded():
    outside = measure_executed_coverage([point(0, 100), point(1, 120)], case())[0]
    assert outside["executed_coverage_percent"] == 0
    terrain_case = case()
    terrain_case.obstacle_mask[1, 2] = True
    summary, mask, _ = measure_executed_coverage([point(0, -20), point(1, 20)], terrain_case)
    assert summary["cultivable_cells"] == 4
    assert summary["executed_covered_area_m2"] == 800
    assert summary["executed_coverage_percent"] == 100
    assert not mask[1, 2]


@pytest.mark.parametrize("samples", [
    [point(1, 0), point(1, 10)], [point(2, 0), point(1, 0)],
    [point(0, float("nan"))], [point(0, 0, active="unknown")],
    [{"simulation_time_s": 0, "drone_x_m": 0, "drone_y_m": 0}],
])
def test_invalid_data_is_rejected(samples):
    with pytest.raises(ValueError):
        measure_executed_coverage(samples, case())


def test_single_sample_cannot_claim_complete_observation_and_exports_masks(tmp_path):
    assert not measure_executed_coverage([point(0, 0)], case())[0]["executed_coverage_available"]
    source = tmp_path / "telemetry.csv"
    source.write_text("simulation_time_s,drone_x_m,drone_y_m,application_active\n0,-20,0,True\n1,20,0,True\n", encoding="utf-8")
    output = tmp_path / "coverage"
    result = analyze_executed_coverage(source, case(), output)
    assert result["executed_coverage_percent"] == 100
    assert np.load(output / "coverage_masks.npz")["covered"].sum() == 5


def test_incomplete_unsafe_uncovered_or_unobserved_flights_are_not_comparable(tmp_path):
    coverage = measure_executed_coverage([point(0, -20), point(1, 20)], case())[0]
    energy = {"energy_estimate_available": True, "energy_outside_envelope_intervals": 0}
    good = assess_flight({"mission_completed_safely": "True"}, energy, coverage)
    assert good["energy_comparison_eligible"]
    assert not assess_flight({"mission_completed_safely": "False"}, energy, coverage)["energy_comparison_eligible"]
    for changed in ({"executed_coverage_percent": 99}, {"coverage_telemetry_gaps": 1},
                    {"executed_coverage_available": False}):
        assert not assess_flight({"mission_completed_safely": True}, energy, {**coverage, **changed})["energy_comparison_eligible"]
    assert not assess_flight({"mission_completed_safely": True}, {**energy, "energy_outside_envelope_intervals": 1}, coverage)["energy_comparison_eligible"]
    rows = [{"method": "reference", "estimated_energy_wh": 10., **good},
            {"method": "proposed", "estimated_energy_wh": 8., **good}]
    output = tmp_path / "contrasts.csv"
    export_energy_contrasts(rows, output)
    with output.open(encoding="utf-8-sig") as stream:
        row = next(csv.DictReader(stream))
    assert float(row["estimated_energy_reduction_percent"]) == 20
    rows[1].update(energy_comparison_eligible=False,
                   energy_comparison_exclusion_reasons="cobertura_insuficiente")
    export_energy_contrasts(rows, output)
    with output.open(encoding="utf-8-sig") as stream:
        row = next(csv.DictReader(stream))
    assert row["comparable"] == "False" and row["estimated_energy_reduction_percent"] == ""
