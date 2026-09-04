from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass(frozen=True)
class WindVector:
    """Vetor horizontal do vento no referencial local: +X=leste, +Y=norte."""

    east_mps: float = 0.0
    north_mps: float = 0.0

    @property
    def speed_mps(self) -> float:
        return hypot(self.east_mps, self.north_mps)


@dataclass(frozen=True)
class WindEvent:
    name: str
    at_s: float
    wind: WindVector

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("O evento de vento precisa ter um nome.")
        if self.at_s < 0:
            raise ValueError("O instante do evento de vento não pode ser negativo.")


@dataclass(frozen=True)
class WindCostParameters:
    """Pesos de um custo normalizado; os valores não representam energia em joules."""

    weight: float = 1.0
    crosswind_factor: float = 0.25
    reference_speed_mps: float = 5.0

    def __post_init__(self) -> None:
        if self.weight < 0 or self.crosswind_factor < 0:
            raise ValueError("Os pesos do vento não podem ser negativos.")
        if self.reference_speed_mps <= 0:
            raise ValueError("A velocidade de referência do vento precisa ser positiva.")


@dataclass(frozen=True)
class WindScenario:
    events: tuple[WindEvent, ...]
    cost: WindCostParameters = WindCostParameters()
    visual_acceleration_gain: float = 0.05
    maximum_visual_acceleration: float = 0.5
    replan_delay_s: float = 0.0
    maximum_drift_m: float = 0.0

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("O cenário precisa conter ao menos um evento de vento.")
        if tuple(sorted(self.events, key=lambda item: item.at_s)) != self.events:
            raise ValueError("Os eventos de vento precisam estar ordenados por tempo.")
        if any(
            current.at_s >= following.at_s
            for current, following in zip(self.events, self.events[1:])
        ):
            raise ValueError(
                "Os eventos de vento precisam ter instantes diferentes e crescentes."
            )
        if (
            self.visual_acceleration_gain < 0
            or self.maximum_visual_acceleration < 0
            or self.replan_delay_s < 0
            or self.maximum_drift_m < 0
        ):
            raise ValueError("Os parâmetros da perturbação visual não podem ser negativos.")

    def active_event(self, simulation_time_s: float) -> WindEvent:
        active = WindEvent("calmaria_automatica", 0.0, WindVector())
        for event in self.events:
            if event.at_s > simulation_time_s:
                break
            active = event
        return active

    def next_event_index(self, simulation_time_s: float) -> int:
        """Índice do primeiro evento que ainda não ocorreu."""

        return next(
            (
                index
                for index, event in enumerate(self.events)
                if event.at_s > simulation_time_s
            ),
            len(self.events),
        )


def calculate_wind_penalty(
    movement_east_m: float,
    movement_north_m: float,
    wind: WindVector | None,
    parameters: WindCostParameters | None = None,
) -> float:
    """Custo não negativo por vento contrário e lateral.

    Vento a favor não reduz o custo-base, mantendo a heurística de distância
    como limite inferior admissível.
    """

    if wind is None or wind.speed_mps <= 1e-12:
        return 0.0
    params = parameters or WindCostParameters()
    distance = hypot(movement_east_m, movement_north_m)
    if distance <= 1e-12:
        return 0.0

    move_east = movement_east_m / distance
    move_north = movement_north_m / distance
    wind_east = wind.east_mps / wind.speed_mps
    wind_north = wind.north_mps / wind.speed_mps
    alignment = move_east * wind_east + move_north * wind_north
    crosswind = abs(move_east * wind_north - move_north * wind_east)
    normalized_speed = wind.speed_mps / params.reference_speed_mps
    directional_factor = max(0.0, -alignment) + params.crosswind_factor * crosswind
    return params.weight * distance * normalized_speed * directional_factor
