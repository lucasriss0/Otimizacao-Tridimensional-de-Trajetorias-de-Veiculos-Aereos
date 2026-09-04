from src.scenario import load_scenario


def test_loads_demo_wind_scenario():
    scenario = load_scenario("configs/demo_wind.yaml")
    assert scenario.scenario_id == "demo_wind"
    assert scenario.terrain.topodata.is_file()
    assert scenario.coverage.window.row_start == 20
    assert scenario.simulation.speed_mps == 8
    assert scenario.wind.events[0].at_s > 0
    assert scenario.wind.events[0].wind.speed_mps > 0
    assert scenario.wind.events[1].at_s > scenario.wind.events[0].at_s
    assert scenario.wind.replan_delay_s == 3
    assert scenario.wind.maximum_drift_m == 12
    assert len(scenario.obstacles) == 1
    assert scenario.obstacles[0].name == "ObstacleTreeCenter"
    assert scenario.obstacles[0].safety_radius_m == 60
