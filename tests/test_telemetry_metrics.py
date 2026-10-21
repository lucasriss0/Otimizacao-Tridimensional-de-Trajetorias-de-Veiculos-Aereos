import csv
from dataclasses import replace

import pytest

from src.coppeliasim import SimulationLog, TelemetrySample, _save_simulation_log
from src.scenario import load_scenario
from src.telemetry_metrics import summarize_telemetry


def sample(time, x=0, z=60, violation=False, collision=False, error=0):
    return dict(simulation_time_s=time, drone_x_m=x, drone_y_m=0,
                drone_z_m=z, tracking_error_m=error, clearance_m=z,
                clearance_violation=violation, collision=collision)


def test_measures_known_path_with_irregular_sampling_and_string_flags():
    rows = [sample(1, violation="True", error=3),
            sample(3, 3, 64, collision="True", error=4),
            sample(6, 3, 60, error=0)]
    result = summarize_telemetry(rows, 10)
    assert result["executed_distance_3d_m"] == 9
    assert result["executed_elevation_gain_m"] == 4
    assert result["executed_elevation_loss_m"] == 4
    assert result["executed_normalized_cost"] == 49
    assert result["observed_duration_s"] == 5
    assert result["clearance_violation_duration_s"] == 2
    assert result["collision_duration_s"] == 3
    assert result["mean_tracking_error_m"] == pytest.approx(7 / 3)
    assert result["rmse_tracking_error_m"] == pytest.approx((25 / 3) ** .5)
    assert not result["observed_safe"]


def test_empty_data_does_not_claim_safety_and_single_sample_has_no_distance():
    assert summarize_telemetry([])["minimum_clearance_m"] is None
    assert not summarize_telemetry([])["observed_safe"]
    result = summarize_telemetry([sample(5)])
    assert result["executed_distance_3d_m"] == 0
    assert result["observed_duration_s"] == 0
    assert result["observed_safe"]


@pytest.mark.parametrize("rows", [
    [sample(1), sample(1)], [sample(2), sample(1)],
    [sample(1, x=float("nan"))], [sample(1, collision="unknown")],
])
def test_invalid_measurements_are_rejected(rows):
    with pytest.raises(ValueError):
        summarize_telemetry(rows)


@pytest.mark.parametrize("completed,violation,has_error,expected", [
    (True, False, False, True), (True, True, False, False),
    (False, False, False, False), (True, False, True, False),
])
def test_saved_metrics_separate_completion_and_safety(tmp_path, completed, violation, has_error, expected):
    source = tmp_path / "scenario.yaml"
    source.write_text("id: test", encoding="utf-8")
    scenario = replace(load_scenario("configs/demo_wind.yaml"), output_root=tmp_path / "runs")
    telemetry = TelemetrySample(1, 0, 0, 1, 0, 0, 60, 0, 0, 60,
                                0, "calm", 0, 0, 60, violation, False)
    log = SimulationLog(completed, "test", 1, 1, 1, 0, [telemetry], [], [],
                        error="failure" if has_error else None)
    destination = _save_simulation_log(log, scenario, source)
    with (destination / "metrics.csv").open(encoding="utf-8-sig") as stream:
        row = next(csv.DictReader(stream))
    assert row["mission_completed"] == str(completed)
    assert row["mission_completed_safely"] == str(expected)
    assert row["executed_distance_3d_m"] == "0.0"
