import pytest

from src.wind import (
    WindCostParameters,
    WindEvent,
    WindScenario,
    WindVector,
    calculate_wind_penalty,
)


def test_headwind_costs_more_than_crosswind_and_tailwind():
    params = WindCostParameters(weight=1, crosswind_factor=0.25, reference_speed_mps=5)
    headwind = calculate_wind_penalty(30, 0, WindVector(-5, 0), params)
    crosswind = calculate_wind_penalty(30, 0, WindVector(0, 5), params)
    tailwind = calculate_wind_penalty(30, 0, WindVector(5, 0), params)
    assert headwind == pytest.approx(30)
    assert crosswind == pytest.approx(7.5)
    assert tailwind == 0


def test_calm_wind_does_not_change_cost():
    assert calculate_wind_penalty(30, 0, WindVector()) == 0


def test_scenario_selects_deterministic_event_by_time():
    scenario = WindScenario(
        (
            WindEvent("calmaria", 0, WindVector()),
            WindEvent("rajada", 10, WindVector(4, 0)),
        )
    )
    assert scenario.active_event(9.99).name == "calmaria"
    assert scenario.active_event(10).name == "rajada"


def test_scenario_uses_automatic_calm_before_first_event():
    scenario = WindScenario((WindEvent("rajada", 10, WindVector(4, 0)),))

    assert scenario.active_event(0).wind == WindVector()
    assert scenario.active_event(9.99).name == "calmaria_automatica"
    assert scenario.next_event_index(0) == 0
    assert scenario.next_event_index(10) == 1


def test_rejects_unsorted_events():
    with pytest.raises(ValueError, match="ordenados"):
        WindScenario(
            (
                WindEvent("depois", 10, WindVector()),
                WindEvent("antes", 0, WindVector()),
            )
        )


def test_rejects_events_at_the_same_time():
    with pytest.raises(ValueError, match="diferentes"):
        WindScenario(
            (
                WindEvent("primeiro", 10, WindVector()),
                WindEvent("segundo", 10, WindVector()),
            )
        )
