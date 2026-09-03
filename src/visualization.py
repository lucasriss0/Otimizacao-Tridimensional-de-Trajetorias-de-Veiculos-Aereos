from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.astar import Position


def save_path_figure(
    terrain: np.ndarray,
    path: list[Position],
    start: Position,
    goal: Position,
    output_path: str,
    title: str = "Trajetória calculada pelo A*",
) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    figure, axis = plt.subplots(figsize=(8, 7))

    image = axis.imshow(
        terrain,
        cmap="terrain",
        origin="upper",
    )

    figure.colorbar(
        image,
        ax=axis,
        label="Altitude",
    )

    if path:
        path_rows = [position[0] for position in path]
        path_columns = [position[1] for position in path]

        axis.plot(
            path_columns,
            path_rows,
            color="blue",
            linewidth=3,
            marker="o",
            markersize=5,
            label="Rota A*",
        )

    axis.scatter(
        start[1],
        start[0],
        color="lime",
        edgecolor="black",
        s=150,
        label="Origem",
        zorder=5,
    )

    axis.scatter(
        goal[1],
        goal[0],
        color="red",
        edgecolor="black",
        s=150,
        label="Destino",
        zorder=5,
    )

    axis.set_title(title)
    axis.set_xlabel("Coluna")
    axis.set_ylabel("Linha")
    axis.legend()

    figure.tight_layout()
    figure.savefig(destination, dpi=160)
    plt.close(figure)
