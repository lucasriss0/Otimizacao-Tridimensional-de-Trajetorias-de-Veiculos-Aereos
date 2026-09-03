from src.astar import astar
from src.terrain import create_example_terrain
from src.visualization import save_path_figure


def main() -> None:
    terrain = create_example_terrain()

    start = (3, 0)
    goal = (3, 6)

    result = astar(
        terrain=terrain,
        start=start,
        goal=goal,
        climb_weight=3.0,
    )

    if not result.success:
        print(f"Falha: {result.error}")
        return

    print("Caminho encontrado!")
    print(f"Rota: {result.path}")
    print(f"Custo total: {result.total_cost:.2f}")
    print(f"Nós expandidos: {result.expanded_nodes}")
    print(f"Quantidade de posições: {len(result.path)}")

    save_path_figure(
        terrain=terrain,
        path=result.path,
        start=start,
        goal=goal,
        output_path="output/primeira_rota.png",
    )

    print("Imagem salva em output/primeira_rota.png")


if __name__ == "__main__":
    main()