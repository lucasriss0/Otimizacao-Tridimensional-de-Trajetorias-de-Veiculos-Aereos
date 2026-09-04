from src.experiments import compare_wind_cases
from src.obstacles import create_obstacle_mask
from src.scenario import load_scenario
from src.terrain import load_topodata


def test_comparison_is_deterministic_and_complete():
    scenario = load_scenario("configs/demo_wind.yaml")
    first = compare_wind_cases(scenario)
    second = compare_wind_cases(scenario)
    assert [item.case for item in first] == [
        "sem_vento", "vento_fixo", "vento_variavel_replanejado"
    ]
    assert [item.path for item in first] == [item.path for item in second]
    assert all(item.coverage_percent == 100 for item in first)

    terrain = load_topodata(
        scenario.terrain.topodata,
        scenario.terrain.size,
        scenario.terrain.center_lat,
        scenario.terrain.center_lon,
        scenario.terrain.area_m,
    ).elevation
    cell_size = scenario.terrain.area_m / terrain.shape[0]
    blocked = create_obstacle_mask(
        terrain.shape, list(scenario.obstacles), cell_size, cell_size
    )
    assert blocked.any()
    assert all(not blocked[cell] for result in first for cell in result.path)
