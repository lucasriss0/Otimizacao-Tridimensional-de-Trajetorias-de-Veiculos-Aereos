"""Referência geométrica de faixas: sem A*, sem otimização por elevação.

Representa regras operacionais explícitas, não o software interno de um fabricante.
Desvios usam visibilidade entre vértices de exclusões e Dijkstra por distância XY.
"""
from heapq import heappop, heappush
from math import ceil, floor, hypot
from time import perf_counter

import numpy as np

from src.coverage import generate_boustrophedon_targets
from src.executed_coverage import measure_executed_coverage
from src.metrics import calculate_path_metrics

BASELINE_METHOD = "convencional_geometrico"
BASELINE_VERSION = "parallel_geometric_v1"
BASELINE_DESCRIPTION = (
    "Faixas paralelas ao maior lado do talhão (horizontal no empate); "
    "conexões retas e desvios geométricos por visibilidade/Dijkstra XY, sem A*. "
    "Sem custo de relevo ou energia na escolha da rota. Aproximação operacional, "
    "não reprodução do algoritmo fechado de fabricante."
)


def intersects_rectangle(a, b, rectangle):
    """Interseção com o interior aberto; permite acompanhar a borda segura."""
    enter, leave = 0., 1.
    for coordinate, low, high in ((0, rectangle[0], rectangle[2]),
                                  (1, rectangle[1], rectangle[3])):
        delta = b[coordinate] - a[coordinate]
        if abs(delta) < 1e-12:
            if not low + 1e-10 < a[coordinate] < high - 1e-10:
                return False
        else:
            t1, t2 = (low-a[coordinate])/delta, (high-a[coordinate])/delta
            enter, leave = max(enter, min(t1,t2)), min(leave, max(t1,t2))
            if enter >= leave - 1e-10:
                return False
    return enter < leave - 1e-10


class GeometricConnections:
    """Grafo dos cantos de áreas proibidas; nunca expande células do grid."""
    def __init__(self, mask, cell_x_m, cell_y_m):
        self.cell_x_m, self.cell_y_m = cell_x_m, cell_y_m
        # A máscara já contém o raio de segurança. Mais .01 célula impede
        # atalhos pelos pontos de contato de duas áreas bloqueadas.
        self.rectangles = [(r-.51,c-.51,r+.51,c+.51) for r,c in np.argwhere(mask)]
        corners = {(float(r),float(c)) for a,b,d,e in self.rectangles
                   for r,c in ((a,b),(a,e),(d,b),(d,e))}
        self.corners = sorted(p for p in corners if 0 <= p[0] <= mask.shape[0]-1
            and 0 <= p[1] <= mask.shape[1]-1 and self.visible(p,p))
        self.edges = [[] for _ in self.corners]
        for i,a in enumerate(self.corners):
            for j in range(i):
                b = self.corners[j]
                if self.visible(a,b):
                    length = self.distance(a,b)
                    self.edges[i].append((j,length))
                    self.edges[j].append((i,length))

    def distance(self, a, b):
        return hypot((b[0]-a[0])*self.cell_y_m, (b[1]-a[1])*self.cell_x_m)

    def visible(self, a, b):
        return not any(intersects_rectangle(a,b,rectangle) for rectangle in self.rectangles)

    def connect(self, a, b):
        a,b = tuple(a),tuple(b)
        if self.visible(a,b):
            return [a,b], 0
        points = [*self.corners,a,b]
        start, goal = len(points)-2, len(points)-1
        edges = [list(items) for items in self.edges]+[[],[]]
        for i in (start,goal):
            if not self.visible(points[i],points[i]):
                raise ValueError("Alvo dentro da exclusão geométrica de um obstáculo.")
            for j in range(len(self.corners)):
                if self.visible(points[i],points[j]):
                    length = self.distance(points[i],points[j])
                    edges[i].append((j,length))
                    edges[j].append((i,length))
        queue, costs, previous, expanded = [(0.,start)], {start:0.}, {}, 0
        while queue:
            cost,node = heappop(queue)
            if cost > costs[node]+1e-9:
                continue
            expanded += 1
            if node == goal:
                route = [points[node]]
                while node != start:
                    node = previous[node]
                    route.append(points[node])
                return list(reversed(route)), expanded
            for neighbor,length in edges[node]:
                candidate = cost+length
                if candidate < costs.get(neighbor,float('inf'))-1e-9:
                    costs[neighbor],previous[neighbor] = candidate,node
                    heappush(queue,(candidate,neighbor))
        raise ValueError("Não existe conexão geométrica segura entre as passadas.")


def plan_conventional(case, evaluation_weight=10.):
    """Faixas fixadas pela geometria, independentemente das altitudes/Wh."""
    from src.planning_experiments import PlanningTrial
    case.validate()
    started = perf_counter()
    width = (case.window.col_end-case.window.col_start+1)*case.cell_x_m
    height = (case.window.row_end-case.window.row_start+1)*case.cell_y_m
    orientation = "horizontal" if width >= height else "vertical"
    perpendicular = case.cell_y_m if orientation == "horizontal" else case.cell_x_m
    spacing = max(1,floor((case.stripe_spacing_m or case.swath_m)/perpendicular))
    targets = generate_boustrophedon_targets(case.terrain,spacing,case.window,orientation)
    targets = [target for target in targets if not case.obstacle_mask[target]]
    mission = [case.launch,*targets,case.launch]
    mission = [p for i,p in enumerate(mission) if i == 0 or p != mission[i-1]]
    route, expanded, error = [],0,None
    try:
        connector = GeometricConnections(case.obstacle_mask,case.cell_x_m,case.cell_y_m)
        for a,b in zip(mission,mission[1:]):
            segment,count = connector.connect(a,b)
            expanded += count
            for start,end in zip(segment,segment[1:]):
                steps = max(1,ceil(connector.distance(start,end)/min(case.cell_x_m,case.cell_y_m)))
                if not route:
                    route.append(start)
                for step in range(1,steps+1):
                    point = end if step == steps else tuple(float(x+(y-x)*step/steps) for x,y in zip(start,end))
                    if point != route[-1]:
                        route.append(point)
        if not targets or len(route)<2:
            raise ValueError("A missão convencional não contém passadas executáveis.")
    except ValueError as failure:
        error = str(failure)
    samples = [dict(simulation_time_s=i,drone_x_m=(p[1]-(case.terrain.shape[1]-1)/2)*case.cell_x_m,
        drone_y_m=((case.terrain.shape[0]-1)/2-p[0])*case.cell_y_m,application_active=True)
        for i,p in enumerate(route)]
    coverage = measure_executed_coverage(samples,case)[0]["executed_coverage_percent"] or 0.
    eligible = error is None and coverage+1e-9 >= 100.
    if error is None and not eligible:
        error = "Cobertura convencional abaixo do mínimo exigido."
    elapsed = perf_counter()-started
    metrics = calculate_path_metrics(BASELINE_METHOD,case.terrain,route,case.cell_x_m,
        case.cell_y_m,evaluation_weight,elapsed,expanded) if len(route)>1 else None
    return PlanningTrial(case.name,BASELINE_METHOD,orientation,0.,evaluation_weight,error is None,
        eligible,eligible,error,coverage,metrics.horizontal_distance_m if metrics else None,
        metrics.distance_3d_m if metrics else None,metrics.elevation_gain_m if metrics else None,
        metrics.normalized_energy_cost if metrics else None,elapsed,expanded,route)
